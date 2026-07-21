#!/usr/bin/env python3
"""Local aiohttp service for reading Outlook mail through Microsoft Graph."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import quote, urlencode

from aiohttp import web


SERVER_DIR = Path(__file__).resolve().parent
OUTLOOK_DIR = SERVER_DIR.parent
PROJECT_DIR = OUTLOOK_DIR.parent
STATIC_DIR = SERVER_DIR / "static"
LOG_DIR = SERVER_DIR / "log"
LOG_FILE = LOG_DIR / "server.log"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from outlook.mailbox_graph import (  # noqa: E402
    DEFAULT_ACCOUNT_DIR,
    GraphAccount,
    GraphMailboxClient,
    GraphMailboxError,
)
from outlook.server import __version__ as SERVICE_VERSION  # noqa: E402
from outlook.server.auth_service import (  # noqa: E402
    SESSION_COOKIE,
    MailboxAuthService,
    MailboxUser,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8780
LOGGER_NAME = "outlook.server"
T = TypeVar("T")


@dataclass(frozen=True)
class ServerConfig:
    accounts_dir: Path = DEFAULT_ACCOUNT_DIR
    use_system_proxy: bool = False
    graph_timeout: int = 30
    request_timeout: int = 90
    session_ttl: int = 8 * 60 * 60


CONFIG_KEY = web.AppKey("config", ServerConfig)
LOGGER_KEY = web.AppKey("logger", logging.Logger)
AUTH_KEY = web.AppKey("auth", MailboxAuthService)


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure console output and a rotating log under server/log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def json_error(message: str, status: int) -> web.Response:
    return web.json_response(
        {"ok": False, "error": message, "message": message},
        status=status,
        headers={"Cache-Control": "no-store"},
    )


@web.middleware
async def error_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Any],
) -> web.StreamResponse:
    try:
        response = await handler(request)
    except GraphMailboxError as exc:
        request.app[LOGGER_KEY].warning("Graph mailbox request failed: %s", exc)
        return json_error(str(exc), 400)
    except asyncio.TimeoutError:
        request.app[LOGGER_KEY].warning("Request timed out: %s", request.path)
        return json_error("mailbox request timed out", 504)
    except web.HTTPException as exc:
        if request.path.startswith("/api/"):
            return json_error(exc.reason, exc.status)
        raise
    except Exception:
        request.app[LOGGER_KEY].exception("Unhandled request error: %s", request.path)
        return json_error("internal server error", 500)

    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@web.middleware
async def access_log_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Any],
) -> web.StreamResponse:
    started = time.perf_counter()
    response = await handler(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    request.app[LOGGER_KEY].info(
        "%s %s %s status=%s duration_ms=%.1f",
        request.remote or "-",
        request.method,
        request.path,
        response.status,
        elapsed_ms,
    )
    return response


def make_client(config: ServerConfig) -> GraphMailboxClient:
    return GraphMailboxClient(
        account_dir=config.accounts_dir,
        timeout=config.graph_timeout,
        use_system_proxy=config.use_system_proxy,
    )


def load_account(client: GraphMailboxClient, email: str) -> GraphAccount:
    accounts = client.load_accounts(email)
    if len(accounts) != 1:
        raise GraphMailboxError(f"Expected one account for {email}, got {len(accounts)}")
    return accounts[0]


async def run_graph_call(config: ServerConfig, callback: Callable[[], T]) -> T:
    return await asyncio.wait_for(
        asyncio.to_thread(callback),
        timeout=config.request_timeout,
    )


def request_host_name(request: web.Request) -> str:
    value = (request.headers.get("Host") or "").strip()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else ""
    if value.count(":") == 1:
        value = value.rsplit(":", 1)[0]
    return value


def is_local_whitelist_request(request: web.Request) -> bool:
    return request_host_name(request) == "127.0.0.1" and request.remote == "127.0.0.1"


def auth_user(request: web.Request) -> MailboxUser | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    user = request.app[AUTH_KEY].user_from_token(token)
    if user is not None and user.access_all and not is_local_whitelist_request(request):
        request.app[AUTH_KEY].logout(token)
        return None
    return user


def require_auth_user(request: web.Request) -> MailboxUser:
    user = auth_user(request)
    if user is None:
        raise web.HTTPUnauthorized(reason="login required")
    return user


def authorize_mailbox_email(request: web.Request, user: MailboxUser, email: str) -> str:
    email = email.strip()
    if user.access_all:
        if not email:
            raise web.HTTPBadRequest(reason="mailbox email is required")
        account = request.app[AUTH_KEY].find_account(email)
        if account is None:
            raise web.HTTPNotFound(reason="mailbox account not found")
        return account.email
    if email.lower() != user.email.lower():
        raise web.HTTPForbidden(reason="mailbox access is limited to the logged-in account")
    return user.email


def requested_email(request: web.Request, user: MailboxUser) -> str:
    email = request.query.get("email") or ("" if user.access_all else user.email)
    return authorize_mailbox_email(request, user, email)


def requested_mailbox_email(request: web.Request, user: MailboxUser) -> str:
    return authorize_mailbox_email(request, user, request.match_info.get("email", ""))


def latest_subject_api_url(mailbox: str, recipient: str = "") -> str:
    path = f"/api/mailboxes/{quote(mailbox, safe='@')}/messages/latest"
    return f"{path}?{urlencode({'recipient': recipient})}" if recipient else path


async def read_json_body(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(reason="request body must be valid JSON") from exc
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(reason="request body must be a JSON object")
    return data


def positive_int_query(
    request: web.Request,
    name: str,
    default: int,
    maximum: int,
) -> int:
    raw = (request.query.get(name) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=f"query parameter '{name}' must be an integer") from exc
    if value < 1 or value > maximum:
        raise web.HTTPBadRequest(reason=f"query parameter '{name}' must be between 1 and {maximum}")
    return value


async def handle_root(request: web.Request) -> web.StreamResponse:
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return web.FileResponse(index_file)
    return web.json_response(
        {
            "ok": True,
            "service": "outlook-mail-server",
            "version": SERVICE_VERSION,
            "endpoints": [
                "/health",
                "/api/accounts",
                "/api/folders?email=<address>",
                "/api/messages?email=<address>&folder=inbox&top=20",
                "/api/mailboxes/<address>/recipients",
                "/api/mailboxes/<address>/messages/latest?recipient=<address>",
            ],
        }
    )


async def handle_mailbox_page(request: web.Request) -> web.StreamResponse:
    token = request.cookies.get(SESSION_COOKIE, "")
    entry_token = (request.query.get("entry") or "").strip()
    user = request.app[AUTH_KEY].enter_mailbox(token, entry_token)
    if user is None or (user.access_all and not is_local_whitelist_request(request)):
        request.app[AUTH_KEY].logout(token)
        response = web.HTTPFound("/?session=expired")
        response.del_cookie(SESSION_COOKIE, path="/")
        raise response
    return web.FileResponse(STATIC_DIR / "mailbox.html")


async def handle_health(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    return web.json_response(
        {
            "ok": True,
            "service": "outlook-mail-server",
            "version": SERVICE_VERSION,
            "time": utc_now(),
            "accounts_dir_ready": config.accounts_dir.is_dir(),
        }
    )


async def handle_auth_query(request: web.Request) -> web.Response:
    data = await read_json_body(request)
    email = str(data.get("email") or data.get("username") or "").strip()
    password = str(data.get("password") or "")
    local_whitelist = is_local_whitelist_request(request)
    users = request.app[AUTH_KEY].list_users() if local_whitelist else []
    user = (
        MailboxUser(email="127.0.0.1", source_file="", access_all=True)
        if local_whitelist
        else request.app[AUTH_KEY].query_user(email, password)
    )
    request.app[LOGGER_KEY].info(
        "Auth query email=%s ok=%s local_whitelist=%s host=%s remote=%s",
        "127.0.0.1" if local_whitelist else email or "-",
        bool(user),
        local_whitelist,
        request_host_name(request) or "-",
        request.remote or "-",
    )
    if user is None:
        return json_error("邮箱或密码错误", 401)
    return web.json_response(
        {
            "ok": True,
            "username": user.email,
            "email": "" if user.access_all else user.email,
            "source_file": user.source_file,
            "active_session_count": request.app[AUTH_KEY].active_session_count(user.email),
            "accounts_dir_ready": request.app[CONFIG_KEY].accounts_dir.is_dir(),
            "local_whitelist": local_whitelist,
            "access_all": user.access_all,
            "account_count": len(users) if user.access_all else 1,
        },
        headers={"Cache-Control": "no-store"},
    )


async def handle_auth_login(request: web.Request) -> web.Response:
    data = await read_json_body(request)
    email = str(data.get("email") or data.get("username") or "").strip()
    password = str(data.get("password") or "")
    local_whitelist = is_local_whitelist_request(request)
    login_result = (
        request.app[AUTH_KEY].login_local_whitelist()
        if local_whitelist
        else request.app[AUTH_KEY].login(email, password)
    )
    request.app[LOGGER_KEY].info(
        "Auth login email=%s ok=%s local_whitelist=%s host=%s remote=%s",
        "127.0.0.1" if local_whitelist else email or "-",
        bool(login_result),
        local_whitelist,
        request_host_name(request) or "-",
        request.remote or "-",
    )
    if login_result is None:
        return json_error("邮箱或密码错误", 401)

    token, entry_token, user = login_result
    config = request.app[CONFIG_KEY]
    account_count = len(request.app[AUTH_KEY].list_users()) if user.access_all else 1
    response = web.json_response(
        {
            "ok": True,
            "username": user.email,
            "email": "" if user.access_all else user.email,
            "source_file": user.source_file,
            "entry_token": entry_token,
            "expires_in": config.session_ttl,
            "active_session_count": request.app[AUTH_KEY].active_session_count(user.email),
            "local_whitelist": local_whitelist,
            "access_all": user.access_all,
            "account_count": account_count,
        },
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.session_ttl,
        httponly=True,
        secure=request.secure,
        samesite="Lax",
        path="/",
    )
    return response


async def handle_auth_me(request: web.Request) -> web.Response:
    token = request.cookies.get(SESSION_COOKIE, "")
    user = auth_user(request)
    if user is None:
        return web.json_response(
            {
                "authenticated": False,
                "local_whitelist": is_local_whitelist_request(request),
            },
            headers={"Cache-Control": "no-store"},
        )
    entry_token = request.app[AUTH_KEY].renew_entry_token(token)
    return web.json_response(
        {
            "authenticated": True,
            "username": user.email,
            "email": "" if user.access_all else user.email,
            "entry_token": entry_token,
            "active_session_count": request.app[AUTH_KEY].active_session_count(user.email),
            "local_whitelist": user.access_all,
            "access_all": user.access_all,
            "account_count": len(request.app[AUTH_KEY].list_users()) if user.access_all else 1,
        },
        headers={"Cache-Control": "no-store"},
    )


async def handle_auth_logout(request: web.Request) -> web.Response:
    request.app[AUTH_KEY].logout(request.cookies.get(SESSION_COOKIE, ""))
    response = web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})
    response.del_cookie(SESSION_COOKIE, path="/")
    return response


async def handle_accounts(request: web.Request) -> web.Response:
    user = require_auth_user(request)
    users = request.app[AUTH_KEY].list_users() if user.access_all else [user]
    return web.json_response(
        {
            "ok": True,
            "count": len(users),
            "access_all": user.access_all,
            "accounts": [
                {"email": account.email, "source": account.source_file}
                for account in users
            ],
        }
    )


async def handle_folders(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    user = require_auth_user(request)
    email = requested_email(request, user)
    recursive = (request.query.get("recursive") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }

    def fetch() -> list[dict[str, Any]]:
        client = make_client(config)
        try:
            account = load_account(client, email)
            access_token = client.get_access_token(account)
            return [asdict(folder) for folder in client.list_folders(access_token, recursive=recursive)]
        finally:
            client.session.close()

    folders = await run_graph_call(config, fetch)
    return web.json_response(
        {"ok": True, "email": email, "count": len(folders), "folders": folders}
    )


async def handle_messages(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    user = require_auth_user(request)
    email = requested_email(request, user)
    folder = (request.query.get("folder") or "inbox").strip()
    top = positive_int_query(request, "top", default=20, maximum=100)

    def fetch() -> list[dict[str, Any]]:
        client = make_client(config)
        try:
            account = load_account(client, email)
            access_token = client.get_access_token(account)
            return client.list_message_titles(access_token, folder, top=top)
        finally:
            client.session.close()

    messages = await run_graph_call(config, fetch)
    return web.json_response(
        {
            "ok": True,
            "email": email,
            "folder": folder,
            "count": len(messages),
            "messages": messages,
        }
    )


async def handle_mailbox_recipients(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    user = require_auth_user(request)
    email = requested_mailbox_email(request, user)
    top_per_folder = positive_int_query(request, "top", default=200, maximum=1000)
    folder_ids = ("inbox", "junkemail")

    def fetch() -> list[dict[str, Any]]:
        client = make_client(config)
        try:
            account = load_account(client, email)
            access_token = client.get_access_token(account)
            return client.list_recipient_addresses(
                access_token,
                account.email,
                folder_ids=folder_ids,
                top_per_folder=top_per_folder,
            )
        finally:
            client.session.close()

    recipients = await run_graph_call(config, fetch)
    for recipient in recipients:
        recipient["latest_subject_url"] = latest_subject_api_url(
            email,
            str(recipient.get("address") or ""),
        )
    return web.json_response(
        {
            "ok": True,
            "mailbox": email,
            "count": len(recipients),
            "source_folders": list(folder_ids),
            "recipients": recipients,
        }
    )


async def handle_latest_message_title(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    user = require_auth_user(request)
    email = requested_mailbox_email(request, user)
    folder = (request.query.get("folder") or "inbox").strip()
    recipient = (request.query.get("recipient") or "").strip()
    scan_limit = positive_int_query(request, "scan", default=500, maximum=5000)

    def fetch() -> dict[str, Any] | None:
        client = make_client(config)
        try:
            account = load_account(client, email)
            access_token = client.get_access_token(account)
            return client.latest_message_title(
                access_token,
                folder_id=folder,
                recipient=recipient,
                scan_limit=scan_limit,
            )
        finally:
            client.session.close()

    message = await run_graph_call(config, fetch)
    return web.json_response(
        {
            "ok": True,
            "mailbox": email,
            "recipient": recipient or None,
            "folder": folder,
            "found": message is not None,
            "subject": None if message is None else str(message.get("subject") or ""),
        }
    )


async def on_startup(app: web.Application) -> None:
    config = app[CONFIG_KEY]
    app[LOGGER_KEY].info(
        "Outlook mail server starting version=%s accounts_dir=%s static_dir=%s log_file=%s",
        SERVICE_VERSION,
        config.accounts_dir,
        STATIC_DIR,
        LOG_FILE,
    )


async def on_cleanup(app: web.Application) -> None:
    app[LOGGER_KEY].info("Outlook mail server stopped")


def create_app(
    config: ServerConfig | None = None,
    logger: logging.Logger | None = None,
) -> web.Application:
    config = config or ServerConfig()
    logger = logger or logging.getLogger(LOGGER_NAME)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    app = web.Application(middlewares=[access_log_middleware, error_middleware])
    app[CONFIG_KEY] = config
    app[LOGGER_KEY] = logger
    app[AUTH_KEY] = MailboxAuthService(config.accounts_dir, session_ttl=config.session_ttl)
    app.router.add_get("/", handle_root)
    app.router.add_get("/mailbox", handle_mailbox_page)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/api/auth/query", handle_auth_query)
    app.router.add_post("/api/auth/login", handle_auth_login)
    app.router.add_get("/api/auth/me", handle_auth_me)
    app.router.add_post("/api/auth/logout", handle_auth_logout)
    app.router.add_get("/api/accounts", handle_accounts)
    app.router.add_get("/api/folders", handle_folders)
    app.router.add_get("/api/messages", handle_messages)
    app.router.add_get("/api/mailboxes/{email}/recipients", handle_mailbox_recipients)
    app.router.add_get("/api/mailboxes/{email}/messages/latest", handle_latest_message_title)
    app.router.add_static("/static/", STATIC_DIR, name="static", show_index=False)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def resolve_accounts_dir(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path.resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local aiohttp Outlook mail server")
    parser.add_argument("--host", default=os.environ.get("OUTLOOK_SERVER_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=env_int("OUTLOOK_SERVER_PORT", DEFAULT_PORT),
    )
    parser.add_argument(
        "--accounts-dir",
        default=os.environ.get("OUTLOOK_ACCOUNTS_DIR", str(DEFAULT_ACCOUNT_DIR)),
        help="Directory containing Graph account token files.",
    )
    parser.add_argument(
        "--graph-timeout",
        type=int,
        default=env_int("OUTLOOK_GRAPH_TIMEOUT", 30),
        help="Timeout in seconds for each Graph HTTP request.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=env_int("OUTLOOK_REQUEST_TIMEOUT", 90),
        help="Overall timeout in seconds for one API request.",
    )
    parser.add_argument(
        "--session-ttl",
        type=int,
        default=env_int("OUTLOOK_SESSION_TTL", 8 * 60 * 60),
        help="Login session lifetime in seconds.",
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
        help="Use HTTP_PROXY and HTTPS_PROXY for Microsoft Graph requests.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("OUTLOOK_SERVER_LOG_LEVEL", "INFO"),
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging(args.log_level)
    config = ServerConfig(
        accounts_dir=resolve_accounts_dir(args.accounts_dir),
        use_system_proxy=args.use_system_proxy,
        graph_timeout=max(1, args.graph_timeout),
        request_timeout=max(1, args.request_timeout),
        session_ttl=max(60, args.session_ttl),
    )
    app = create_app(config=config, logger=logger)
    logger.info("Listening on http://%s:%s", args.host, args.port)
    web.run_app(
        app,
        host=args.host,
        port=args.port,
        print=None,
        access_log=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
