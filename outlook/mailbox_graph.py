# -*- coding: utf-8 -*-
"""
Graph mailbox metadata exporter.

Reads token files produced by oauth_graph.py and exports:
  - outlook/db/<email>.csv: mailbox folder list
  - outlook/out/<email>+<folder>.csv: message title metadata for each folder

This module intentionally does not request message body fields.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DEFAULT_ACCOUNT_DIR = PROJECT_DIR / "graph_refresh_token" / "out"
DEFAULT_DB_DIR = BASE_DIR / "db"
DEFAULT_OUT_DIR = BASE_DIR / "out"
DEFAULT_AT_CSV = DEFAULT_DB_DIR / "at.csv"
DEFAULT_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphMailboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphAccount:
    email: str
    password: str
    client_id: str
    refresh_token: str
    source_file: Path


@dataclass(frozen=True)
class MailFolder:
    id: str
    display_name: str
    parent_folder_id: str = ""
    total_item_count: int | None = None
    unread_item_count: int | None = None
    child_folder_count: int | None = None
    level: int = 0
    path: str = ""


def _client_id_like(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value))


def safe_filename(value: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value.strip())
    safe = safe.strip(" ._")
    return safe or "unknown"


def _b64url_decode_json(segment: str) -> dict[str, Any]:
    if not segment:
        return {}
    padded = segment + "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "replace")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def decode_jwt_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}, {}
    return _b64url_decode_json(parts[0]), _b64url_decode_json(parts[1])


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _epoch_to_utc(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_account_file(path: Path) -> GraphAccount:
    line = path.read_text(encoding="utf-8").strip()
    parts = line.split("----", 3)
    if len(parts) != 4:
        raise GraphMailboxError(f"{path.name}: expected 4 columns, got {len(parts)}")

    email, password, col3, col4 = parts
    if _client_id_like(col3):
        client_id, refresh_token = col3, col4
    elif _client_id_like(col4):
        refresh_token, client_id = col3, col4
    else:
        client_id, refresh_token = DEFAULT_CLIENT_ID, col4
    return GraphAccount(
        email=email.strip(),
        password=password,
        client_id=client_id.strip() or DEFAULT_CLIENT_ID,
        refresh_token=refresh_token.strip(),
        source_file=path,
    )


class GraphMailboxClient:
    def __init__(
        self,
        account_dir: Path = DEFAULT_ACCOUNT_DIR,
        db_dir: Path = DEFAULT_DB_DIR,
        out_dir: Path = DEFAULT_OUT_DIR,
        timeout: int = 30,
        use_system_proxy: bool = False,
    ) -> None:
        self.account_dir = account_dir
        self.db_dir = db_dir
        self.out_dir = out_dir
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = bool(use_system_proxy)
        if not use_system_proxy:
            self.session.proxies = {"http": None, "https": None}

    def load_accounts(self, email_filter: str = "") -> list[GraphAccount]:
        if not self.account_dir.is_dir():
            raise GraphMailboxError(f"Account directory not found: {self.account_dir}")
        accounts: list[GraphAccount] = []
        for path in sorted(self.account_dir.glob("*.txt")):
            account = parse_account_file(path)
            if email_filter and account.email.lower() != email_filter.lower():
                continue
            accounts.append(account)
        if not accounts:
            raise GraphMailboxError(f"No account token files found in {self.account_dir}")
        return accounts

    def refresh_access_token(self, account: GraphAccount) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.post(
                    TOKEN_URL,
                    data={
                        "client_id": account.client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": account.refresh_token,
                        "scope": "https://graph.microsoft.com/Mail.Read",
                    },
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    raise GraphMailboxError(
                        f"{account.email}: token refresh failed HTTP {resp.status_code}: {resp.text[:180]}"
                    )
                payload = resp.json()
                if not payload.get("access_token"):
                    raise GraphMailboxError(f"{account.email}: token endpoint returned no access_token")
                return payload
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_err = exc
                if attempt < 2:
                    time.sleep(1.5)
                    continue
        raise GraphMailboxError(f"{account.email}: token refresh connection failed: {str(last_err)[:160]}")

    def get_access_token(self, account: GraphAccount) -> str:
        return self.refresh_access_token(account)["access_token"]

    def _graph_get(self, access_token: str, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise GraphMailboxError(f"Graph GET failed HTTP {resp.status_code}: {resp.text[:180]}")
        return resp.json()

    def _paged_values(
        self,
        access_token: str,
        url: str,
        params: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        next_url: str | None = url
        next_params = params
        while next_url:
            payload = self._graph_get(access_token, next_url, next_params)
            batch = payload.get("value", [])
            for item in batch:
                values.append(item)
                if limit is not None and len(values) >= limit:
                    return values
            next_url = payload.get("@odata.nextLink")
            next_params = None
        return values

    def list_folders(self, access_token: str, recursive: bool = True) -> list[MailFolder]:
        fields = "id,displayName,parentFolderId,totalItemCount,unreadItemCount,childFolderCount"
        root_url = f"{GRAPH_BASE}/me/mailFolders"
        root_items = self._paged_values(access_token, root_url, {"$top": "100", "$select": fields})
        folders: list[MailFolder] = []

        def add_items(items: Iterable[dict[str, Any]], level: int, parent_path: str) -> None:
            for item in items:
                name = item.get("displayName", "")
                folder_path = f"{parent_path}/{name}" if parent_path else name
                folder = MailFolder(
                    id=item.get("id", ""),
                    display_name=name,
                    parent_folder_id=item.get("parentFolderId", "") or "",
                    total_item_count=item.get("totalItemCount"),
                    unread_item_count=item.get("unreadItemCount"),
                    child_folder_count=item.get("childFolderCount"),
                    level=level,
                    path=folder_path,
                )
                folders.append(folder)
                if recursive and folder.id and (folder.child_folder_count or 0) > 0:
                    encoded_id = urllib.parse.quote(folder.id, safe="")
                    child_url = f"{GRAPH_BASE}/me/mailFolders/{encoded_id}/childFolders"
                    child_items = self._paged_values(access_token, child_url, {"$top": "100", "$select": fields})
                    add_items(child_items, level + 1, folder_path)

        add_items(root_items, 0, "")
        return folders

    def list_message_titles(self, access_token: str, folder_id: str, top: int = 50) -> list[dict[str, Any]]:
        encoded_id = urllib.parse.quote(folder_id, safe="")
        url = f"{GRAPH_BASE}/me/mailFolders/{encoded_id}/messages"
        limit = None if top <= 0 else top
        page_size = "50" if top <= 0 else str(min(top, 50))
        params = {
            "$top": page_size,
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,subject,from,sender,receivedDateTime,sentDateTime,isRead,"
                "hasAttachments,importance,internetMessageId,conversationId,webLink,categories"
            ),
        }
        return self._paged_values(access_token, url, params, limit=limit)

    def write_folders_csv(self, account: GraphAccount, folders: list[MailFolder]) -> Path:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        path = self.db_dir / f"{safe_filename(account.email)}.csv"
        fieldnames = [
            "email",
            "folder_path",
            "display_name",
            "folder_id",
            "parent_folder_id",
            "total_item_count",
            "unread_item_count",
            "child_folder_count",
            "level",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for folder in folders:
                writer.writerow({
                    "email": account.email,
                    "folder_path": folder.path,
                    "display_name": folder.display_name,
                    "folder_id": folder.id,
                    "parent_folder_id": folder.parent_folder_id,
                    "total_item_count": folder.total_item_count,
                    "unread_item_count": folder.unread_item_count,
                    "child_folder_count": folder.child_folder_count,
                    "level": folder.level,
                })
        return path

    def build_access_token_row(self, account: GraphAccount, token_payload: dict[str, Any]) -> dict[str, str]:
        access_token = str(token_payload.get("access_token") or "")
        header, payload = decode_jwt_unverified(access_token)
        now = int(time.time())
        parts = access_token.split(".") if access_token else []
        is_jwt = bool(len(parts) >= 3 and header and payload)
        refreshed_at = datetime.now(tz=timezone.utc)
        expires_in = token_payload.get("expires_in")
        response_expires_at = ""
        try:
            response_expires_at = datetime.fromtimestamp(
                int(refreshed_at.timestamp()) + int(expires_in),
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError):
            pass

        row: dict[str, str] = {
            "email": account.email,
            "source_file": str(account.source_file),
            "client_id": account.client_id,
            "token_type": _csv_value(token_payload.get("token_type")),
            "scope": _csv_value(token_payload.get("scope")),
            "access_token": access_token,
            "token_length": str(len(access_token)),
            "is_jwt": "true" if is_jwt else "false",
            "jwt_part_count": str(len(parts)),
            "jwt_parse_status": "decoded" if is_jwt else "not_jwt_or_opaque",
            "refreshed_at_utc": refreshed_at.isoformat().replace("+00:00", "Z"),
            "expires_in": _csv_value(expires_in),
            "ext_expires_in": _csv_value(token_payload.get("ext_expires_in")),
            "response_expires_at_utc": response_expires_at,
            "issued_at_utc": _epoch_to_utc(payload.get("iat")),
            "not_before_utc": _epoch_to_utc(payload.get("nbf")),
            "expires_at_utc": _epoch_to_utc(payload.get("exp")),
            "expires_in_seconds": "",
        }
        try:
            row["expires_in_seconds"] = str(max(0, int(payload.get("exp")) - now))
        except (TypeError, ValueError):
            pass

        for key, value in sorted(header.items()):
            row[f"jwt_header_{key}"] = _csv_value(value)
        for key, value in sorted(payload.items()):
            row[f"jwt_claim_{key}"] = _csv_value(value)
        return row

    def write_access_tokens_csv(
        self,
        accounts: list[GraphAccount],
        at_csv: Path = DEFAULT_AT_CSV,
    ) -> tuple[Path, int]:
        at_csv.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, str]] = []
        for account in accounts:
            token_payload = self.refresh_access_token(account)
            rows.append(self.build_access_token_row(account, token_payload))

        base_fields = [
            "email",
            "source_file",
            "client_id",
            "token_type",
            "scope",
            "access_token",
            "token_length",
            "is_jwt",
            "jwt_part_count",
            "jwt_parse_status",
            "refreshed_at_utc",
            "expires_in",
            "ext_expires_in",
            "response_expires_at_utc",
            "issued_at_utc",
            "not_before_utc",
            "expires_at_utc",
            "expires_in_seconds",
        ]
        dynamic_fields = sorted({key for row in rows for key in row if key not in base_fields})
        with at_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=base_fields + dynamic_fields)
            writer.writeheader()
            writer.writerows(rows)
        return at_csv, len(rows)

    def write_titles_csv(
        self,
        account: GraphAccount,
        folder: MailFolder,
        messages: list[dict[str, Any]],
    ) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{safe_filename(account.email)}+{safe_filename(folder.display_name)}.csv"
        fieldnames = [
            "email",
            "folder_path",
            "folder_name",
            "message_id",
            "subject",
            "from_name",
            "from_address",
            "sender_name",
            "sender_address",
            "received_datetime",
            "sent_datetime",
            "is_read",
            "has_attachments",
            "importance",
            "internet_message_id",
            "conversation_id",
            "web_link",
            "categories",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for message in messages:
                from_addr = (message.get("from", {}).get("emailAddress", {}) or {})
                sender_addr = (message.get("sender", {}).get("emailAddress", {}) or {})
                writer.writerow({
                    "email": account.email,
                    "folder_path": folder.path,
                    "folder_name": folder.display_name,
                    "message_id": message.get("id", ""),
                    "subject": message.get("subject", ""),
                    "from_name": from_addr.get("name", ""),
                    "from_address": from_addr.get("address", ""),
                    "sender_name": sender_addr.get("name", ""),
                    "sender_address": sender_addr.get("address", ""),
                    "received_datetime": message.get("receivedDateTime", ""),
                    "sent_datetime": message.get("sentDateTime", ""),
                    "is_read": message.get("isRead", ""),
                    "has_attachments": message.get("hasAttachments", ""),
                    "importance": message.get("importance", ""),
                    "internet_message_id": message.get("internetMessageId", ""),
                    "conversation_id": message.get("conversationId", ""),
                    "web_link": message.get("webLink", ""),
                    "categories": "|".join(message.get("categories", []) or []),
                })
        return path

    def export_account(
        self,
        account: GraphAccount,
        top: int = 50,
        folder_filters: list[str] | None = None,
        folders_only: bool = False,
        recursive: bool = True,
    ) -> tuple[Path, list[Path]]:
        access_token = self.get_access_token(account)
        folders = self.list_folders(access_token, recursive=recursive)
        folder_csv = self.write_folders_csv(account, folders)

        title_csvs: list[Path] = []
        if folders_only:
            return folder_csv, title_csvs

        wanted = {value.lower() for value in (folder_filters or [])}
        for folder in folders:
            if wanted and folder.display_name.lower() not in wanted and folder.id.lower() not in wanted:
                continue
            messages = self.list_message_titles(access_token, folder.id, top=top)
            title_csvs.append(self.write_titles_csv(account, folder, messages))
        return folder_csv, title_csvs


def resolve_path(value: str, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Export Graph mailbox folders and message title metadata.")
    parser.add_argument(
        "--accounts-dir",
        default="",
        help="Directory containing <email>.txt token files. Default: graph_refresh_token/out.",
    )
    parser.add_argument("--db-dir", default="", help="Folder-list CSV output directory. Default: outlook/db.")
    parser.add_argument("--out-dir", default="", help="Message-title CSV output directory. Default: outlook/out.")
    parser.add_argument("--email", default="", help="Only process one email.")
    parser.add_argument("--folder", action="append", default=[], help="Only export this folder display name or id.")
    parser.add_argument("--top", type=int, default=50, help="Messages per folder. Use 0 to fetch all pages.")
    parser.add_argument("--folders-only", action="store_true", help="Only export folder list CSV files.")
    parser.add_argument("--export-at", action="store_true", help="Write Graph access tokens and decoded JWT claims to outlook/db/at.csv.")
    parser.add_argument("--at-csv", default="", help="Access-token CSV path. Default: outlook/db/at.csv.")
    parser.add_argument("--no-recursive", action="store_true", help="Do not export child folders.")
    parser.add_argument("--use-system-proxy", action="store_true", help="Use HTTP_PROXY/HTTPS_PROXY for Graph requests.")
    args = parser.parse_args(argv)

    client = GraphMailboxClient(
        account_dir=resolve_path(args.accounts_dir, DEFAULT_ACCOUNT_DIR),
        db_dir=resolve_path(args.db_dir, DEFAULT_DB_DIR),
        out_dir=resolve_path(args.out_dir, DEFAULT_OUT_DIR),
        use_system_proxy=args.use_system_proxy,
    )

    try:
        accounts = client.load_accounts(args.email)
        if args.export_at:
            at_path = resolve_path(args.at_csv, DEFAULT_AT_CSV)
            written_path, count = client.write_access_tokens_csv(accounts, at_path)
            print(f"access tokens: {written_path} rows={count}")
            return 0
        for account in accounts:
            print(f"{account.email}: exporting folders")
            folder_csv, title_csvs = client.export_account(
                account,
                top=args.top,
                folder_filters=args.folder,
                folders_only=args.folders_only,
                recursive=not args.no_recursive,
            )
            print(f"  folders: {folder_csv}")
            for path in title_csvs:
                print(f"  titles: {path}")
        return 0
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
