"""End-to-end tests for the web layer against a live local Radicale:
login, sync-on-login, list/search/detail, add/edit/delete write-through,
and conflict surfacing."""

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
        dav_url=dav_server["base_url"],
        secret_key="",  # empty -> app generates an ephemeral key
        db_path=str(tmp_path / "cache.db"),
        secure_cookies=False,
    )
    app = create_app(settings)
    return TestClient(app, follow_redirects=False)


def login(client):
    resp = client.post("/login", data={"username": "testuser", "password": "anything"})
    assert resp.status_code == 303, resp.text
    return client


CARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:web-1\r\n"
    "FN:Webb Tester\r\n"
    "N:Tester;Webb;;;\r\n"
    "EMAIL;TYPE=WORK:webb@example.net\r\n"
    "TEL;TYPE=CELL:+1 555 0107\r\n"
    "END:VCARD\r\n"
)


def test_wrong_password_rejected(client):
    resp = client.post("/login", data={"username": "testuser", "password": "wrong"})
    assert resp.status_code == 200
    assert "Login failed" in resp.text
    assert client.get("/").status_code == 303  # still not signed in -> redirect to login


def test_login_syncs_and_lists_contacts(client, dav, book):
    dav.create(book.url, "web-1", CARD)
    login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Webb Tester" in resp.text


def test_detail_page_has_interact_links(client, dav, book):
    href, _ = dav.create(book.url, "web-2", CARD.replace("web-1", "web-2"))
    login(client)
    resp = client.get("/contacts/web-2")
    assert resp.status_code == 200
    assert 'href="mailto:webb@example.net"' in resp.text
    assert 'href="tel:+15550107"' in resp.text
    assert 'href="sms:+15550107"' in resp.text
    dav.delete(href)


def test_search_fragment(client, dav, book):
    dav.create(book.url, "web-3", CARD.replace("web-1", "web-3").replace("Webb", "Zara"))
    login(client)
    resp = client.get("/search", params={"q": "zar"})
    assert "Zara Tester" in resp.text
    resp = client.get("/search", params={"q": "no-such-person-xyz"})
    assert "Zara" not in resp.text


def test_add_contact_writes_through_to_server(client, dav, book):
    login(client)
    resp = client.post(
        "/contacts",
        data={
            "given": "Nina", "family": "Novak", "org": "Initech", "note": "", "bday": "",
            "email_label": ["work"], "email_value": ["nina@initech.example"],
            "phone_label": ["cell"], "phone_value": ["+1 555 0142"],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
        },
    )
    assert resp.status_code == 303
    uid = resp.headers["location"].rsplit("/", 1)[-1]
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{uid}.vcf")
    assert "FN:Nina Novak" in raw
    assert "nina@initech.example" in raw


def test_edit_contact_writes_through_and_conflict_surfaces(client, dav, book):
    href, _ = dav.create(book.url, "web-4", CARD.replace("web-1", "web-4"))
    login(client)

    resp = client.post(
        "/contacts/web-4",
        data={
            "given": "Webster", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
        },
    )
    assert resp.status_code == 303
    raw, _ = dav.get(href)
    assert "FN:Webster Tester" in raw

    # Simulate another client editing behind our back, then submit a stale edit.
    fresh_raw, fresh_etag = dav.get(href)
    dav.put(href, fresh_raw.replace("Webster", "Behind-Your-Back"), fresh_etag)
    resp = client.post(
        "/contacts/web-4",
        data={
            "given": "Stale", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
        },
    )
    assert resp.status_code == 409
    assert "changed" in resp.text.lower()
    raw, _ = dav.get(href)
    assert "Behind-Your-Back" in raw  # never overwritten

    dav.delete(href)


def test_add_contact_with_address_writes_through_to_server(client, dav, book):
    login(client)
    resp = client.post(
        "/contacts",
        data={
            "given": "Ada", "family": "Byron", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
            "adr_label": ["home"], "adr_street": ["1 Main St"], "adr_city": ["Springfield"],
            "adr_region": ["IL"], "adr_code": ["62704"], "adr_country": ["USA"],
            "adr_pobox": [""], "adr_extended": [""],
        },
    )
    assert resp.status_code == 303
    uid = resp.headers["location"].rsplit("/", 1)[-1]
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{uid}.vcf")
    assert "ADR" in raw
    assert "1 Main St" in raw

    resp = client.get(f"/contacts/{uid}")
    assert "1 Main St, Springfield, IL, 62704, USA" in resp.text


