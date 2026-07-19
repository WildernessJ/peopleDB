"""Cache/sync store: SQLite mirror of the CardDAV addressbooks.

Keyed per user per addressbook. Holds the raw vCard blob (source of truth for
edits), extracted display columns, an FTS5 search index, and the server sync
token. The cache is disposable; the CardDAV server stays canonical."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from peopledb.vcard import Contact, parse_vcard

# Column definition for the contacts_fts FTS5 index, kept in ONE place so the
# CREATE in _SCHEMA and the rebuild in _migrate can never drift apart -- a
# mismatch would silently index the wrong fields. Bump _SCHEMA_VERSION below
# whenever this list changes so existing caches rebuild.
_FTS_COLUMNS = "user UNINDEXED, href UNINDEXED, name, org, emails, phones, note, address, url"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS contacts (
    user TEXT NOT NULL,
    addressbook TEXT NOT NULL,
    href TEXT NOT NULL,
    etag TEXT NOT NULL,
    raw TEXT NOT NULL,
    uid TEXT NOT NULL DEFAULT '',
    is_group INTEGER NOT NULL DEFAULT 0,
    broken INTEGER NOT NULL DEFAULT 0,
    sort_name TEXT NOT NULL DEFAULT '',
    bday TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user, href)
);
CREATE TABLE IF NOT EXISTS sync_tokens (
    user TEXT NOT NULL,
    addressbook TEXT NOT NULL,
    token TEXT NOT NULL,
    PRIMARY KEY (user, addressbook)
);
CREATE TABLE IF NOT EXISTS feed_tokens (
    user TEXT NOT NULL PRIMARY KEY,
    token TEXT NOT NULL UNIQUE
);
CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
    {_FTS_COLUMNS}
);
"""

# Bumped whenever contacts_fts's column set changes. FTS5 has no ALTER ADD
# COLUMN, and the cache is disposable, so a version bump means "drop and
# rebuild contacts_fts from contacts.raw on next boot" rather than a real
# migration. See ContactStore.__init__.
_SCHEMA_VERSION = 1


@dataclass
class StoredContact:
    href: str
    addressbook: str
    etag: str
    raw: str
    contact: Contact
    broken: bool = False


