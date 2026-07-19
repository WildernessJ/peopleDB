"""Server-side sessions holding the user's CardDAV credentials,
Fernet-encrypted at rest (key from env). In-memory by design: restarting the
app just means logging in again; nothing credential-shaped touches disk.

Sessions carry a sliding idle timeout (issue #3): each `get()` stamps
last-seen time and expires (drops) sessions that have gone idle too long,
so a stolen/forgotten cookie doesn't hold a live CardDAV password forever."""

from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Callable

from cryptography.fernet import Fernet


class SessionStore:
    def __init__(
        self,
        fernet_key: bytes | str,
        idle_seconds: float = 7 * 24 * 3600,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if idle_seconds < 0:
            raise ValueError("idle_seconds must be >= 0 (0 disables expiry)")
        self._fernet = Fernet(fernet_key)
        self._idle_seconds = idle_seconds
        self._now = now
        self._lock = threading.Lock()
        # sid -> (encrypted payload, last-seen timestamp per self._now)
        self._sessions: dict[str, tuple[bytes, float]] = {}

    def create(self, username: str, password: str) -> str:
        sid = secrets.token_urlsafe(32)
        payload = json.dumps([username, password]).encode()
        blob = self._fernet.encrypt(payload)
        with self._lock:
            self._sessions[sid] = (blob, self._now())
        return sid

    def get(self, sid: str, refresh: bool = True) -> tuple[str, str] | None:
        """Look up a session's credentials.

        `refresh` controls whether this lookup counts as user activity that
        slides the idle window. Real user requests should refresh (default);
        internal polling (see `credentials()`) must not, or a session would
        never accumulate idle time regardless of the user being away."""
        with self._lock:
            entry = self._sessions.get(sid)
            if entry is None:
                return None
            blob, last_seen = entry
            if self._idle_seconds and self._now() - last_seen > self._idle_seconds:
                del self._sessions[sid]
                return None
            if refresh:
                self._sessions[sid] = (blob, self._now())
        username, password = json.loads(self._fernet.decrypt(blob))
        return username, password

    def drop(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def credentials(self) -> list[tuple[str, str]]:
        """Unique (username, password) pairs across active sessions.

        Expired sessions are purged as a side effect (via get(refresh=False))
        but this internal poll must NOT itself count as activity — otherwise
        the background refresher's own periodic call would slide every
        session's idle window forever and expiry would never trigger."""
        with self._lock:
            sids = list(self._sessions)
        seen: dict[tuple[str, str], None] = {}
        for sid in sids:
            creds = self.get(sid, refresh=False)
            if creds is not None:
                seen[creds] = None
        return list(seen)