def test_edit_contact_form_renders_existing_address_rows(client, dav, book):
    raw = CARD.replace("web-1", "web-adr-1").replace(
        "END:VCARD\r\n", "ADR;TYPE=HOME:;;1 Main St;Springfield;IL;62704;USA\r\nEND:VCARD\r\n"
    )
    dav.create(book.url, "web-adr-1", raw)
    login(client)
    resp = client.get("/contacts/web-adr-1/edit")
    assert resp.status_code == 200
    assert 'value="1 Main St"' in resp.text
    assert 'value="Springfield"' in resp.text
    assert 'value="IL"' in resp.text
    assert 'value="62704"' in resp.text
    assert 'value="USA"' in resp.text


def test_edit_contact_updates_address_and_preserves_pobox_extended(client, dav, book):
    raw = CARD.replace("web-1", "web-adr-2").replace(
        "END:VCARD\r\n",
        "ADR;TYPE=HOME:PO Box 1;Apt 2;1 Main St;Springfield;IL;62704;USA\r\nEND:VCARD\r\n",
    )
    href, _ = dav.create(book.url, "web-adr-2", raw)
    login(client)

    resp = client.post(
        "/contacts/web-adr-2",
        data={
            "given": "Webb", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
            "adr_label": ["home"], "adr_street": ["2 Elm St"], "adr_city": ["Springfield"],
            "adr_region": ["IL"], "adr_code": ["62704"], "adr_country": ["USA"],
            "adr_pobox": ["PO Box 1"], "adr_extended": ["Apt 2"],
        },
    )
    assert resp.status_code == 303
    updated, _ = dav.get(href)
    assert "2 Elm St" in updated
    assert "PO Box 1" in updated  # unedited component preserved
    assert "Apt 2" in updated


def test_edit_contact_removes_address_when_row_left_blank(client, dav, book):
    raw = CARD.replace("web-1", "web-adr-3").replace(
        "END:VCARD\r\n", "ADR;TYPE=HOME:;;1 Main St;Springfield;IL;62704;USA\r\nEND:VCARD\r\n"
    )
    href, _ = dav.create(book.url, "web-adr-3", raw)
    login(client)

    resp = client.post(
        "/contacts/web-adr-3",
        data={
            "given": "Webb", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
            "adr_label": [""], "adr_street": [""], "adr_city": [""],
            "adr_region": [""], "adr_code": [""], "adr_country": [""],
            "adr_pobox": [""], "adr_extended": [""],
        },
    )
    assert resp.status_code == 303
    updated, _ = dav.get(href)
    assert "ADR" not in updated


def test_pobox_address_is_visible_in_form_and_clearable(client, dav, book):
    # A pobox-only ADR must not render as an invisible-yet-undeletable row:
    # populated pobox/extended appear as visible inputs so they can be cleared.
    raw = CARD.replace("web-1", "web-adr-4").replace(
        "END:VCARD\r\n", "ADR;TYPE=HOME:PO Box 99;;;Springfield;IL;62704;USA\r\nEND:VCARD\r\n"
    )
    href, _ = dav.create(book.url, "web-adr-4", raw)
    login(client)

    form_page = client.get("/contacts/web-adr-4/edit").text
    assert 'name="adr_pobox" value="PO Box 99"' in form_page
    assert 'type="hidden" name="adr_pobox" value="PO Box 99"' not in form_page

    resp = client.post(
        "/contacts/web-adr-4",
        data={
            "given": "Webb", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
            "adr_label": [""], "adr_street": [""], "adr_city": [""],
            "adr_region": [""], "adr_code": [""], "adr_country": [""],
            "adr_pobox": [""], "adr_extended": [""],
        },
    )
    assert resp.status_code == 303
    updated, _ = dav.get(href)
    assert "ADR" not in updated