class ContactStore:
    def __init__(self, path: str | Path) -> None:
        # SQLite connections may only be used from the thread that created
        # them (check_same_thread=False would let us share one connection,
        # but that forced a global RLock serializing every user's reads and
        # writes). Instead: one connection per thread (threading.local),
        # created lazily, with WAL mode so readers don't block writers and a
        # busy_timeout so concurrent writers wait instead of raising
        # SQLITE_BUSY. The schema only needs creating once, so it runs here
        # on an explicit bootstrap connection rather than per-thread.
        self._path = str(path)
        self._local = threading.local()
        bootstrap = self._connect()
        bootstrap.executescript(_SCHEMA)
        bootstrap.commit()
        # Keep the bootstrap connection as this thread's cached one rather
        # than leaking it and lazily opening a second on first use.
        self._local.conn = bootstrap
        self._migrate(bootstrap)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Rebuild contacts_fts exactly once when its column set is stale.

        `CREATE ... IF NOT EXISTS` in _SCHEMA leaves an old-shaped table alone
        on an existing DB, so user_version is the only signal that a rebuild
        is needed. Runs at most once per version bump: an existing cache with
        a stale table gets re-populated from contacts.raw; a fresh DB (empty
        contacts, table already current from _SCHEMA) does a trivial no-op
        rebuild and is stamped so it never runs again."""
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= _SCHEMA_VERSION:
            return
        with conn:
            conn.execute("DROP TABLE IF EXISTS contacts_fts")
            conn.execute(f"CREATE VIRTUAL TABLE contacts_fts USING fts5({_FTS_COLUMNS})")
            for user, href, raw, broken, is_group in conn.execute(
                "SELECT user, href, raw, broken, is_group FROM contacts"
            ):
                if broken or is_group:
                    continue
                try:
                    contact = parse_vcard(raw)
                except Exception:
                    continue
                conn.execute(
                    "INSERT INTO contacts_fts (user, href, name, org, emails, phones, note,"
                    " address, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._fts_row(user, href, contact),
                )
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    @staticmethod
    def _fts_row(user: str, href: str, contact: Contact) -> tuple:
        """Build the positional values for one contacts_fts insert. Shared by
        upsert and the migration rebuild so the two never drift apart."""
        return (
            user,
            href,
            f"{contact.formatted_name} {contact.given} {contact.family}",
            contact.org,
            " ".join(v for _, v in contact.emails),
            " ".join(v for _, v in contact.phones),
            contact.note,
            " ".join(parts.formatted for _, parts in contact.addresses),
            " ".join(v for _, v in contact.urls),
        )

    def close(self) -> None:
        """Checkpoint the WAL and close the calling thread's connection, so a
        clean shutdown leaves no stale -wal file. Checkpointing is database-
        scoped, so this flushes other threads' writes too; their connections
        themselves die with their threads (freed on GC). Opens a short-lived
        connection when the calling thread has none (e.g. a lifespan hook on
        a different thread than the one that served requests)."""
        conn = getattr(self._local, "conn", None) or self._connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
            self._local.conn = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def upsert(self, user: str, addressbook: str, href: str, etag: str, raw: str) -> None:
        try:
            contact = parse_vcard(raw)
            broken = False
        except Exception:
            contact = Contact()
            broken = True
        sort_name = (
            f"{contact.family} {contact.given}".strip() or contact.formatted_name
        ).lower()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO contacts"
                " (user, addressbook, href, etag, raw, uid, is_group, broken, sort_name, bday)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user, addressbook, href, etag, raw, contact.uid,
                 int(contact.is_group), int(broken), sort_name, contact.bday),
            )
            self._conn.execute(
                "DELETE FROM contacts_fts WHERE user = ? AND href = ?", (user, href)
            )
            if not broken and not contact.is_group:
                self._conn.execute(
                    "INSERT INTO contacts_fts (user, href, name, org, emails, phones, note,"
                    " address, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._fts_row(user, href, contact),
                )

    def delete(self, user: str, href: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM contacts WHERE user = ? AND href = ?", (user, href)
            )
            self._conn.execute(
                "DELETE FROM contacts_fts WHERE user = ? AND href = ?", (user, href)
            )

    def get(self, user: str, href: str) -> StoredContact | None:
        row = self._conn.execute(
            "SELECT href, addressbook, etag, raw, broken FROM contacts"
            " WHERE user = ? AND href = ?",
            (user, href),
        ).fetchone()
        return self._to_record(row) if row else None

    def list_contacts(self, user: str) -> list[StoredContact]:
        rows = self._conn.execute(
            "SELECT href, addressbook, etag, raw, broken FROM contacts"
            " WHERE user = ? AND is_group = 0 AND broken = 0 ORDER BY sort_name",
            (user,),
        ).fetchall()
        return [self._to_record(r) for r in rows]

    def _to_record(self, row: tuple) -> StoredContact:
        href, addressbook, etag, raw, broken = row
        contact = Contact() if broken else parse_vcard(raw)
        return StoredContact(
            href=href, addressbook=addressbook, etag=etag, raw=raw,
            contact=contact, broken=bool(broken),
        )

    def get_by_uid(self, user: str, uid: str) -> StoredContact | None:
        # The table's primary key is (user, href), not uid -- nothing enforces
        # one row per (user, uid). If a bad import or unresolved sync conflict
        # ever produces two rows sharing a uid, fetchone() with no ORDER BY is
        # an arbitrary pick. ORDER BY href makes the pick deterministic.
        row = self._conn.execute(
            "SELECT href, addressbook, etag, raw, broken FROM contacts"
            " WHERE user = ? AND uid = ? ORDER BY href LIMIT 1",
            (user, uid),
        ).fetchone()
        return self._to_record(row) if row else None

    def list_groups(self, user: str) -> list[StoredContact]:
        rows = self._conn.execute(
            "SELECT href, addressbook, etag, raw, broken FROM contacts"
            " WHERE user = ? AND is_group = 1 AND broken = 0 ORDER BY sort_name",
            (user,),
        ).fetchall()
        return [self._to_record(r) for r in rows]

    def list_broken(self, user: str) -> list[StoredContact]:
        rows = self._conn.execute(
            "SELECT href, addressbook, etag, raw, broken FROM contacts"
            " WHERE user = ? AND broken = 1 ORDER BY href",
            (user,),
        ).fetchall()
        return [self._to_record(r) for r in rows]

    def contacts_with_bday(self, user: str) -> list[StoredContact]:
        rows = self._conn.execute(
            "SELECT href, addressbook, etag, raw, broken FROM contacts"
            " WHERE user = ? AND is_group = 0 AND broken = 0 AND bday != ''"
            " ORDER BY sort_name",
            (user,),
        ).fetchall()
        return [self._to_record(r) for r in rows]

    def search(self, user: str, query: str) -> list[StoredContact]:
        # Quote each term and add a prefix wildcard so "sar" matches "Sarah"
        # and "sarah@acme.example" isn't parsed as FTS syntax.
        terms = [t.replace('"', '""') for t in query.split()]
        if not terms:
            return []
        match = " ".join(f'"{t}"*' for t in terms)
        rows = self._conn.execute(
            "SELECT c.href, c.addressbook, c.etag, c.raw, c.broken"
            " FROM contacts_fts f JOIN contacts c ON c.user = f.user AND c.href = f.href"
            " WHERE f.user = ? AND contacts_fts MATCH ? ORDER BY c.sort_name",
            (user, match),
        ).fetchall()
        return [self._to_record(r) for r in rows]

    def ensure_feed_token(self, user: str) -> str:
        # Check-then-insert across two per-thread connections is a TOCTOU
        # race if done as SELECT-then-INSERT: two threads could both see no
        # row and both try to INSERT. Use INSERT OR IGNORE (first writer
        # wins on the `user` primary key, the loser's insert is a no-op)
        # then always re-SELECT so every caller returns the same token.
        # Retry loop: OR IGNORE also swallows a (vanishingly unlikely)
        # UNIQUE(token) collision with another user's token, in which case no
        # row lands for this user -- generate a new candidate and try again.
        row = None
        while row is None:
            candidate = secrets.token_urlsafe(24)
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO feed_tokens (user, token) VALUES (?, ?)",
                    (user, candidate),
                )
            row = self._conn.execute(
                "SELECT token FROM feed_tokens WHERE user = ?", (user,)
            ).fetchone()
        return row[0]

    def user_for_feed_token(self, token: str) -> str | None:
        row = self._conn.execute(
            "SELECT user FROM feed_tokens WHERE token = ?", (token,)
        ).fetchone()
        return row[0] if row else None

    def get_sync_token(self, user: str, addressbook: str) -> str | None:
        row = self._conn.execute(
            "SELECT token FROM sync_tokens WHERE user = ? AND addressbook = ?",
            (user, addressbook),
        ).fetchone()
        return row[0] if row else None

    def set_sync_token(self, user: str, addressbook: str, token: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO sync_tokens (user, addressbook, token) VALUES (?, ?, ?)",
                (user, addressbook, token),
            )
