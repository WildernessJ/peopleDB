"""Tests for the session store seam: Fernet-encrypted server-side credentials."""

import pytest
from cryptography.fernet import Fernet

from peopledb.auth import SessionStore


def make_store():
    return SessionStore(fernet_key=Fernet.generate_key())


def test_session_roundtrip():
    store = make_store()
    sid = store.create("jason", "hunter2")
    assert store.get(sid) == ("jason", "hunter2")


def test_unknown_or_dropped_session_returns_none():
    store = make_store()
    assert store.get("no-such-sid") is None
    sid = store.create("jason", "hunter2")
    store.drop(sid)
    assert store.get(sid) is None


def test_credentials_encrypted_at_rest():
    store = make_store()
    store.create("jason", "hunter2")
    for blob, _last_seen in store._sessions.values():
        assert b"hunter2" not in blob
        assert b"jason" not in blob


class FakeClock:
    """Manually-advanced clock standing in for time.monotonic in tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_session_valid_within_idle_window():
    clock = FakeClock()
    store = SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=100, now=clock)
    sid = store.create("jason", "hunter2")
    clock.advance(50)
    assert store.get(sid) == ("jason", "hunter2")


def test_session_expires_after_idle_window():
    clock = FakeClock()
    store = SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=100, now=clock)
    sid = store.create("jason", "hunter2")
    clock.advance(101)
    assert store.get(sid) is None
    # Expired session is actually purged, not just hidden.
    assert sid not in store._sessions


def test_activity_slides_the_idle_window():
    clock = FakeClock()
    store = SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=100, now=clock)
    sid = store.create("jason", "hunter2")
    # Touch the session just before it would expire, several times.
    clock.advance(90)
    assert store.get(sid) == ("jason", "hunter2")
    clock.advance(90)
    assert store.get(sid) == ("jason", "hunter2")
    clock.advance(90)
    assert store.get(sid) == ("jason", "hunter2")


def test_credentials_purges_expired_sessions():
    clock = FakeClock()
    store = SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=100, now=clock)
    live_sid = store.create("jason", "hunter2")
    dead_sid = store.create("alice", "swordfish")
    clock.advance(50)
    # Touch only the live session so it survives while the other goes idle.
    store.get(live_sid)
    clock.advance(60)
    creds = store.credentials()
    assert creds == [("jason", "hunter2")]
    assert dead_sid not in store._sessions
    assert live_sid in store._sessions


def test_idle_zero_never_expires():
    clock = FakeClock()
    store = SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=0, now=clock)
    sid = store.create("jason", "hunter2")
    clock.advance(10_000_000)
    assert store.get(sid) == ("jason", "hunter2")


def test_background_polling_does_not_reset_idle_window():
    """Regression: the background refresher (app.py lifespan) calls
    credentials() every sync_interval_seconds, which internally calls get()
    on every session. If that internal lookup refreshed last-seen the same
    as real user activity, no session could ever accumulate idle time and
    the whole feature would be inert in production — server-internal polling
    must not itself count as activity."""
    clock = FakeClock()
    store = SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=100, now=clock)
    sid = store.create("jason", "hunter2")
    # Simulate the refresher polling every 30s (< idle_seconds) with no real
    # user request in between, past the idle window's total.
    for _ in range(5):
        clock.advance(30)
        store.credentials()
    assert clock.t > 100
    assert store.get(sid) is None
    assert sid not in store._sessions


def test_negative_idle_seconds_rejected():
    with pytest.raises(ValueError):
        SessionStore(fernet_key=Fernet.generate_key(), idle_seconds=-1)
