"""Concurrency behavior for ContactStore's connection-per-thread + WAL design
(issue #5). Before this, one shared sqlite3 connection guarded by a single
threading.RLock serialized ALL users' reads and writes. These tests exercise
multiple threads hammering the store at once and assert it comes out correct
(no exceptions, no lost writes) rather than reproducing a specific bug."""

import threading
import time
from pathlib import Path

import pytest

from peopledb.store import ContactStore

CARD_TEMPLATE = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:{uid}\r\n"
    "FN:{name}\r\n"
    "N:{name};;;;\r\n"
    "EMAIL;TYPE=WORK:{uid}@example.com\r\n"
    "END:VCARD\r\n"
)


@pytest.fixture
def store(tmp_path):
    return ContactStore(tmp_path / "cache.db")


def test_journal_mode_is_wal(store):
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_concurrent_upserts_and_reads_across_users(store):
    """N threads, each owning one user, interleave upserts and reads. Under
    the old design this serialized on one global RLock; here it must simply
    complete without error and every row must land."""
    n_users = 8
    n_writes_per_user = 20
    errors: list[BaseException] = []

    def worker(user_idx: int) -> None:
        user = f"user-{user_idx}"
        try:
            for i in range(n_writes_per_user):
                uid = f"{user}-contact-{i}"
                raw = CARD_TEMPLATE.format(uid=uid, name=f"Person {i}")
                store.upsert(user, "default", f"/dav/{uid}.vcf", f'W/"{i}"', raw)
                # Interleave a read of our own user's data while other
                # threads are writing theirs.
                store.list_contacts(user)
                store.get(user, f"/dav/{uid}.vcf")
        except BaseException as exc:  # noqa: BLE001 - capture for assertion
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(n_users)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"worker threads raised: {errors}"
    for i in range(n_users):
        user = f"user-{i}"
        contacts = store.list_contacts(user)
        assert len(contacts) == n_writes_per_user, (
            f"{user}: expected {n_writes_per_user} contacts, got {len(contacts)}"
        )


def test_concurrent_upserts_same_user_all_land():
    """Same-user writes from multiple threads without the app-level per-user
    lock (that lock lives in app.py, not the store) still must not corrupt
    data or deadlock the store itself — each write targets a distinct href,
    so no update should be lost."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        store = ContactStore(Path(tmp) / "cache.db")
        n_threads = 10
        n_per_thread = 15
        errors: list[BaseException] = []

        def worker(thread_idx: int) -> None:
            try:
                for i in range(n_per_thread):
                    uid = f"t{thread_idx}-c{i}"
                    raw = CARD_TEMPLATE.format(uid=uid, name=f"Person {uid}")
                    store.upsert("shared-user", "default", f"/dav/{uid}.vcf", 'W/"e"', raw)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"worker threads raised: {errors}"
        assert len(store.list_contacts("shared-user")) == n_threads * n_per_thread


def test_reader_not_blocked_by_concurrent_writer(store):
    """Under WAL, a reader on one thread should be able to run while a writer
    on another thread holds a long-ish write transaction, instead of raising
    SQLITE_BUSY or blocking for the writer's full duration."""
    store.upsert("jason", "default", "/dav/seed.vcf", 'W/"seed"', CARD_TEMPLATE.format(uid="seed", name="Seed"))

    writer_started = threading.Event()
    writer_finish = threading.Event()
    read_results: list[int] = []
    read_errors: list[BaseException] = []

    def writer() -> None:
        conn = store._conn
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO contacts"
                " (user, addressbook, href, etag, raw, uid, is_group, broken, sort_name, bday)"
                " VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, '')",
                ("jason", "default", "/dav/slow.vcf", 'W/"slow"', "raw", "slow", "slow"),
            )
            writer_started.set()
            # Hold the write transaction open for a bit while a reader runs
            # concurrently on another thread's connection.
            writer_finish.wait(timeout=5)

    def reader() -> None:
        writer_started.wait(timeout=5)
        try:
            start = time.monotonic()
            rows = store.list_contacts("jason")
            elapsed = time.monotonic() - start
            read_results.append(len(rows))
            # A blocked reader would wait for the writer (which holds the
            # transaction for up to ~1s below); under WAL it should return
            # almost immediately.
            assert elapsed < 1.0, f"reader blocked for {elapsed:.2f}s"
        except BaseException as exc:  # noqa: BLE001
            read_errors.append(exc)
        finally:
            writer_finish.set()

    wt = threading.Thread(target=writer)
    rt = threading.Thread(target=reader)
    wt.start()
    rt.start()
    wt.join(timeout=10)
    rt.join(timeout=10)

    assert not read_errors, f"reader raised: {read_errors}"
    # Reader ran before the writer committed, so it should see only the
    # seed row (snapshot isolation), not the uncommitted "slow" row.
    assert read_results == [1]


def test_close_checkpoints_wal_and_is_reopenable(tmp_path):
    db = tmp_path / "cache.db"
    store = ContactStore(db)
    store.upsert("u", "book", "c1.vcf", "e1", CARD_TEMPLATE.format(uid="c1", name="Cee One"))
    wal = Path(str(db) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0
    store.close()
    # Checkpoint truncated the WAL (file removed entirely when the last
    # connection closes, or left empty otherwise).
    assert not wal.exists() or wal.stat().st_size == 0
    store.close()  # second close on a thread with no cached conn: no-op
    # The store lazily reopens a fresh connection after close.
    assert [c.href for c in store.list_contacts("u")] == ["c1.vcf"]


def test_app_lifespan_closes_store(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from peopledb.app import create_app
    from peopledb.config import Settings

    settings = Settings(
        dav_url="http://127.0.0.1:9",  # never contacted
        db_path=str(tmp_path / "cache.db"),
        secure_cookies=False,
    )
    app = create_app(settings)
    app.state.store.upsert("u", "book", "c1.vcf", "e1", CARD_TEMPLATE.format(uid="c1", name="Cee One"))
    with TestClient(app):
        pass  # enter+exit runs lifespan startup/shutdown
    wal = Path(str(tmp_path / "cache.db") + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
