# -*- coding: utf-8 -*-
"""
Standalone Microsoft OAuth -> Graph refresh_token extractor.

Reads Outlook credentials from graph_refresh_token/.env by default and writes
the result under graph_refresh_token/out/. This is intentionally separate
from the root extract_graph_tokens.py so the flow can be studied and evolved
without changing the existing pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
OUT_DIR = BASE_DIR / "out"

DEFAULT_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
DEFAULT_REDIRECT_URI = "http://localhost"
DEFAULT_SCOPE = "offline_access https://graph.microsoft.com/Mail.Read"
AUTHORIZE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


class OAuthFlowError(RuntimeError):
    pass


@dataclass
class GraphOAuthConfig:
    email: str
    password: str
    client_id: str = DEFAULT_CLIENT_ID
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scope: str = DEFAULT_SCOPE
    out_dir: Path = OUT_DIR
    use_system_proxy: bool = True
    save_debug_html: bool = False


def _bool_env(value: str | None, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: Path = ENV_PATH) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def resolve_output_dir(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def config_from_env(path: Path = ENV_PATH, require_credentials: bool = True) -> GraphOAuthConfig:
    file_env = load_dotenv(path)

    def val(name: str, default: str = "") -> str:
        return os.environ.get(name) or file_env.get(name) or default

    email = val("OUTLOOK_EMAIL").strip()
    password = val("OUTLOOK_PASSWORD")
    if require_credentials and (not email or not password):
        raise OAuthFlowError(
            f"Missing OUTLOOK_EMAIL/OUTLOOK_PASSWORD. Copy {path.name}.example to {path.name} and fill them."
        )
    return GraphOAuthConfig(
        email=email,
        password=password,
        client_id=val("GRAPH_CLIENT_ID", DEFAULT_CLIENT_ID).strip(),
        redirect_uri=val("GRAPH_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip(),
        scope=val("GRAPH_SCOPE", DEFAULT_SCOPE).strip(),
        out_dir=resolve_output_dir(val("GRAPH_OUTPUT_DIR", "out").strip() or "out"),
        use_system_proxy=_bool_env(val("USE_SYSTEM_PROXY", "1"), True),
        save_debug_html=_bool_env(val("SAVE_DEBUG_HTML", "0"), False),
    )


def make_session(use_system_proxy: bool) -> requests.Session:
    sess = requests.Session()
    sess.trust_env = bool(use_system_proxy)
    if not use_system_proxy:
        sess.proxies = {"http": None, "https": None}
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return sess


def build_authorize_url(cfg: GraphOAuthConfig) -> str:
    params = {
        "client_id": cfg.client_id,
        "response_type": "code",
        "redirect_uri": cfg.redirect_uri,
        "scope": cfg.scope,
        "response_mode": "query",
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _first_match(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def parse_login_page(html: str) -> dict[str, str]:
    flow_token = _first_match([
        r'sFTTag.*?value=\\?"([^"\\]+)',
        r'name="PPFT"[^>]*value="([^"]+)"',
    ], html)
    post_url = _first_match([r'"urlPost"\s*:\s*"([^"]+)"'], html).replace("\\u0026", "&")
    ctx = _first_match([r'"sCtx"\s*:\s*"([^"]+)"'], html)
    if not flow_token:
        raise OAuthFlowError("Microsoft login page did not contain PPFT/flow token.")
    if not post_url:
        post_url = "https://login.live.com/ppsecure/post.srf"
    return {"flow_token": flow_token, "post_url": post_url, "ctx": ctx}


def _absolute_url(base_url: str, action: str) -> str:
    action = action.replace("&amp;", "&")
    if action.startswith("http://") or action.startswith("https://"):
        return action
    base = urllib.parse.urlparse(base_url)
    if action.startswith("/"):
        return f"{base.scheme}://{base.netloc}{action}"
    prefix = base.path.rsplit("/", 1)[0]
    return f"{base.scheme}://{base.netloc}{prefix}/{action}"


def _hidden_inputs(form_html: str) -> dict[str, str]:
    return {
        name: value
        for name, value in re.findall(
            r'<input[^>]*name="([^"]*)"[^>]*value="([^"]*)"',
            form_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    }


def _save_debug_html(resp: requests.Response, label: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("_") or "page"
    path = out_dir / f"oauth_debug_{safe_label}_{int(time.time())}.html"
    path.write_text(resp.text or "", encoding="utf-8", errors="replace")
    print(f"  [debug] saved HTML: {path}")


def submit_credentials(sess: requests.Session, cfg: GraphOAuthConfig) -> requests.Response:
    auth_url = build_authorize_url(cfg)
    print("  [1] GET authorize page")
    resp = sess.get(auth_url, timeout=30, allow_redirects=True)
    login = parse_login_page(resp.text)

    print("  [2] POST Outlook credentials")
    data = {
        "login": cfg.email,
        "loginfmt": cfg.email,
        "passwd": cfg.password,
        "PPFT": login["flow_token"],
        "ctx": login["ctx"],
        "type": "11",
        "LoginOptions": "3",
        "i13": "0",
        "CookieDisclosure": "0",
        "IsFidoSupported": "0",
        "isSignupPost": "0",
        "i19": "16393",
    }
    return sess.post(login["post_url"], data=data, timeout=30, allow_redirects=False)


def submit_auto_forms(sess: requests.Session, resp: requests.Response, rounds: int = 5) -> requests.Response:
    for _ in range(rounds):
        html = resp.text or ""
        if not (("DoSubmit" in html or ("fmHF" in html and "onload" in html)) and "action=" in html):
            return resp
        action = _first_match([r'action="([^"]+)"'], html)
        if not action:
            return resp
        form_data = _hidden_inputs(html)
        action_url = _absolute_url(resp.url, action)
        print("  [3] submit Microsoft auto-form")
        resp = sess.post(action_url, data=form_data, timeout=30, allow_redirects=False)
    return resp


def _localhost_result(url: str, redirect_uri: str) -> tuple[str | None, str | None]:
    if not url:
        return None, None
    parsed = urllib.parse.urlparse(url)
    target = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname != target.hostname:
        return None, None
    params = urllib.parse.parse_qs(parsed.query)
    if params.get("code"):
        return params["code"][0], None
    if params.get("error") or params.get("error_description"):
        err = params.get("error_description", params.get("error", ["OAuth error"]))[0]
        return None, err
    return None, None


def _response_from_redirect_url(url: str) -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    resp.url = url
    resp._content = b""
    return resp


def follow_redirects_until_page(sess: requests.Session, resp: requests.Response, cfg: GraphOAuthConfig) -> requests.Response:
    while resp.status_code in (301, 302, 303, 307, 308):
        loc = resp.headers.get("Location", "")
        code, err = _localhost_result(loc, cfg.redirect_uri)
        if code or err:
            return _response_from_redirect_url(loc)
        if not loc:
            return resp
        loc = _absolute_url(resp.url, loc)
        resp = sess.get(loc, timeout=30, allow_redirects=False)
    return resp


def handle_consent_update(sess: requests.Session, resp: requests.Response) -> requests.Response | None:
    if "Consent/Update" not in resp.url and "Consent/update" not in resp.url:
        return None
    match = re.search(r"ServerData\s*=\s*(\{.*?\});", resp.text or "", re.DOTALL)
    if not match:
        raise OAuthFlowError("Consent/Update page did not expose ServerData.")
    server_data = json.loads(match.group(1))
    data = {
        "ucaction": "Yes",
        "client_id": server_data.get("sClientId", ""),
        "scope": server_data.get("sRawInputScopes", ""),
        "cscope": server_data.get("sRawInputGrantedScopes", ""),
        "canary": server_data.get("sCanary", ""),
    }
    print("  [4] accept Consent/Update")
    return sess.post(resp.url, data=data, timeout=30, allow_redirects=False)


def handle_proofs_add(sess: requests.Session, resp: requests.Response, cfg: GraphOAuthConfig) -> requests.Response | None:
    if "proofs/Add" not in resp.url and "proofs/add" not in resp.url:
        return None
    html = resp.text or ""
    if cfg.save_debug_html:
        _save_debug_html(resp, "proofs_add_before", cfg.out_dir)
    if re.search(r'"fShowSkip"\s*:\s*false', html, re.IGNORECASE):
        raise OAuthFlowError(
            "Microsoft requires adding security proof for this account "
            "(proofs/Add fShowSkip=false). Cannot extract RT with email+password only."
        )
    match = re.search(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
    if not match:
        raise OAuthFlowError("proofs/Add page did not contain a skippable form.")
    action = _absolute_url(resp.url, match.group(1))
    data = _hidden_inputs(match.group(2))
    data["action"] = "Skip"
    print("  [4] skip proofs/Add")
    result = sess.post(action, data=data, timeout=30, allow_redirects=False)
    if cfg.save_debug_html and result.status_code not in (301, 302, 303, 307, 308):
        _save_debug_html(result, "proofs_add_after", cfg.out_dir)
    return result


def submit_first_form(sess: requests.Session, resp: requests.Response) -> requests.Response | None:
    html = resp.text or ""
    match = re.search(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    action = _absolute_url(resp.url, match.group(1))
    data = _hidden_inputs(match.group(2))
    if "consent" in action.lower() or "consent" in resp.url.lower():
        data["ucaccept"] = "Yes"
    print("  [4] submit intermediate form")
    return sess.post(action, data=data, timeout=30, allow_redirects=False)


def capture_authorization_code(sess: requests.Session, resp: requests.Response, cfg: GraphOAuthConfig) -> str:
    resp = submit_auto_forms(sess, resp)
    for _ in range(15):
        resp = follow_redirects_until_page(sess, resp, cfg)
        code, err = _localhost_result(resp.url, cfg.redirect_uri)
        if code:
            print("  [5] captured authorization code")
            return code
        if err:
            raise OAuthFlowError(f"OAuth redirect returned error: {err[:160]}")

        handler_resp = handle_consent_update(sess, resp)
        if handler_resp is None:
            handler_resp = handle_proofs_add(sess, resp, cfg)
        if handler_resp is None:
            handler_resp = submit_first_form(sess, resp)
        if handler_resp is None:
            if cfg.save_debug_html:
                _save_debug_html(resp, "stuck", cfg.out_dir)
            raise OAuthFlowError(f"OAuth flow stuck at {resp.url[:140]} status={resp.status_code}")
        resp = handler_resp
    raise OAuthFlowError("OAuth flow did not produce an authorization code.")


def exchange_code(sess: requests.Session, cfg: GraphOAuthConfig, code: str) -> dict[str, Any]:
    print("  [6] exchange code for tokens")
    resp = sess.post(
        TOKEN_URL,
        data={
            "client_id": cfg.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
            "scope": cfg.scope,
        },
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise OAuthFlowError(f"Token endpoint returned non-JSON HTTP {resp.status_code}: {resp.text[:160]}") from exc
    if "access_token" not in payload:
        err = payload.get("error_description") or payload.get("error") or str(payload)[:200]
        raise OAuthFlowError(f"Token endpoint did not return access_token: {err[:200]}")
    if not payload.get("refresh_token"):
        raise OAuthFlowError("Token endpoint returned access_token but no refresh_token.")
    return payload


def extract_refresh_token(cfg: GraphOAuthConfig) -> dict[str, Any]:
    sess = make_session(cfg.use_system_proxy)
    resp = submit_credentials(sess, cfg)
    code = capture_authorization_code(sess, resp, cfg)
    token_payload = exchange_code(sess, cfg, code)
    return {
        "email": cfg.email,
        "client_id": cfg.client_id,
        "scope": cfg.scope,
        "refresh_token": token_payload["refresh_token"],
        "access_token": token_payload.get("access_token", ""),
        "expires_in": token_payload.get("expires_in"),
        "token_type": token_payload.get("token_type"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def email_filename(email: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", email.strip())
    safe = safe.strip(" ._")
    return f"{safe or 'outlook'}.txt"


def save_result(result: dict[str, Any], password: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / email_filename(result["email"])
    txt_path.write_text(
        f"{result['email']}----{password}----{result['client_id']}----{result['refresh_token']}\n",
        encoding="utf-8",
    )
    return txt_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract Microsoft Graph refresh_token from one Outlook account.")
    parser.add_argument("--env", default=str(ENV_PATH), help="Path to .env file.")
    parser.add_argument("--email", default="", help="Override OUTLOOK_EMAIL.")
    parser.add_argument("--password", default="", help="Override OUTLOOK_PASSWORD. Prefer .env instead of CLI.")
    parser.add_argument("--out-dir", default="", help="Output directory. Defaults to graph_refresh_token/out.")
    parser.add_argument("--no-proxy", action="store_true", help="Ignore HTTP_PROXY/HTTPS_PROXY for the OAuth flow.")
    parser.add_argument("--print-token", action="store_true", help="Print refresh_token to console. Off by default.")
    args = parser.parse_args(argv)

    try:
        cfg = config_from_env(Path(args.env), require_credentials=False)
        if args.email:
            cfg.email = args.email
        if args.password:
            cfg.password = args.password
        if args.out_dir:
            cfg.out_dir = resolve_output_dir(args.out_dir)
        if args.no_proxy:
            cfg.use_system_proxy = False
        if not cfg.email or not cfg.password:
            raise OAuthFlowError(
                "Missing Outlook credentials. Set OUTLOOK_EMAIL/OUTLOOK_PASSWORD in .env or environment, "
                "or pass --email and --password."
            )

        print(f"Graph OAuth refresh_token extraction for {cfg.email}")
        print(f"  client_id={cfg.client_id}")
        print(f"  scope={cfg.scope}")
        print(f"  out_dir={cfg.out_dir}")
        print(f"  proxy={'system env' if cfg.use_system_proxy else 'disabled'}")

        result = extract_refresh_token(cfg)
        txt_path = save_result(result, cfg.password, cfg.out_dir)

        print("  [OK] refresh_token extracted")
        print(f"  saved: {txt_path}")
        if args.print_token:
            print(result["refresh_token"])
        else:
            rt = result["refresh_token"]
            print(f"  refresh_token: {rt[:24]}...{rt[-12:]}")
        return 0
    except Exception as exc:
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
