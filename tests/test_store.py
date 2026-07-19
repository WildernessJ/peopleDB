"""Tests for the cache/sync store seam: ContactStore over SQLite."""

import sqlite3

import pytest

from peopledb.store import ContactStore, _SCHEMA_VERSION

CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:abc-123\r\n"
    "FN:Sarah Jones\r\n"
    "N:Jones;Sarah;;;\r\n"
    "ORG:Acme Corp;\r\n"
    "EMAIL;TYPE=WORK:sarah@acme.example\r\n"
    "TEL;TYPE=CELL:+1 555 0100\r\n"
    "END:VCARD\r\n"
)


@pytest.fixture
def store(tmp_path):
    return ContactStore(tmp_path / "cache.db")


def test_upsert_and_get_roundtrip(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"etag-1"', CARD)
    rec = store.get("jason", "/dav/abc-123.vcf")
    assert rec.etag == 'W/"etag-1"'
    assert rec.raw == CARD
    assert rec.contact.formatted_name == "Sarah Jones"
    assert rec.contact.uid == "abc-123"


def test_upsert_replaces_on_same_href(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"etag-1"', CARD)
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"etag-2"', CARD.replace("Sarah", "Sara"))
    assert len(store.list_contacts("jason")) == 1
    assert store.get("jason", "/dav/abc-123.vcf").etag == 'W/"etag-2"'


def test_delete_removes_record(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', CARD)
    store.delete("jason", "/dav/abc-123.vcf")
    assert store.get("jason", "/dav/abc-123.vcf") is None
    assert store.list_contacts("jason") == []


def test_records_are_per_user(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', CARD)
    assert store.list_contacts("someone-else") == []


GROUP = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:grp-1\r\n"
    "FN:Book Club\r\n"
    "N:Book Club\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:abc-123\r\n"
    "END:VCARD\r\n"
)

BDAY_CARD = CARD.replace("END:VCARD", "BDAY:1985-04-12\r\nEND:VCARD")


def test_search_matches_name_email_org_with_prefix(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', CARD)
    for query in ("sar", "jones", "acme", "sarah@acme.example"):
        hits = store.search("jason", query)
        assert [r.contact.uid for r in hits] == ["abc-123"], f"query {query!r} missed"
    assert store.search("jason", "zzz-nothing") == []
    assert store.search("someone-else", "sarah") == []


ADDRESS_URL_CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:addr-url-1\r\n"
    "FN:Wendell Voss\r\n"
    "N:Voss;Wendell;;;\r\n"
    "ADR;TYPE=HOME:;;123 Zorbington Lane;Blorpville;Cascadia;98765;Freedonia\r\n"
    "URL;TYPE=WORK:https://zibblequonk.example\r\n"
    "END:VCARD\r\n"
)


def test_search_matches_address_tokens(store):
    store.upsert("jason", "default", "/dav/addr-url-1.vcf", 'W/"e"', ADDRESS_URL_CARD)
    for query in ("zorbington", "blorpville", "98765", "freedonia"):
        hits = store.search("jason", query)
        assert [r.contact.uid for r in hits] == ["addr-url-1"], f"query {query!r} missed"


def test_search_matches_url_token(store):
    store.upsert("jason", "default", "/dav/addr-url-1.vcf", 'W/"e"', ADDRESS_URL_CARD)
    hits = store.search("jason", "zibblequonk")
    assert [r.contact.uid for r in hits] == ["addr-url-1"]


def test_search_no_match_returns_empty(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', CARD)
    store.upsert("jason", "default", "/dav/addr-url-1.vcf", 'W/"e"', ADDRESS_URL_CARD)
    assert store.search("jason", "nonexistent-token-xyz") == []


OLD_FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE contacts_fts USING fts5("
    "user UNINDEXED, href UNINDEXED, name, org, emails, phones, note"
    ")"
)


def test_migration_rebuilds_fts_from_old_schema(tmp_path):
    db_path = tmp_path / "cache.db"

    # Bootstrap a store normally, then downgrade it in place to simulate an
    # old cache: old contacts_fts column set, user_version reset to 0. The
    # `contacts` row (the canonical source the rebuild re-derives from)
    # stays untouched.
    ContactStore(db_path).close()
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("DROP TABLE contacts_fts")
    raw_conn.execute(OLD_FTS_SCHEMA)
    raw_conn.execute(
        "INSERT INTO contacts (user, addressbook, href, etag, raw, uid, is_group, broken,"
        " sort_name, bday) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, '')",
        ("jason", "default", "/dav/addr-url-1.vcf", 'W/"e"', ADDRESS_URL_CARD,
         "addr-url-1", "voss wendell"),
    )
    raw_conn.execute("PRAGMA user_version = 0")
    raw_conn.commit()
    raw_conn.close()

    store = ContactStore(db_path)
    try:
        assert [r.contact.uid for r in store.search("jason", "zorbington")] == ["addr-url-1"]
        assert [r.contact.uid for r in store.search("jason", "zibblequonk")] == ["addr-url-1"]
    finally:
        store.close()

    # Re-opening must be idempotent: the version gate must skip a second
    # rebuild. A passing search alone can't prove that -- a re-run rebuild
    # repopulates from the same `contacts` row, so search would work either
    # way. Prove the gate discriminates: the first open must have stamped the
    # version, and a sentinel FTS row with no backing `contacts` row (so a
    # rebuild would drop it and never re-add it) must survive the re-open.
    probe = sqlite3.connect(db_path)
    assert probe.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    probe.execute(
        "INSERT INTO contacts_fts (user, href, name) VALUES ('jason', '/sentinel', 'sentinelquux')"
    )
    probe.commit()
    probe.close()

    store2 = ContactStore(db_path)
    try:
        assert [r.contact.uid for r in store2.search("jason", "blorpville")] == ["addr-url-1"]
    finally:
        store2.close()

    verify = sqlite3.connect(db_path)
    sentinel_rows = verify.execute(
        "SELECT href FROM contacts_fts WHERE contacts_fts MATCH 'sentinelquux'"
    ).fetchall()
    verify.close()
    assert sentinel_rows == [("/sentinel",)], "second open wrongly rebuilt contacts_fts"


def test_groups_listed_separately_from_contacts(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', CARD)
    store.upsert("jason", "default", "/dav/grp-1.vcf", 'W/"g"', GROUP)
    assert [r.contact.uid for r in store.list_contacts("jason")] == ["abc-123"]
    groups = store.list_groups("jason")
    assert [g.contact.uid for g in groups] == ["grp-1"]
    assert groups[0].contact.member_uids == ["abc-123"]


def test_unparseable_card_is_listed_broken_not_fatal(store):
    store.upsert("jason", "default", "/dav/junk.vcf", 'W/"j"', "NOT A VCARD")
    assert store.list_contacts("jason") == []
    broken = store.list_broken("jason")
    assert [b.href for b in broken] == ["/dav/junk.vcf"]


def test_contacts_with_bday(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', BDAY_CARD)
    store.upsert("jason", "default", "/dav/grp-1.vcf", 'W/"g"', GROUP)
    withdays = store.contacts_with_bday("jason")
    assert [r.contact.uid for r in withdays] == ["abc-123"]
    assert withdays[0].contact.bday == "1985-04-12"


def test_get_by_uid(store):
    store.upsert("jason", "default", "/dav/abc-123.vcf", 'W/"e"', CARD)
    rec = store.get_by_uid("jason", "abc-123")
    assert rec is not None and rec.href == "/dav/abc-123.vcf"
    assert store.get_by_uid("jason", "nope") is None


def test_get_by_uid_deterministic_on_duplicate_uid(store):
    # The table's primary key is (user, href), not uid -- nothing stops two
    # rows from sharing a (user, uid) if a bad import or unresolved sync
    # conflict ever produces one. get_by_uid must pick deterministically:
    # smallest href wins (the "ORDER BY href" tiebreak, issue #33).
    #
    # Honest scoping of this test: it pins the *direction* of the tiebreak
    # (smallest href) and would catch an accidental "ORDER BY href DESC". It is
    # NOT a red-without-fix regression guard, and can't be one through the
    # public API on the current schema: SQLite already satisfies this query via
    # the (user, href) PK autoindex, whose B-tree is walked in href order for a
    # fixed user, so fetchone() returns the smallest href even with no ORDER BY.
    # The "ORDER BY href" fix is therefore belt-and-suspenders -- it makes the
    # guarantee explicit and robust to a future schema/index change (e.g. adding
    # a uid index) that would otherwise remove the incidental ordering.
    store.upsert("jason", "default", "/dav/zzz-later.vcf", 'W/"e1"', CARD)
    store.upsert("jason", "default", "/dav/aaa-earlier.vcf", 'W/"e2"', CARD)

    rec = store.get_by_uid("jason", "abc-123")

    assert rec is not None
    assert rec.href == "/dav/aaa-earlier.vcf"


def test_feed_token_stable_and_resolvable(store):
    token = store.ensure_feed_token("jason")
    assert token
    assert store.ensure_feed_token("jason") == token  # stable across calls
    assert store.user_for_feed_token(token) == "jason"
    assert store.user_for_feed_token("bogus") is None


def test_sync_token_roundtrip(store):
    assert store.get_sync_token("jason", "default") is None
    store.set_sync_token("jason", "default", "http://sabre.io/ns/sync/12")
    assert store.get_sync_token("jason", "default") == "http://sabre.io/ns/sync/12"