def test_relationships_link_to_matching_contact(client, dav, book):
    spouse = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:rel-spouse\r\n"
        "FN:James King\r\nN:King;James;;;\r\nEND:VCARD\r\n"
    )
    carol = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:rel-carol\r\n"
        "FN:Carol King\r\nN:King;Carol;;;\r\n"
        "item1.X-ABRELATEDNAMES:James King\r\n"
        "item1.X-ABLABEL:_$!<Spouse>!$_\r\n"
        "item2.X-ABRELATEDNAMES:Nobody Known\r\n"
        "item2.X-ABLABEL:Friend\r\n"
        "END:VCARD\r\n"
    )
    dav.create(book.url, "rel-spouse", spouse)
    dav.create(book.url, "rel-carol", carol)
    login(client)
    resp = client.get("/contacts/rel-carol")
    assert resp.status_code == 200
    assert 'href="/contacts/rel-spouse"' in resp.text  # match -> navigable link
    assert "Nobody Known" in resp.text  # no match -> plain text still shown


def test_delete_contact(client, dav, book):
    href, _ = dav.create(book.url, "web-5", CARD.replace("web-1", "web-5"))
    login(client)
    resp = client.post("/contacts/web-5/delete")
    assert resp.status_code == 303
    raw, _ = dav.get(href, missing_ok=True)
    assert raw is None


def test_delete_conflict_when_card_changed_elsewhere(client, dav, book):
    href, _ = dav.create(book.url, "web-6", CARD.replace("web-1", "web-6"))
    login(client)  # caches etag e1
    # Another client edits the card -> server etag advances past our cache.
    fresh_raw, fresh_etag = dav.get(href)
    dav.put(href, fresh_raw.replace("Webb", "Elsewhere"), fresh_etag)

    resp = client.post("/contacts/web-6/delete")
    assert resp.status_code == 409
    assert "not deleted" in resp.text.lower()
    # The card still exists on the server; the concurrent edit was not destroyed.
    raw, _ = dav.get(href, missing_ok=True)
    assert raw is not None and "Elsewhere" in raw
    dav.delete(href)


def test_birthdays_view_and_ics_feed(client, dav, book):
    bday_card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:bd-1\r\n"
        "FN:Birthday Person\r\nN:Person;Birthday;;;\r\n"
        "BDAY:1985-04-12\r\nEND:VCARD\r\n"
    )
    dav.create(book.url, "bd-1", bday_card)
    login(client)

    resp = client.get("/birthdays")
    assert resp.status_code == 200
    assert "Birthday Person" in resp.text
    assert "/feed/" in resp.text  # subscribe URL shown

    feed_path = resp.text.split('id="feed-url"')[1].split(">")[1].split("<")[0]
    feed_path = "/" + feed_path.split("/", 3)[-1] if feed_path.startswith("http") else feed_path

    # The feed works without a session (calendar apps have no cookie)...
    fresh = TestClient(client.app, follow_redirects=False)
    resp = fresh.get(feed_path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Birthday Person's birthday" in resp.text

    # ...but only with a valid token.
    assert fresh.get("/feed/not-a-real-token.ics").status_code == 404


def test_writes_target_configured_addressbook_not_just_first(dav_server, dav, tmp_path):
    import httpx

    # Create a second addressbook and target it explicitly.
    base = dav_server["base_url"]
    mkcol = (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        '<mkcol xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav"><set><prop>'
        "<resourcetype><collection/><CR:addressbook/></resourcetype>"
        "<displayname>Secondary</displayname></prop></set></mkcol>"
    )
    httpx.request(
        "MKCOL", f"{base}/testuser/secondary/", content=mkcol,
        headers={"Content-Type": "application/xml"}, auth=("testuser", "anything"),
    )
    settings = Settings(
        dav_url=base, secret_key="", db_path=str(tmp_path / "cache.db"),
        secure_cookies=False, write_addressbook="Secondary",
    )
    client = TestClient(create_app(settings), follow_redirects=False)
    login(client)
    resp = client.post(
        "/contacts",
        data={
            "given": "Sec", "family": "Ondary", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [], "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [], "related_label": [], "related_value": [],
        },
    )
    assert resp.status_code == 303
    uid = resp.headers["location"].rsplit("/", 1)[-1]
    (secondary,) = [b for b in dav.addressbooks() if b.name == "Secondary"]
    raw, _ = dav.get(f"{secondary.url.rstrip('/')}/{uid}.vcf")
    assert "FN:Sec Ondary" in raw


def test_photo_display_end_to_end(client, dav, book):
    import base64
    import textwrap

    photo_bytes = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes-for-live-photo-test" * 3 + b"\xff\xd9"
    photo_b64 = base64.b64encode(photo_bytes).decode()
    # Apple folds base64 PHOTO data at 75 octets, continuation lines starting
    # with a single space (RFC 6350 line folding).
    folded = "\r\n ".join(textwrap.wrap(photo_b64, 75))
    card = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "UID:web-photo\r\n"
        "FN:Photo Webb\r\n"
        "N:Webb;Photo;;;\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{folded}\r\n"
        "END:VCARD\r\n"
    )
    href, _ = dav.create(book.url, "web-photo", card)
    login(client)

    resp = client.get("/")
    assert resp.status_code == 200
    assert 'src="/contacts/web-photo/photo"' in resp.text

    resp = client.get("/contacts/web-photo/photo")
    assert resp.status_code == 200
    assert resp.content == photo_bytes
    assert resp.headers["content-type"] == "image/jpeg"

    etag = resp.headers["etag"]
    resp = client.get("/contacts/web-photo/photo", headers={"If-None-Match": etag})
    assert resp.status_code == 304

    dav.delete(href)


