"""Tests for the contact card view toggle (issue #10): the peopledb_view
cookie, the POST /view route that sets it, and card-vs-list rendering in
index/search.

Uses an in-process TestClient with a session created directly against
SessionStore and data seeded directly into ContactStore -- no live CardDAV
server needed."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

CARD_FULL = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:full-1\r\n"
    "FN:Fully Loaded\r\nN:Loaded;Fully;;;\r\n"
    "ORG:Acme Corp\r\n"
    "TEL:+1 555 111 2222\r\n"
    "EMAIL:fully@example.com\r\n"
    "END:VCARD\r\n"
)

CARD_ALL_FIELDS = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:all-1\r\n"
    "FN:All Fields\r\nN:Fields;All;;;\r\n"
    "ORG:Acme Corp\r\n"
    "TEL:+1 555 111 2222\r\n"
    "EMAIL:all@example.com\r\n"
    "BDAY:1990-05-12\r\n"
    "URL:https://example.com/all\r\n"
    "ADR:;;123 Main St;Springfield;IL;62704;USA\r\n"
    "END:VCARD\r\n"
)

CARD_BARE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:bare-1\r\n"
    "FN:Bare Bones\r\nN:Bones;Bare;;;\r\n"
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
    store.upsert("tester", "/addressbook/", "/addressbook/full-1.vcf", "etag-1", CARD_FULL)
    store.upsert("tester", "/addressbook/", "/addressbook/bare-1.vcf", "etag-2", CARD_BARE)
    store.upsert("tester", "/addressbook/", "/addressbook/all-1.vcf", "etag-3", CARD_ALL_FIELDS)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


# -- default / cookie handling ------------------------------------------------


def test_index_defaults_to_list_view_when_no_cookie(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'class="contacts"' in resp.text
    assert 'class="contact-cards"' not in resp.text


def test_index_renders_card_view_when_cookie_set(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'class="contact-cards"' in resp.text


def test_invalid_cookie_value_falls_back_to_list(client):
    client.cookies.set("peopledb_view", "bogus")
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'class="contacts"' in resp.text
    assert 'class="contact-cards"' not in resp.text


# -- POST /view ----------------------------------------------------------------


def test_post_view_sets_cookie_and_redirects(client):
    resp = client.post("/view", data={"view": "card"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert resp.cookies.get("peopledb_view") == "card"


def test_post_view_back_to_list(client):
    resp = client.post("/view", data={"view": "list"})
    assert resp.status_code == 303
    assert resp.cookies.get("peopledb_view") == "list"


def test_post_view_rejects_invalid_value(client):
    resp = client.post("/view", data={"view": "grid9000"})
    assert resp.status_code == 303
    # Falls back to list rather than persisting a bogus value.
    assert resp.cookies.get("peopledb_view") in ("list", None)


# -- card markup content ---------------------------------------------------


def test_card_view_shows_avatar_name_org_phone_email(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    body = resp.text
    assert "Fully Loaded" in body
    assert "Acme Corp" in body
    assert "555" in body or "555 111 2222" in body
    assert "fully@example.com" in body
    assert '/contacts/full-1' in body


def test_card_view_bare_contact_omits_optional_fields_gracefully(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Bare Bones" in resp.text


def test_empty_state_in_card_view(app):
    sid = app.state.sessions.create("nobodyhome", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    c.cookies.set("peopledb_view", "card")
    resp = c.get("/")
    assert "No contacts found." in resp.text


# -- search fragment respects the cookie ---------------------------------------


def test_search_fragment_renders_card_view_when_cookie_set(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/search", params={"q": "Fully"})
    assert resp.status_code == 200
    assert 'class="contact-cards"' in resp.text
    assert "Acme Corp" in resp.text


def test_search_fragment_renders_list_view_by_default(client):
    resp = client.get("/search", params={"q": "Fully"})
    assert resp.status_code == 200
    assert 'class="contacts"' in resp.text
    assert 'class="contact-cards"' not in resp.text


# -- toggle control on index page ----------------------------------------------


def test_index_page_has_view_toggle_posting_to_view_route(client):
    resp = client.get("/")
    assert 'action="/view"' in resp.text
    assert 'name="view"' in resp.text
    assert 'value="list"' in resp.text
    assert 'value="card"' in resp.text


# -- field selection (#27): render-all + CSS-hide, both views -----------------
#
# Every toggleable field renders behind a stable field-<name> class, still
# guarded so an absent field emits nothing; show/hide itself is CSS-driven
# (live-verified in browser) and not asserted here.


def test_card_view_renders_all_field_classes_for_a_fully_loaded_contact(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    body = resp.text
    assert '<span class="org field-org"><span class="sr-only">Org: </span>Acme Corp</span>' in body
    assert 'class="detail field-phone"' in body
    assert 'class="detail field-email"><span class="sr-only">Email: </span>all@example.com</span>' in body
    assert 'class="detail field-bday"><span class="sr-only">Birthday: </span>1990-05-12</span>' in body
    assert 'class="detail field-url"><span class="sr-only">URL: </span>https://example.com/all</span>' in body
    assert 'class="detail field-address">' in body
    assert "Springfield" in body


def test_card_view_omits_field_spans_for_bare_contact(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    # Isolate the bare-1 <li> so we don't pick up spans from other seeded
    # contacts on the same page.
    body = resp.text
    # Isolate the bare contact's full <li>: the chunk from its own "<li"
    # up to the next "<li" (field spans render AFTER the name, so slicing
    # before the name — as an earlier version did — never saw them and the
    # assertions were vacuous).
    li = next(chunk for chunk in body.split("<li") if "Bare Bones" in chunk)
    assert "field-org" not in li
    assert "field-phone" not in li
    assert "field-email" not in li
    assert "field-bday" not in li
    assert "field-url" not in li
    assert "field-address" not in li


def test_list_view_renders_all_field_classes_for_a_fully_loaded_contact(client):
    resp = client.get("/")
    body = resp.text
    assert '<span class="org field-org"><span class="sr-only">Org: </span>Acme Corp</span>' in body
    assert 'class="detail field-phone"' in body
    assert 'class="detail field-email"><span class="sr-only">Email: </span>all@example.com</span>' in body
    assert 'class="detail field-bday"><span class="sr-only">Birthday: </span>1990-05-12</span>' in body
    assert 'class="detail field-url"><span class="sr-only">URL: </span>https://example.com/all</span>' in body
    assert 'class="detail field-address">' in body
    assert "Springfield" in body


def test_list_view_omits_field_spans_for_bare_contact(client):
    resp = client.get("/")
    body = resp.text
    li = next(chunk for chunk in body.split("<li") if "Bare Bones" in chunk)
    assert "field-org" not in li
    assert "field-phone" not in li
    assert "field-email" not in li
    assert "field-bday" not in li
    assert "field-url" not in li
    assert "field-address" not in li


# -- issue #29: screen-reader field labels ------------------------------------


def test_card_view_field_spans_have_sr_only_labels_for_all_fields(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    body = resp.text
    assert (
        '<span class="org field-org"><span class="sr-only">Org: </span>'
        "Acme Corp</span>" in body
    )
    assert (
        '<span class="detail field-phone"><span class="sr-only">Phone: </span>'
        "+1 555 111 2222</span>" in body
    )
    assert (
        '<span class="detail field-email"><span class="sr-only">Email: </span>'
        "all@example.com</span>" in body
    )
    assert (
        '<span class="detail field-bday"><span class="sr-only">Birthday: </span>'
        "1990-05-12</span>" in body
    )
    assert (
        '<span class="detail field-url"><span class="sr-only">URL: </span>'
        "https://example.com/all</span>" in body
    )
    assert '<span class="detail field-address"><span class="sr-only">Address: </span>' in body


def test_list_view_field_spans_have_sr_only_labels_spot_check(client):
    resp = client.get("/")
    body = resp.text
    assert (
        '<span class="detail field-phone"><span class="sr-only">Phone: </span>'
        "+1 555 111 2222</span>" in body
    )
    assert (
        '<span class="org field-org"><span class="sr-only">Org: </span>'
        "Acme Corp</span>" in body
    )
    # Address label: covered here so a list-only regression in the address
    # span (which the card block wouldn't catch) still fails CI.
    assert (
        '<span class="detail field-address"><span class="sr-only">Address: </span>'
        in body
    )
    assert "Springfield" in body


def test_card_view_bare_contact_has_no_sr_only_field_labels(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    body = resp.text
    li = next(chunk for chunk in body.split("<li") if "Bare Bones" in chunk)
    assert "sr-only" not in li


def test_list_view_bare_contact_has_no_sr_only_field_labels(client):
    resp = client.get("/")
    body = resp.text
    li = next(chunk for chunk in body.split("<li") if "Bare Bones" in chunk)
    assert "sr-only" not in li
