"""Tests for the display-settings popover (spec: specs/2026-07-15-display-settings.md):
a `#settings-panel` in the shared top-bar control cluster (`_topbar.html`, in-flow
since issue #26) holding six S/M/L size controls, plus the index-only List/Cards
view toggle.

Uses an in-process TestClient with a session created directly against
SessionStore and data seeded directly into ContactStore -- no live CardDAV
server needed. Mirrors tests/test_card_view.py and tests/test_detail_avatar_size.py."""

import re

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

CARD_BARE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:bare-1\r\n"
    "FN:Bare Bones\r\nN:Bones;Bare;;;\r\n"
    "END:VCARD\r\n"
)

SIZE_STORAGE_KEYS = [
    "peopledb-size-topbar",
    "peopledb-size-list",
    "peopledb-size-card-text",
    "peopledb-size-card-avatar",
    "peopledb-avatar-size",
    "peopledb-size-detail-text",
]

FIELD_TOKENS = ["org", "phone", "email", "bday", "url", "address"]


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
    store.upsert("tester", "/addressbook/", "/addressbook/bare-1.vcf", "etag-1", CARD_BARE)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


# -- gear control + popover render on any authenticated page ------------------


def test_index_page_has_settings_gear_and_popover(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="settings-panel"' in resp.text
    assert 'aria-label="Display settings"' in resp.text
    assert 'class="settings-popover"' in resp.text


def test_detail_page_has_settings_gear_and_popover(client):
    resp = client.get("/contacts/bare-1")
    assert resp.status_code == 200
    assert 'id="settings-panel"' in resp.text
    assert 'class="settings-popover"' in resp.text


# -- all six S/M/L size controls ------------------------------------------------


def test_popover_has_all_six_size_controls(client):
    resp = client.get("/")
    body = resp.text
    for key in SIZE_STORAGE_KEYS:
        assert f'data-size-storage-key="{key}"' in body

    for label in ("Top bar", "List view", "Card text", "Card avatar",
                  "Detail avatar", "Detail text"):
        assert label in body


def test_size_controls_only_offer_sm_md_lg_choices(client):
    resp = client.get("/")
    body = resp.text
    choices = re.findall(r'data-size-choice="([^"]+)"', body)
    assert choices, "expected at least one data-size-choice control"
    assert set(choices) == {"sm", "md", "lg"}


def test_size_group_root_attrs_are_the_expected_six(client):
    resp = client.get("/")
    body = resp.text
    attrs = re.findall(r'data-size-attr="([^"]+)"', body)
    assert set(attrs) == {
        "data-size-topbar",
        "data-size-list",
        "data-size-card-text",
        "data-size-card-avatar",
        "data-size-detail-avatar",
        "data-size-detail-text",
    }


# -- List/Cards view toggle stays on the index (not in the popover) ------------


def test_view_toggle_is_on_index_and_not_in_the_popover(client):
    body = client.get("/").text
    # The view toggle lives in its own index-page section.
    assert 'class="view-toggle"' in body
    assert 'action="/view"' in body
    # Isolate the settings-panel <details> and confirm the view form isn't in it.
    panel = body.split('id="settings-panel"', 1)[1].split("</details>", 1)[0]
    assert 'action="/view"' not in panel


def test_view_toggle_does_not_appear_off_the_index(client):
    # The toggle is index-only (where `view` is in context); the global popover
    # must not carry it onto the detail page.
    assert 'action="/view"' not in client.get("/contacts/bare-1").text


def test_search_and_quick_add_render_on_index_only(client):
    # The shared top bar (_topbar.html) renders the centered search + quick-add
    # only when the includer sets `show_search` (index does; other pages don't).
    # Guards the `{% set show_search = true %}` line in index.html -- delete it
    # and the search/quick-add silently vanish while the suite stays green.
    index = client.get("/").text
    assert 'hx-get="/search"' in index
    assert 'class="quick-add"' in index
    # A non-index page includes the same bar without show_search -> no search.
    detail = client.get("/contacts/bare-1").text
    assert 'hx-get="/search"' not in detail
    assert 'class="quick-add"' not in detail


# -- old locations are gone ----------------------------------------------------


def test_old_inline_avatar_size_toggle_is_gone_from_detail_page(client):
    resp = client.get("/contacts/bare-1")
    assert 'id="avatar-size-toggle"' not in resp.text
    assert "data-avatar-size-choice" not in resp.text


def test_detail_text_scope_is_marked_and_not_leaked_to_list_pages(client):
    # The detail-text size control targets `main.contact-detail`, so the
    # detail page's <main> must carry that marker class and the index/list
    # page's <main> must NOT (else the knob would resize the contact list and
    # compound with the list/card size controls). Guards the code-review fix.
    detail = client.get("/contacts/bare-1").text
    index = client.get("/").text
    assert '<main class="contact-detail">' in detail
    assert '<main class="contact-index">' in index
    assert '<main class="contact-detail">' not in index


def test_index_has_exactly_one_view_toggle_form(client):
    # Exactly one /view form on the index (its own section) -- not duplicated
    # into the popover.
    assert client.get("/").text.count('action="/view"') == 1


# -- field selection groups (#27) ----------------------------------------------


def test_popover_has_list_and_card_fields_groups(client):
    body = client.get("/").text
    assert 'data-fields-storage-key="peopledb-list-fields"' in body
    assert 'data-fields-attr="data-list-fields"' in body
    assert 'data-fields-storage-key="peopledb-card-fields"' in body
    assert 'data-fields-attr="data-card-fields"' in body
    assert "List fields" in body
    assert "Card fields" in body


def test_field_groups_each_offer_six_checkboxes_for_the_allow_listed_tokens(client):
    body = client.get("/").text
    list_group = body.split('data-fields-storage-key="peopledb-list-fields"')[1].split(
        "</div>", 1
    )[0]
    card_group = body.split('data-fields-storage-key="peopledb-card-fields"')[1].split(
        "</div>", 1
    )[0]
    for group in (list_group, card_group):
        values = re.findall(r'<input type="checkbox" value="([^"]+)"', group)
        assert values == FIELD_TOKENS
