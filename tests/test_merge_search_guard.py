"""Tests for issue #31: the merge-candidate search endpoint
`GET /contacts/{uid}/merge/search` must not offer candidates when the *primary*
`uid` in the path is itself a group. Groups can't be merged (the action is
rejected downstream and the picker is hidden on group pages since #30), so the
search endpoint offering a populated candidate list is a defense-in-depth gap.

Uses an in-process TestClient with data seeded directly into ContactStore --
no live CardDAV server needed."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

PERSON_1 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-1\r\n"
    "FN:Jane Person\r\nN:Person;Jane;;;\r\n"
    "END:VCARD\r\n"
)

PERSON_2 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-2\r\n"
    "FN:John Other\r\nN:Other;John;;;\r\n"
    "END:VCARD\r\n"
)

GROUP_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:group-family\r\n"
    "FN:Family\r\nN:Family;;;;\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "END:VCARD\r\n"
)


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        dav_url="http://unused.invalid",
        secret_key="",
        db_path=str(tmp_path / "cache.db"),
        secure_cookies=False,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    store = app.state.store
    store.upsert("tester", "/addressbook/", "/addressbook/person-1.vcf", "etag-1", PERSON_1)
    store.upsert("tester", "/addressbook/", "/addressbook/person-2.vcf", "etag-2", PERSON_2)
    store.upsert("tester", "/addressbook/", "/addressbook/group-family.vcf", "etag-3", GROUP_CARD)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_merge_search_on_group_primary_offers_no_candidates(client):
    resp = client.get("/contacts/group-family/merge/search")
    assert resp.status_code == 200
    # No mergeable candidate should be offered for a group primary.
    assert "/merge?with=" not in resp.text
    assert "No contacts found." in resp.text


def test_merge_search_on_contact_primary_still_offers_candidates(client):
    # Positive control: an ordinary contact primary still lists other
    # non-group contacts (self and groups excluded).
    resp = client.get("/contacts/person-1/merge/search")
    assert resp.status_code == 200
    assert "/contacts/person-1/merge?with=person-2" in resp.text
    assert "person-1/merge?with=person-1" not in resp.text  # self excluded
    assert "with=group-family" not in resp.text              # group excluded