def test_upload_photo_on_create_writes_folded_photo_to_server(client, dav, book):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (800, 400), "red").save(buf, format="JPEG")

    login(client)
    resp = client.post(
        "/contacts",
        data={
            "given": "Piper", "family": "Foto", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
        },
        files={"photo": ("headshot.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert resp.status_code == 303, resp.text
    uid = resp.headers["location"].rsplit("/", 1)[-1]
    href = f"{book.url.rstrip('/')}/{uid}.vcf"
    raw, _ = dav.get(href)
    assert "PHOTO;ENCODING=b;TYPE=JPEG:" in raw
    # Our own splice folds at 75 octets before the PUT (unit-tested directly in
    # test_vcard_mapper.py); Radicale re-serializes stored cards and unfolds
    # long values back to a single line, so folding isn't observable here --
    # what matters end-to-end is that the photo round-trips intact.

    resp = client.get(f"/contacts/{uid}/photo")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))
    assert max(img.size) <= 512  # re-encoded/downscaled, not the raw 800x400 upload

    dav.delete(href)


def test_upload_photo_on_edit_replaces_existing_photo(client, dav, book):
    import base64
    import io

    from PIL import Image

    old_b64 = base64.b64encode(b"old-fake-photo-bytes").decode()
    card = CARD.replace("web-1", "web-photo-edit").replace(
        "END:VCARD\r\n", f"PHOTO;ENCODING=b;TYPE=JPEG:{old_b64}\r\nEND:VCARD\r\n"
    )
    href, _ = dav.create(book.url, "web-photo-edit", card)
    login(client)

    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "blue").save(buf, format="PNG")
    resp = client.post(
        "/contacts/web-photo-edit",
        data={
            "given": "Webb", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
        },
        files={"photo": ("new.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 303, resp.text
    updated, _ = dav.get(href)
    assert old_b64 not in updated
    assert "PHOTO;ENCODING=b;TYPE=JPEG:" in updated

    resp = client.get("/contacts/web-photo-edit/photo")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    dav.delete(href)


def test_remove_photo_checkbox_clears_photo_on_edit(client, dav, book):
    import base64

    old_b64 = base64.b64encode(b"old-fake-photo-bytes").decode()
    card = CARD.replace("web-1", "web-photo-rm").replace(
        "END:VCARD\r\n", f"PHOTO;ENCODING=b;TYPE=JPEG:{old_b64}\r\nEND:VCARD\r\n"
    )
    href, _ = dav.create(book.url, "web-photo-rm", card)
    login(client)

    resp = client.get("/contacts/web-photo-rm/edit")
    assert resp.status_code == 200
    assert 'name="photo_remove"' in resp.text

    resp = client.post(
        "/contacts/web-photo-rm",
        data={
            "given": "Webb", "family": "Tester", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
            "photo_remove": "1",
        },
    )
    assert resp.status_code == 303, resp.text
    updated, _ = dav.get(href)
    assert "PHOTO" not in updated

    resp = client.get("/contacts/web-photo-rm/photo")
    assert resp.status_code == 404

    dav.delete(href)


def test_logout(client, dav, book):
    login(client)
    resp = client.post("/logout")
    assert resp.status_code == 303
    assert client.get("/").status_code == 303
