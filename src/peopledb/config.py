"""App settings from environment. Never hardcode the CardDAV URL or secrets;
see README for the expected variable shapes."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    dav_url: str
    secret_key: str = ""  # Fernet key; empty -> ephemeral key generated at startup
    db_path: str = "peopledb-cache.db"
    sync_interval_seconds: int = 300
    secure_cookies: bool = True  # set False only for local HTTP dev/tests
    # Which addressbook new contacts/groups are written to, matched against the
    # displayname or the collection path segment. Empty -> first discovered.
    write_addressbook: str = "default"
    # Sliding idle timeout for logged-in sessions (issue #3): a session not
    # used for this long is dropped on next get(). 0 disables expiry (old
    # behavior: session lives until logout or restart).
    session_idle_seconds: int = 7 * 24 * 3600

    @classmethod
    def from_env(cls) -> "Settings":
        dav_url = os.environ.get("PEOPLEDB_DAV_URL", "")
        if not dav_url:
            raise RuntimeError("PEOPLEDB_DAV_URL is required (base URL of the CardDAV server)")
        return cls(
            dav_url=dav_url,
            secret_key=os.environ.get("PEOPLEDB_SECRET_KEY", ""),
            db_path=os.environ.get("PEOPLEDB_DB_PATH", "peopledb-cache.db"),
            sync_interval_seconds=int(os.environ.get("PEOPLEDB_SYNC_INTERVAL", "300")),
            secure_cookies=os.environ.get("PEOPLEDB_SECURE_COOKIES", "1") != "0",
            write_addressbook=os.environ.get("PEOPLEDB_WRITE_ADDRESSBOOK", "default"),
            session_idle_seconds=int(
                os.environ.get("PEOPLEDB_SESSION_IDLE_SECONDS", str(7 * 24 * 3600))
            ),
        )
