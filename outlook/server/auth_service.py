"""Mailbox-backed authentication and in-memory session management."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from outlook.mailbox_graph import GraphAccount, GraphMailboxError, parse_account_file


SESSION_COOKIE = "outlook_mail_session"


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MailboxUser:
    email: str
    source_file: str
    access_all: bool = False


@dataclass
class MailboxSession:
    email: str
    source_file: str
    access_all: bool
    entry_token_hash: str
    created_at: float
    expires_at: float
    last_seen_at: float
    mailbox_entered: bool = False


class MailboxAuthService:
    def __init__(self, accounts_dir: Path, session_ttl: int = 8 * 60 * 60) -> None:
        self.accounts_dir = accounts_dir
        self.session_ttl = max(60, int(session_ttl))
        self._sessions: dict[str, MailboxSession] = {}

    def query_user(self, email: str, password: str) -> MailboxUser | None:
        account = self.find_account(email)
        if account is None or not password:
            return None
        if not hmac.compare_digest(
            account.password.encode("utf-8"),
            password.encode("utf-8"),
        ):
            return None
        return MailboxUser(email=account.email, source_file=account.source_file.name)

    def list_users(self) -> list[MailboxUser]:
        if not self.accounts_dir.is_dir():
            raise GraphMailboxError(f"Account directory not found: {self.accounts_dir}")
        users: list[MailboxUser] = []
        for path in sorted(self.accounts_dir.glob("*.txt")):
            try:
                account = parse_account_file(path)
            except (GraphMailboxError, OSError, UnicodeError):
                continue
            users.append(MailboxUser(email=account.email, source_file=account.source_file.name))
        return users

    def find_account(self, email: str) -> GraphAccount | None:
        normalized = email.strip().lower()
        if not normalized:
            return None
        if not self.accounts_dir.is_dir():
            raise GraphMailboxError(f"Account directory not found: {self.accounts_dir}")

        for path in sorted(self.accounts_dir.glob("*.txt")):
            try:
                account = parse_account_file(path)
            except (GraphMailboxError, OSError, UnicodeError):
                continue
            if account.email.lower() == normalized:
                return account
        return None

    def login(self, email: str, password: str) -> tuple[str, str, MailboxUser] | None:
        user = self.query_user(email, password)
        if user is None:
            return None

        return self._create_session(user)

    def login_local_whitelist(self) -> tuple[str, str, MailboxUser]:
        return self._create_session(
            MailboxUser(email="127.0.0.1", source_file="", access_all=True)
        )

    def _create_session(self, user: MailboxUser) -> tuple[str, str, MailboxUser]:

        self.delete_expired_sessions()
        now = time.time()
        token = secrets.token_urlsafe(32)
        entry_token = secrets.token_urlsafe(24)
        self._sessions[hash_token(token)] = MailboxSession(
            email=user.email,
            source_file=user.source_file,
            access_all=user.access_all,
            entry_token_hash=hash_token(entry_token),
            created_at=now,
            expires_at=now + self.session_ttl,
            last_seen_at=now,
        )
        return token, entry_token, user

    def user_from_token(self, token: str) -> MailboxUser | None:
        session = self._session_from_token(token)
        if session is None:
            return None
        session.last_seen_at = time.time()
        return MailboxUser(
            email=session.email,
            source_file=session.source_file,
            access_all=session.access_all,
        )

    def enter_mailbox(self, token: str, entry_token: str) -> MailboxUser | None:
        session = self._session_from_token(token)
        if session is None:
            return None
        if not session.mailbox_entered:
            candidate = hash_token(entry_token.strip()) if entry_token else ""
            if not candidate or not hmac.compare_digest(candidate, session.entry_token_hash):
                return None
            session.mailbox_entered = True
        session.last_seen_at = time.time()
        return MailboxUser(
            email=session.email,
            source_file=session.source_file,
            access_all=session.access_all,
        )

    def logout(self, token: str) -> None:
        if token:
            self._sessions.pop(hash_token(token), None)

    def renew_entry_token(self, token: str) -> str | None:
        session = self._session_from_token(token)
        if session is None:
            return None
        entry_token = secrets.token_urlsafe(24)
        session.entry_token_hash = hash_token(entry_token)
        session.last_seen_at = time.time()
        return entry_token

    def active_session_count(self, email: str) -> int:
        self.delete_expired_sessions()
        normalized = email.strip().lower()
        return sum(1 for session in self._sessions.values() if session.email.lower() == normalized)

    def delete_expired_sessions(self) -> None:
        now = time.time()
        expired = [key for key, session in self._sessions.items() if session.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)

    def _session_from_token(self, token: str) -> MailboxSession | None:
        if not token:
            return None
        self.delete_expired_sessions()
        return self._sessions.get(hash_token(token))
