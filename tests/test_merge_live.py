"""Live tests for the merge-duplicate-contacts write sequence (#28, ADR-0006):
happy-path union + delete, keeper-etag-conflict abort (zero writes), group
membership moved source->keeper, and delete-fails leaving a harmless leftover
with a surfaced warning."""

import re

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings
from peopledb.dav import DavClient

pytestmark = pytest.mark.live


@pytest.fixture
def dav(dav_server):
    return DavClient(dav_server["base_url"], dav_server["username"], dav_server["password"])


@pytest.fixture
def book(dav):
    (book,) = [b for b in dav.addressbooks() if b.name == "Test Contacts"]
    return book


@pytest.fixture
def client(dav_server, tmp_path):
    settings = Settings(
        dav_url=dav_server["base_url"], secret_key="",
        db_path=str(tmp_path / "cache.db"), secure_cookies=False,
    )
    client = TestClient(create_app(settings), follow_redirects=False)
    resp = client.post("/login", data={"username": "testuser", "password": "anything"})
    assert resp.status_code == 303
    return client


CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\n"
    "FN:{fn}\r\nN:{family};{given};;;\r\n"
    "{extra}"
    "END:VCARD\r\n"
)


def make(dav, book, uid, given, family, extra=""):
    return dav.create(
        book.url, uid,
        CARD.format(uid=uid, fn=f"{given} {family}", given=given, family=family, extra=extra),
    )


_ADDRESS_SUBFIELDS = (
    "label", "street", "city", "region", "code", "country", "pobox", "extended",
)


