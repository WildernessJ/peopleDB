"""Regression test for issue #6: route handlers are `async def` but were
calling the synchronous DavClient (httpx) inline, blocking the event loop on
every CardDAV round-trip and serializing all users' requests.

Also covers the follow-up concurrency review: offloading DAV calls to threads
exposed same-user races (sync token read/write, cache clobbers) that the
blocked event loop used to mask. Per-user locks (app.py's `lock_for`) now
serialize cache-mutating sequences per user, while different users still run
concurrently.

Repro: monkeypatch a user's cached DavClient with a stub whose `addressbooks()`
sleeps (simulating a slow CardDAV server) and tracks concurrent-call depth.
Two concurrent /refresh requests for DIFFERENT users must overlap (event loop
not blocked); two concurrent /refresh requests for the SAME user must
serialize (per-user lock)."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest

from peopledb.app import create_app
from peopledb.config import Settings

SLEEP_SECONDS = 0.08


class ConcurrencyCounter:
    """Shared, thread-safe tracker of how many calls are in-flight at once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrency = 0

    def enter(self) -> None:
        with self._lock:
            self._current += 1
            self.max_concurrency = max(self.max_concurrency, self._current)

    def exit(self) -> None:
        with self._lock:
            self._current -= 1


class SlowDavClient:
    """Stands in for a DavClient whose network round-trip is slow. Only the
    method the /refresh path actually calls (via sync_user) needs to work.
    Tracks concurrent-call depth via a shared counter so tests can assert on
    overlap deterministically instead of on wall-clock elapsed time."""

    def __init__(self, counter: ConcurrencyCounter) -> None:
        self._counter = counter

    def addressbooks(self):
        self._counter.enter()
        try:
            time.sleep(SLEEP_SECONDS)
            return []
        finally:
            self._counter.exit()

    def close(self) -> None:
        pass


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        dav_url="http://unused.invalid",
        secret_key="",
        db_path=str(tmp_path / "cache.db"),
        secure_cookies=False,
    )
    return create_app(settings)


def _login(app, username: str, client: SlowDavClient) -> str:
    creds = (username, "pw")
    app.state.dav_clients[creds] = client
    return app.state.sessions.create(*creds)


def test_concurrent_refresh_different_users_overlaps(app):
    """Two different users hitting /refresh concurrently must NOT serialize:
    the event loop must not be blocked by the synchronous DavClient call."""
    counter = ConcurrencyCounter()
    sid_a = _login(app, "alice", SlowDavClient(counter))
    sid_b = _login(app, "bob", SlowDavClient(counter))

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r1, r2 = await asyncio.gather(
                client.get("/refresh", cookies={"peopledb_session": sid_a}),
                client.get("/refresh", cookies={"peopledb_session": sid_b}),
            )
        return r1, r2

    r1, r2 = asyncio.run(run())

    assert r1.status_code == 303
    assert r2.status_code == 303
    assert counter.max_concurrency == 2, (
        f"expected different users' syncs to overlap, got max concurrency "
        f"{counter.max_concurrency}"
    )


def test_concurrent_refresh_same_user_serializes(app):
    """Two concurrent /refresh for the SAME user must serialize: the per-user
    lock (issue #6 follow-up) prevents two sync_user() runs for one user from
    racing on the sync token read/write and interleaving cache writes."""
    counter = ConcurrencyCounter()
    sid = _login(app, "alice", SlowDavClient(counter))

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", cookies={"peopledb_session": sid}
        ) as client:
            r1, r2 = await asyncio.gather(client.get("/refresh"), client.get("/refresh"))
        return r1, r2

    r1, r2 = asyncio.run(run())

    assert r1.status_code == 303
    assert r2.status_code == 303
    assert counter.max_concurrency == 1, (
        f"expected same-user syncs to serialize, got max concurrency "
        f"{counter.max_concurrency}"
    )