def _hidden_value(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    return match.group(1) if match else ""


def _merge_form_data(client, keeper_uid, with_uid, **overrides):
    """GET the review screen and read back every union row (index + its
    label/value hidden fields) so the POST exactly mirrors what a browser
    would submit with every checkbox left checked."""
    resp = client.get(f"/contacts/{keeper_uid}/merge", params={"with": with_uid})
    assert resp.status_code == 200, resp.text
    html = resp.text
    data: dict[str, object] = {"with": with_uid, "keeper_uid": keeper_uid}
    for prefix in ("email", "phone", "url", "related"):
        indices = re.findall(rf'name="{prefix}_keep" value="([^"]*)"', html)
        data[f"{prefix}_keep"] = indices
        for i in indices:
            data[f"{prefix}_label_{i}"] = _hidden_value(html, f"{prefix}_label_{i}")
            data[f"{prefix}_value_{i}"] = _hidden_value(html, f"{prefix}_value_{i}")
    indices = re.findall(r'name="adr_keep" value="([^"]*)"', html)
    data["adr_keep"] = indices
    for i in indices:
        for sub in _ADDRESS_SUBFIELDS:
            data[f"adr_{sub}_{i}"] = _hidden_value(html, f"adr_{sub}_{i}")
    data.update(overrides)
    return data


def test_merge_happy_path_unions_and_deletes_source(client, dav, book):
    a_href, _ = make(dav, book, "merge-a", "Alice", "Keeper", "EMAIL;TYPE=WORK:alice@work.example\r\n")
    b_href, _ = make(dav, book, "merge-b", "Alice", "Duplicate", "EMAIL;TYPE=HOME:alice@home.example\r\n")
    client.get("/refresh")

    data = _merge_form_data(client, "merge-a", "merge-b")
    resp = client.post("/contacts/merge-a/merge", data=data)
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/contacts/merge-a"

    raw, _ = dav.get(a_href)
    assert "alice@work.example" in raw
    assert "alice@home.example" in raw  # unioned from the source

    raw_b, _ = dav.get(b_href, missing_ok=True)
    assert raw_b is None  # source deleted


def test_merge_rejects_self(client, dav, book):
    make(dav, book, "merge-self", "Solo", "Person")
    client.get("/refresh")
    resp = client.get("/contacts/merge-self/merge", params={"with": "merge-self"})
    assert resp.status_code == 400
    assert "itself" in resp.text.lower()


def test_merge_rejects_group(client, dav, book):
    make(dav, book, "merge-g1", "Group", "Target")
    client.get("/refresh")
    resp = client.post("/groups", data={"name": "A Group"})
    assert resp.status_code == 303
    group_uid = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.get("/contacts/merge-g1/merge", params={"with": group_uid})
    assert resp.status_code == 400
    assert "group" in resp.text.lower()


def test_merge_keeper_conflict_aborts_with_zero_writes(client, dav, book):
    a_href, _ = make(dav, book, "merge-ca", "Carl", "Keeper")
    b_href, b_etag = make(dav, book, "merge-cb", "Carl", "Duplicate")
    client.get("/refresh")

    data = _merge_form_data(client, "merge-ca", "merge-cb")

    # Someone edits the keeper behind our back after the review screen loaded.
    fresh_raw, fresh_etag = dav.get(a_href)
    dav.put(a_href, fresh_raw.replace("Carl Keeper", "Behind-Your-Back"), fresh_etag)

    resp = client.post("/contacts/merge-ca/merge", data=data)
    assert resp.status_code == 409
    assert "changed" in resp.text.lower()

    keeper_raw, _ = dav.get(a_href)
    assert "Behind-Your-Back" in keeper_raw  # untouched by the merge attempt

    source_raw, _ = dav.get(b_href, missing_ok=True)
    assert source_raw is not None  # zero writes: source was never deleted
    assert b_etag  # (the source's original etag is still valid -- no PUT touched it)


def test_merge_keeper_flip_does_not_invert_field_choices(client, dav, book):
    """Regression for #28 finding 1: field radios are labeled/populated by
    contact_a/contact_b, so picking a MIX of a's and b's single-valued fields
    must survive intact even when the KEEPER (the surviving card) is b, not
    a. Before the fix, keeper/source resolution inverted every field choice
    on a keeper-flip -- this pins the surviving card to hold exactly what was
    picked, not the opposite."""
    a_href, _ = make(
        dav, book, "merge-fa", "Alice", "Anderson",
        "ORG:Alice Corp\r\nNOTE:alice note\r\nBDAY:1980-01-01\r\n",
    )
    b_href, _ = make(
        dav, book, "merge-fb", "Bob", "Baker",
        "ORG:Bob Corp\r\nNOTE:bob note\r\nBDAY:1990-02-02\r\n",
    )
    client.get("/refresh")

    data = _merge_form_data(client, "merge-fa", "merge-fb")
    data["keeper_uid"] = "merge-fb"  # keeper flips to contact_b
    data["name_choice"] = "a"  # pick contact_a's given/family
    data["org_choice"] = "b"   # pick contact_b's org
    data["note_choice"] = "a"  # pick contact_a's note
    data["bday_choice"] = "b"  # pick contact_b's bday
    resp = client.post("/contacts/merge-fa/merge", data=data)
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/contacts/merge-fb"

    raw, _ = dav.get(b_href)  # keeper survives at contact_b's href
    assert "N:Anderson;Alice" in raw  # name_choice=a -> contact_a's name won
    assert "Bob Corp" in raw  # org_choice=b -> contact_b's org won
    assert "Alice Corp" not in raw
    assert "1990-02-02" in raw  # bday_choice=b -> contact_b's bday won
    assert "alice note" in raw  # note_choice=a -> contact_a's note won

    raw_a, _ = dav.get(a_href, missing_ok=True)
    assert raw_a is None  # source (contact_a) deleted


def test_merge_rejects_out_of_set_keeper_uid_with_no_writes(client, dav, book):
    a_href, _ = make(dav, book, "merge-ra", "Rae", "Anderson")
    b_href, _ = make(dav, book, "merge-rb", "Rae", "Baker")
    client.get("/refresh")

    data = _merge_form_data(client, "merge-ra", "merge-rb")
    data["keeper_uid"] = "not-a-real-uid"
    resp = client.post("/contacts/merge-ra/merge", data=data)
    assert resp.status_code == 400, resp.text

    raw_a, _ = dav.get(a_href)
    assert "Rae Anderson" in raw_a  # untouched -- no write happened
    raw_b, _ = dav.get(b_href)
    assert "Rae Baker" in raw_b  # untouched, and not deleted either


def test_merge_photo_choice_from_uri_only_card_preserves_keeper_photo(client, dav, book):
    """Regression for #28 finding 2: a URI-only PHOTO (photo_uri set, no
    embedded base64) still trips `has_photo`. Picking that card's photo must
    NOT emit an empty PHOTO line clobbering the keeper's real embedded
    photo -- it must leave the keeper's existing PHOTO untouched."""
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    a_href, _ = make(
        dav, book, "merge-pa", "Pat", "Anderson",
        f"PHOTO;ENCODING=b;TYPE=PNG:{tiny_png_b64}\r\n",
    )
    b_href, _ = make(
        dav, book, "merge-pb", "Pat", "Baker",
        "PHOTO;VALUE=uri:https://example.com/pat.jpg\r\n",
    )
    client.get("/refresh")

    data = _merge_form_data(client, "merge-pa", "merge-pb", photo_choice="b")
    resp = client.post("/contacts/merge-pa/merge", data=data)
    assert resp.status_code == 303, resp.text
    # Finding 1: the choice wasn't silently dropped -- it's surfaced as a
    # merge_warn clause rather than a plain success redirect.
    assert "merge_warn=" in resp.headers["location"]

    raw, _ = dav.get(a_href)
    assert tiny_png_b64 in raw  # keeper's embedded photo preserved, untouched
    photo_lines = [line for line in raw.splitlines() if line.upper().startswith("PHOTO")]
    assert len(photo_lines) == 1  # no extra/empty PHOTO line was added

    follow = client.get(resp.headers["location"])
    assert follow.status_code == 200
    assert "photo not merged" in follow.text


def test_merge_moves_group_membership_source_to_keeper(client, dav, book):
    a_href, _ = make(dav, book, "merge-ga", "Gwen", "Keeper")
    b_href, _ = make(dav, book, "merge-gb", "Gwen", "Duplicate")
    client.get("/refresh")

    resp = client.post("/groups", data={"name": "Merge Group"})
    group_uid = resp.headers["location"].rsplit("/", 1)[-1]
    client.post(f"/groups/{group_uid}/members", data={"member_uid": "merge-gb"})

    data = _merge_form_data(client, "merge-ga", "merge-gb")
    resp = client.post("/contacts/merge-ga/merge", data=data)
    assert resp.status_code == 303

    group_href = f"{book.url.rstrip('/')}/{group_uid}.vcf"
    group_raw, _ = dav.get(group_href)
    assert "urn:uuid:merge-ga" in group_raw
    assert "urn:uuid:merge-gb" not in group_raw


def test_merge_delete_failure_warns_and_leaves_source_and_keeper_intact(client, dav, book):
    a_href, _ = make(dav, book, "merge-da", "Dana", "Keeper")
    b_href, _ = make(dav, book, "merge-db", "Dana", "Duplicate")
    client.get("/refresh")

    data = _merge_form_data(client, "merge-da", "merge-db")

    # Someone edits the source behind our back so its cached etag is stale --
    # the keeper PUT (step 1) still succeeds, but the source DELETE (step 3,
    # last) 412s. This exercises the "delete fails" branch live, since forcing
    # a real transport failure against the throwaway server isn't practical.
    fresh_raw, fresh_etag = dav.get(b_href)
    dav.put(b_href, fresh_raw.replace("Dana Duplicate", "Edited-Elsewhere"), fresh_etag)

    resp = client.post("/contacts/merge-da/merge", data=data)
    assert resp.status_code == 303
    assert "merge_warn=" in resp.headers["location"]

    keeper_raw, _ = dav.get(a_href)
    assert "Dana Keeper" in keeper_raw  # merge itself did land on the keeper

    source_raw, _ = dav.get(b_href, missing_ok=True)
    assert source_raw is not None  # delete failed -> harmless leftover survives
    assert "Edited-Elsewhere" in source_raw

    # Finding 2: the redirect must be followed to a merge-specific banner --
    # not the #24 group_warn sentence ("Contact saved, but could not be added
    # to: ..."), which reads as nonsense for a delete-failure clause.
    follow = client.get(resp.headers["location"])
    assert follow.status_code == 200
    assert "Merge completed with warnings:" in follow.text
    assert "could not be deleted" in follow.text
    assert "could not be added to" not in follow.text


def test_merge_search_links_to_review_screen_excludes_self_and_groups(client, dav, book):
    """Finding 3: the merge-flavored search fragment links each result to the
    merge REVIEW screen (not detail, unlike /search's _contacts.html), and
    excludes both self and groups -- neither is a valid merge target."""
    make(dav, book, "merge-sa", "Searchy", "Anderson")
    make(dav, book, "merge-sb", "Searchy", "Baker")
    client.get("/refresh")
    resp = client.post("/groups", data={"name": "Searchy Group"})
    group_uid = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.get("/contacts/merge-sa/merge/search", params={"q": "Searchy"})
    assert resp.status_code == 200, resp.text
    assert "/contacts/merge-sa/merge?with=merge-sb" in resp.text
    assert "with=merge-sa" not in resp.text  # self excluded
    assert f"with={group_uid}" not in resp.text  # group excluded


def test_merge_moves_membership_in_two_groups(client, dav, book):
    """Finding 4: a source that's a member of TWO groups gets rewritten
    source->keeper in BOTH, not just the first one found."""
    a_href, _ = make(dav, book, "merge-2ga", "Multi", "Keeper")
    b_href, _ = make(dav, book, "merge-2gb", "Multi", "Duplicate")
    client.get("/refresh")

    resp = client.post("/groups", data={"name": "First Group"})
    group1_uid = resp.headers["location"].rsplit("/", 1)[-1]
    resp = client.post("/groups", data={"name": "Second Group"})
    group2_uid = resp.headers["location"].rsplit("/", 1)[-1]
    client.post(f"/groups/{group1_uid}/members", data={"member_uid": "merge-2gb"})
    client.post(f"/groups/{group2_uid}/members", data={"member_uid": "merge-2gb"})

    data = _merge_form_data(client, "merge-2ga", "merge-2gb")
    resp = client.post("/contacts/merge-2ga/merge", data=data)
    assert resp.status_code == 303
    assert "merge_warn" not in resp.headers["location"]

    for group_uid in (group1_uid, group2_uid):
        group_href = f"{book.url.rstrip('/')}/{group_uid}.vcf"
        group_raw, _ = dav.get(group_href)
        assert "urn:uuid:merge-2ga" in group_raw
        assert "urn:uuid:merge-2gb" not in group_raw

    source_raw, _ = dav.get(b_href, missing_ok=True)
    assert source_raw is None  # source deleted


def test_merge_partial_group_failure_moves_other_group_and_warns_by_name(client, dav, book):
    """Finding 4 (partial case): source is in two groups; one group's PUT
    fails (stale etag), the OTHER still gets moved, the source is still
    deleted, and the warning names the failed group."""
    a_href, _ = make(dav, book, "merge-3ga", "Part", "Keeper")
    b_href, _ = make(dav, book, "merge-3gb", "Part", "Duplicate")
    client.get("/refresh")

    resp = client.post("/groups", data={"name": "Stale Group"})
    stale_group_uid = resp.headers["location"].rsplit("/", 1)[-1]
    resp = client.post("/groups", data={"name": "Fine Group"})
    fine_group_uid = resp.headers["location"].rsplit("/", 1)[-1]
    client.post(f"/groups/{stale_group_uid}/members", data={"member_uid": "merge-3gb"})
    client.post(f"/groups/{fine_group_uid}/members", data={"member_uid": "merge-3gb"})

    data = _merge_form_data(client, "merge-3ga", "merge-3gb")

    # Make the stale group's cached etag go stale by editing it behind the
    # cache's back (mirrors the keeper-conflict test's technique) -- its PUT
    # during the merge will then be conditioned on a stale etag and 412.
    stale_href = f"{book.url.rstrip('/')}/{stale_group_uid}.vcf"
    fresh_raw, fresh_etag = dav.get(stale_href)
    dav.put(stale_href, fresh_raw.replace("Stale Group", "Stale Group Edited"), fresh_etag)

    resp = client.post("/contacts/merge-3ga/merge", data=data)
    assert resp.status_code == 303
    assert "merge_warn=" in resp.headers["location"]

    fine_href = f"{book.url.rstrip('/')}/{fine_group_uid}.vcf"
    fine_raw, _ = dav.get(fine_href)
    assert "urn:uuid:merge-3ga" in fine_raw  # the other group WAS moved
    assert "urn:uuid:merge-3gb" not in fine_raw

    stale_raw, _ = dav.get(stale_href)
    assert "urn:uuid:merge-3gb" in stale_raw  # stale group keeps the stale ref

    source_raw, _ = dav.get(b_href, missing_ok=True)
    assert source_raw is None  # source is still deleted regardless

    follow = client.get(resp.headers["location"])
    assert follow.status_code == 200
    assert "Stale Group" in follow.text  # warning names the failed group
