"""Web layer: FastAPI app, server-rendered Jinja2 + HTMX."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import threading
from datetime import date
from itertools import zip_longest
from pathlib import Path
from urllib.parse import quote

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from peopledb.auth import SessionStore
from peopledb.birthdays import format_bday_date, ics_feed, next_birthday
from peopledb.config import Settings
from peopledb.dav import ConflictError, DavClient, DavError, UnreachableError
from peopledb.merge import (
    MergeChoice,
    build_merged_fields,
    drop_self_relations,
    rewrite_members,
    union_values,
)
from peopledb.photos import MAX_UPLOAD_BYTES, PhotoError, process_upload
from peopledb.quickparse import parse_quick_entry
from peopledb.store import ContactStore, StoredContact
from peopledb.sync import sync_user
from peopledb.vcard import (
    AddressParts,
    Contact,
    ContactFields,
    apply_edits,
    new_group,
    new_vcard,
    parse_vcard,
    remove_photo,
    set_group,
    set_photo,
)

log = logging.getLogger("peopledb")

_PKG_DIR = Path(__file__).parent
_SESSION_COOKIE = "peopledb_session"
_VIEW_COOKIE = "peopledb_view"
_VIEW_VALUES = ("list", "card")


def _view_from_cookie(request: Request) -> str:
    value = request.cookies.get(_VIEW_COOKIE, "")
    return value if value in _VIEW_VALUES else "list"


class _LoginRequired(Exception):
    pass


def _telify(number: str) -> str:
    return re.sub(r"[^\d+]", "", number)


def _maps_url(address: str) -> str:
    return f"https://maps.apple.com/?q={quote(address)}"


_SAFE_URL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "sms:")


def _safe_url(value: str) -> str:
    """Allow only known-safe schemes; neutralize javascript:/data: etc."""
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered.startswith(_SAFE_URL_SCHEMES):
        return stripped
    # Bare domains ("example.com") — assume https rather than treat as relative.
    # Reject anything with a scheme we didn't explicitly allow.
    if ":" not in stripped.split("/", 1)[0]:
        return "https://" + stripped
    return "#"


def _if_none_match(header_value: str, etag: str) -> bool:
    """Compare an If-None-Match header against etag, per RFC 7232: comma-separated
    list, weak (W/"...") validators compared by their underlying value."""
    def unwrap(tag: str) -> str:
        tag = tag.strip()
        if tag.startswith("W/"):
            tag = tag[2:]
        return tag.strip('"')

    target = unwrap(etag)
    return any(unwrap(candidate) == target for candidate in header_value.split(","))


def _fields_from_form(form) -> ContactFields:
    def pairs(prefix: str) -> list[tuple[str, str]]:
        labels = form.getlist(f"{prefix}_label")
        values = form.getlist(f"{prefix}_value")
        return [(l.strip(), v.strip()) for l, v in zip(labels, values) if v.strip()]

    def addresses() -> list[tuple[str, AddressParts]]:
        labels = form.getlist("adr_label")
        streets = form.getlist("adr_street")
        cities = form.getlist("adr_city")
        regions = form.getlist("adr_region")
        codes = form.getlist("adr_code")
        countries = form.getlist("adr_country")
        poboxes = form.getlist("adr_pobox")
        extendeds = form.getlist("adr_extended")
        result = []
        # zip_longest: a missing trailing field (hand-crafted POST, future
        # template drift) becomes an empty component instead of silently
        # truncating and misaligning every following row.
        for label, street, city, region, code, country, pobox, extended in zip_longest(
            labels, streets, cities, regions, codes, countries, poboxes, extendeds,
            fillvalue="",
        ):
            parts = AddressParts(
                street=street.strip(), city=city.strip(), region=region.strip(),
                code=code.strip(), country=country.strip(),
                pobox=pobox.strip(), extended=extended.strip(),
            )
            # Blank-row rule: a row counts as filled if any component is non-empty.
            if any((parts.street, parts.city, parts.region, parts.code,
                    parts.country, parts.pobox, parts.extended)):
                result.append((label.strip(), parts))
        return result

    return ContactFields(
        given=form.get("given", "").strip(),
        family=form.get("family", "").strip(),
        org=form.get("org", "").strip(),
        note=form.get("note", "").strip(),
        bday=form.get("bday", "").strip(),
        emails=pairs("email"),
        phones=pairs("phone"),
        urls=pairs("url"),
        addresses=addresses(),
        related=pairs("related"),
    )


def _indexed_pairs(form, prefix: str) -> list[tuple[str, str]]:
    """Read back a merge review screen's checked subset of a union: each row
    is rendered with a stable index i (`{prefix}_label_{i}` / `{prefix}_value_{i}`,
    hidden) plus a `{prefix}_keep` checkbox carrying that same index. Only
    checked rows come back in `getlist`, so this is index-driven rather than
    the label/value getlist zip `_fields_from_form.pairs` uses for the plain
    edit form (which has no per-row inclusion toggle)."""
    result = []
    for i in form.getlist(f"{prefix}_keep"):
        value = form.get(f"{prefix}_value_{i}", "").strip()
        if value:
            result.append((form.get(f"{prefix}_label_{i}", "").strip(), value))
    return result


def _indexed_addresses(form) -> list[tuple[str, AddressParts]]:
    result = []
    for i in form.getlist("adr_keep"):
        parts = AddressParts(
            street=form.get(f"adr_street_{i}", "").strip(),
            city=form.get(f"adr_city_{i}", "").strip(),
            region=form.get(f"adr_region_{i}", "").strip(),
            code=form.get(f"adr_code_{i}", "").strip(),
            country=form.get(f"adr_country_{i}", "").strip(),
            pobox=form.get(f"adr_pobox_{i}", "").strip(),
            extended=form.get(f"adr_extended_{i}", "").strip(),
        )
        if any((parts.street, parts.city, parts.region, parts.code,
                parts.country, parts.pobox, parts.extended)):
            result.append((form.get(f"adr_label_{i}", "").strip(), parts))
    return result


# Multipart framing (boundaries, field headers, the other form fields) adds
# some overhead on top of the raw file bytes; this margin keeps the guard from
# rejecting a legitimate near-the-cap upload while still catching anything
# wildly oversized before request.form() buffers/parses the whole body.
_UPLOAD_LENGTH_MARGIN_BYTES = 1 * 1024 * 1024


def _oversize_content_length(request: Request) -> bool:
    """Cheap pre-parse guard: reject on Content-Length alone when it's clearly
    over budget, so an enormous upload doesn't get fully parsed by
    request.form() just to be rejected afterwards by _apply_photo's read cap.
    A missing or unparsable header can't be trusted either way and is let
    through -- _apply_photo's cap still applies once the form is parsed."""
    header = request.headers.get("content-length", "")
    try:
        length = int(header)
    except ValueError:
        return False
    return length > MAX_UPLOAD_BYTES + _UPLOAD_LENGTH_MARGIN_BYTES


async def _apply_photo(raw: str, form) -> str:
    """Apply a photo upload/removal on top of an already-edited raw vCard, so
    it composes with apply_edits/new_vcard before the single DAV write (issue
    #11). No file and no removal flag -> raw returned untouched. Raises
    PhotoError for an oversize/wrong-type/corrupt upload; the caller re-renders
    the form with a banner rather than writing anything."""
    upload = form.get("photo")
    if upload is not None and getattr(upload, "filename", ""):
        # Cap the read itself (not just a post-hoc length check) so an
        # enormous upload doesn't get buffered into memory in full.
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if data:
            # process_upload is CPU-bound (Pillow decode/resize/re-encode) --
            # run it on a worker thread so a large photo doesn't stall the
            # event loop for every other concurrent request.
            b64, media_type = await asyncio.to_thread(process_upload, data)
            return set_photo(raw, b64, media_type)
    if form.get("photo_remove"):
        return remove_photo(raw)
    return raw


def create_app(settings: Settings) -> FastAPI:
    import asyncio
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Periodic background refresh for every signed-in user.
        async def refresher():
            while True:
                await asyncio.sleep(settings.sync_interval_seconds)
                for creds in app.state.sessions.credentials():
                    await asyncio.to_thread(try_sync, creds)

        task = asyncio.create_task(refresher())
        try:
            yield
        finally:
            task.cancel()
            for client in app.state.dav_clients.values():
                client.close()
            # Checkpoint + close this thread's store connection so a clean
            # shutdown leaves no stale -wal file.
            app.state.store.close()

    app = FastAPI(title="peopleDB", lifespan=lifespan)
    app.state.settings = settings
    app.state.dav_ok: dict[str, bool] = {}
    app.state.sessions = SessionStore(
        settings.secret_key or Fernet.generate_key(),
        idle_seconds=settings.session_idle_seconds,
    )
    app.state.store = ContactStore(settings.db_path)
    # One DavClient (httpx connection pool) per user, reused across requests and
    # closed at shutdown — avoids a fresh TLS handshake and a leaked socket pool
    # on every request.
    app.state.dav_clients: dict[tuple[str, str], DavClient] = {}
    app.state.dav_clients_lock = threading.Lock()
    # Per-user locks serializing cache-mutating sequences (sync batch, write-back
    # refresh, delete) so a concurrent sync_user() and a write-triggered re-GET
    # for the same user never interleave (issue #6 follow-up: offloading DAV
    # calls to threads exposed same-user races the blocked event loop used to
    # mask). The dict itself is guarded by user_locks_lock; each Lock inside runs
    # only on worker threads (via asyncio.to_thread), never held across an await.
    app.state.user_locks: dict[str, threading.Lock] = {}
    app.state.user_locks_lock = threading.Lock()

    templates = Jinja2Templates(directory=_PKG_DIR / "templates")
    templates.env.filters["telify"] = _telify
    templates.env.filters["maps_url"] = _maps_url
    templates.env.filters["safe_url"] = _safe_url
    templates.env.filters["bday_date"] = format_bday_date
    app.mount("/static", StaticFiles(directory=_PKG_DIR / "static"), name="static")

    store: ContactStore = app.state.store

    # -- auth plumbing -------------------------------------------------------

    def current_session(request: Request) -> tuple[str, str]:
        sid = request.cookies.get(_SESSION_COOKIE, "")
        creds = app.state.sessions.get(sid)
        if creds is None:
            raise _LoginRequired()
        return creds

    def lock_for(user: str) -> threading.Lock:
        with app.state.user_locks_lock:
            lock = app.state.user_locks.get(user)
            if lock is None:
                lock = threading.Lock()
                app.state.user_locks[user] = lock
            return lock

    def dav_for(creds: tuple[str, str]) -> DavClient:
        with app.state.dav_clients_lock:
            client = app.state.dav_clients.get(creds)
            if client is None:
                client = DavClient(settings.dav_url, creds[0], creds[1])
                app.state.dav_clients[creds] = client
            return client

    def try_sync(creds: tuple[str, str]) -> None:
        """Refresh a user's cache; on failure mark them offline, never raise.
        Runs on a worker thread (via to_thread); the user lock serializes this
        against any other cache-mutating sequence for the same user (another
        sync_user, or a write-triggered re-GET+upsert)."""
        user = creds[0]
        try:
            with lock_for(user):
                sync_user(dav_for(creds), store, user)
            app.state.dav_ok[user] = True
        except (UnreachableError, DavError) as exc:
            log.warning("sync failed for %s: %s", user, exc)
            app.state.dav_ok[user] = False

    async def cache_after_write(
        user: str, dav: DavClient, addressbook: str, href: str, sent_raw: str, etag: str
    ) -> None:
        """Cache a just-written card. Prefer the server's normalized copy, but a
        failed re-fetch must NOT masquerade as a failed write — the PUT/POST
        already succeeded, so fall back to what we sent with the write's etag.

        The re-fetch + store.upsert run together as one synchronous unit on a
        worker thread, holding the user lock, so a concurrently running sync
        batch for the same user can't clobber this write (or vice versa)."""

        def fetch_and_store() -> None:
            nonlocal sent_raw, etag
            with lock_for(user):
                try:
                    fetched_raw, fetched_etag = dav.get(href)
                    sent_raw, etag = fetched_raw or sent_raw, fetched_etag or etag
                except DavError as exc:
                    log.warning(
                        "post-write refetch failed for %s (write still applied): %s", href, exc
                    )
                store.upsert(user, addressbook, href, etag or "", sent_raw)

        await asyncio.to_thread(fetch_and_store)

    async def locked_delete(user: str, href: str) -> None:
        """Remove a just-deleted card from the cache under the user lock, so it
        can't race a concurrently running sync batch for the same user."""

        def delete_locked() -> None:
            with lock_for(user):
                store.delete(user, href)

        await asyncio.to_thread(delete_locked)

    @app.exception_handler(_LoginRequired)
    async def _redirect_to_login(request: Request, exc: _LoginRequired):
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(UnreachableError)
    async def _server_unreachable(request: Request, exc: UnreachableError):
        # Writes fail loudly; nothing is queued (spec: never queue silently).
        return HTMLResponse(
            "<h1>CardDAV server unreachable</h1>"
            "<p>Your change was <strong>not saved</strong>. The server is the "
            "store of record and peopleDB never queues writes. "
            'Try again once it is back. <a href="/">Back to contacts</a></p>',
            status_code=503,
        )

    @app.exception_handler(DavError)
    async def _dav_error(request: Request, exc: DavError):
        # Any other CardDAV failure: fail loudly, don't 500 with a stack trace.
        log.warning("DAV error on %s: %s", request.url.path, exc)
        return HTMLResponse(
            "<h1>CardDAV request failed</h1>"
            "<p>Your change was <strong>not saved</strong>. "
            'Please try again. <a href="/">Back to contacts</a></p>',
            status_code=502,
        )

    Creds = Depends(current_session)

    def render(name: str, request: Request, status_code: int = 200, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name=name, context=ctx, status_code=status_code
        )

    # -- auth routes ----------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        return render("login.html", request)

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        form = await request.form()
        username = form.get("username", "").strip()
        password = form.get("password", "")
        # Throwaway client just for credential validation; close it so each
        # login attempt doesn't leak an httpx connection pool.
        dav = DavClient(settings.dav_url, username, password)
        try:
            ok = await asyncio.to_thread(dav.validate_credentials)
        except UnreachableError:
            return render("login.html", request, error="CardDAV server unreachable.")
        finally:
            await asyncio.to_thread(dav.close)
        if not ok:
            return render("login.html", request, error="Login failed: check username and password.")
        await asyncio.to_thread(try_sync, (username, password))
        sid = app.state.sessions.create(username, password)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            _SESSION_COOKIE, sid,
            httponly=True, samesite="lax", secure=settings.secure_cookies,
        )
        return resp

    @app.post("/logout")
    async def logout(request: Request):
        sid = request.cookies.get(_SESSION_COOKIE, "")
        app.state.sessions.drop(sid)
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(_SESSION_COOKIE)
        return resp

    # -- contact list / search -------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, group: str = "", creds: tuple[str, str] = Creds):
        user = creds[0]
        contacts = store.list_contacts(user)
        active_group = None
        if group:
            active_group = store.get_by_uid(user, group)
            if active_group:
                members = set(active_group.contact.member_uids)
                contacts = [c for c in contacts if c.contact.uid in members]
        return render(
            "index.html", request,
            contacts=contacts,
            groups=store.list_groups(user),
            active_group=active_group,
            broken=store.list_broken(user),
            offline=not app.state.dav_ok.get(user, True),
            view=_view_from_cookie(request),
        )

    @app.get("/refresh")
    async def refresh(request: Request, creds: tuple[str, str] = Creds):
        await asyncio.to_thread(try_sync, creds)
        return RedirectResponse("/", status_code=303)

    @app.get("/search", response_class=HTMLResponse)
    async def search(request: Request, q: str = "", creds: tuple[str, str] = Creds):
        user = creds[0]
        contacts = store.search(user, q) if q.strip() else store.list_contacts(user)
        return render("_contacts.html", request, contacts=contacts, view=_view_from_cookie(request))

    @app.post("/view")
    async def set_view(request: Request):
        form = await request.form()
        value = form.get("view", "")
        if value not in _VIEW_VALUES:
            value = "list"
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            _VIEW_COOKIE, value,
            max_age=60 * 60 * 24 * 365, samesite="lax", secure=settings.secure_cookies,
        )
        return resp

    # -- add / edit / delete ----------------------------------------------------

    @app.get("/contacts/new", response_class=HTMLResponse)
    async def new_contact_form(request: Request, q: str = "", creds: tuple[str, str] = Creds):
        user = creds[0]
        contact = None
        parsed_groups: list[str] = []
        if q.strip():
            fields = parse_quick_entry(q)
            contact = Contact(
                given=fields.given, family=fields.family, org=fields.org,
                note=fields.note, bday=fields.bday, emails=fields.emails,
                phones=fields.phones, urls=fields.urls, related=fields.related,
            )
            parsed_groups = fields.groups
        # Group assignment isn't a Contact/ContactFields property -- membership
        # lives on the group card, not the contact's own vCard (ADR-0002) -- so
        # the checkbox data is passed as separate render kwargs, not through
        # Contact. Always list the existing groups (even with no `q`) so the
        # checkboxes render on a plain "New contact" too.
        existing = store.list_groups(user)
        matched_lower = {n.lower() for n in parsed_groups}
        groups = [
            {
                "uid": g.contact.uid,
                "name": g.contact.formatted_name,
                "checked": g.contact.formatted_name.lower() in matched_lower,
            }
            for g in existing
        ]
        existing_names_lower = {g.contact.formatted_name.lower() for g in existing}
        unmatched_groups = [n for n in parsed_groups if n.lower() not in existing_names_lower]
        return render(
            "form.html", request, contact=contact, action="/contacts", is_edit=False,
            groups=groups, unmatched_groups=unmatched_groups,
        )

    @app.post("/contacts")
    async def create_contact(request: Request, creds: tuple[str, str] = Creds):
        user = creds[0]
        dav = dav_for(creds)
        if _oversize_content_length(request):
            return render(
                "form.html", request, status_code=413,
                contact=None, action="/contacts", is_edit=False,
                conflict="Photo is too large (max 10 MB).",
            )
        form = await request.form()
        fields = _fields_from_form(form)
        raw = new_vcard(fields)
        try:
            raw = await _apply_photo(raw, form)
        except PhotoError as exc:
            return render(
                "form.html", request, status_code=400,
                contact=parse_vcard(raw), action="/contacts", is_edit=False,
                conflict=str(exc),
            )
        uid = parse_vcard(raw).uid
        book = await _write_book(dav)
        href, etag = await asyncio.to_thread(dav.create, book.url, uid, raw)
        await cache_after_write(user, dav, book.url, href, raw, etag)

        # #24: assign the new contact to any checked groups. Group membership
        # is not on the contact's own vCard -- it's a separate write to each
        # group card's member list, one PUT per group, sequentially.
        failed_group_names: list[str] = []
        for group_uid in form.getlist("group_uid"):
            if not group_uid:
                continue
            ok, name = await _add_member_to_group(user, dav, group_uid, uid)
            if not ok:
                failed_group_names.append(name)

        if failed_group_names:
            # The contact IS created -- don't mask the partial failure by
            # silently dropping it. Surface the group name(s) that didn't
            # take so the user can retry from the group page.
            warn = quote(", ".join(failed_group_names))
            return RedirectResponse(f"/contacts/{uid}?group_warn={warn}", status_code=303)
        return RedirectResponse(f"/contacts/{uid}", status_code=303)

    @app.get("/contacts/{uid}", response_class=HTMLResponse)
    async def contact_detail(
        request: Request, uid: str, group_warn: str = "", merge_warn: str = "",
        creds: tuple[str, str] = Creds,
    ):
        user = creds[0]
        rec = _get_or_404(user, uid)
        # Resolve related names to contacts so relationships are navigable.
        # X-ABRELATEDNAMES carries no UID in vCard 3.0, so it's matched by
        # display name -- which isn't unique. Only link when exactly one
        # contact has that name; otherwise leave it as plain text rather
        # than risk linking to the wrong person.
        other_contacts = store.list_contacts(user)
        uids_by_name: dict[str, list[str]] = {}
        for r in other_contacts:
            uids_by_name.setdefault(r.contact.formatted_name, []).append(r.contact.uid)
        related_uids = {
            name: uids[0]
            for _, name in rec.contact.related
            if len(uids := uids_by_name.get(name, [])) == 1
        }
        return render(
            "detail.html", request, rec=rec, contact=rec.contact, related_uids=related_uids,
            group_warn=group_warn, merge_warn=merge_warn,
        )

    @app.get("/contacts/{uid}/photo")
    async def contact_photo(request: Request, uid: str, creds: tuple[str, str] = Creds):
        rec = _get_or_404(creds[0], uid)
        if not rec.contact.photo_b64:
            raise HTTPException(status_code=404, detail="No photo")
        etag = rec.etag
        headers = {"Cache-Control": "private, max-age=3600"}
        if etag:
            headers["ETag"] = etag
        if etag and _if_none_match(request.headers.get("if-none-match", ""), etag):
            return Response(status_code=304, headers=headers)
        return Response(
            content=base64.b64decode(rec.contact.photo_b64),
            media_type=rec.contact.photo_media_type,
            headers=headers,
        )

    @app.get("/contacts/{uid}/edit", response_class=HTMLResponse)
    async def edit_contact_form(request: Request, uid: str, creds: tuple[str, str] = Creds):
        rec = _get_or_404(creds[0], uid)
        return render(
            "form.html", request,
            contact=rec.contact, etag=rec.etag, action=f"/contacts/{uid}", is_edit=True,
        )

    @app.post("/contacts/{uid}")
    async def update_contact(request: Request, uid: str, creds: tuple[str, str] = Creds):
        user = creds[0]
        dav = dav_for(creds)
        rec = _get_or_404(user, uid)
        if _oversize_content_length(request):
            return render(
                "form.html", request, status_code=413,
                contact=rec.contact, etag=rec.etag, action=f"/contacts/{uid}",
                is_edit=True, conflict="Photo is too large (max 10 MB).",
            )
        form = await request.form()
        fields = _fields_from_form(form)
        edited = apply_edits(rec.raw, fields)
        try:
            edited = await _apply_photo(edited, form)
        except PhotoError as exc:
            return render(
                "form.html", request, status_code=400,
                contact=parse_vcard(edited), etag=rec.etag, action=f"/contacts/{uid}",
                is_edit=True, conflict=str(exc),
            )
        # Guard against the card changing while the form was open: use the etag
        # the form was rendered with (falls back to the cache's for direct POSTs).
        if_match = form.get("etag") or rec.etag
        try:
            new_etag = await asyncio.to_thread(dav.put, rec.href, edited, if_match)
        except ConflictError:
            await cache_after_write(user, dav, rec.addressbook, rec.href, rec.raw, "")
            fresh = store.get_by_uid(user, uid)
            return render(
                "form.html", request, status_code=409,
                contact=fresh.contact if fresh else rec.contact,
                etag=fresh.etag if fresh else "",
                action=f"/contacts/{uid}", is_edit=True,
                conflict="This card changed on the server while you were editing. "
                         "Your changes were NOT saved; the form now shows the latest version.",
            )
        await cache_after_write(user, dav, rec.addressbook, rec.href, edited, new_etag)
        return RedirectResponse(f"/contacts/{uid}", status_code=303)

    @app.post("/contacts/{uid}/delete")
    async def delete_contact(request: Request, uid: str, creds: tuple[str, str] = Creds):
        user = creds[0]
        dav = dav_for(creds)
        rec = _get_or_404(user, uid)
        try:
            await asyncio.to_thread(dav.delete, rec.href, rec.etag)
        except ConflictError:
            # Someone changed the card since our cache; re-sync and surface it.
            await cache_after_write(user, dav, rec.addressbook, rec.href, rec.raw, "")
            return render(
                "detail.html", request, status_code=409,
                rec=rec, contact=rec.contact, related_uids={},
                conflict="This contact changed on the server, so it was NOT deleted. "
                         "Review the latest version and retry if you still want to delete it.",
            )
        await locked_delete(user, rec.href)
        return RedirectResponse("/", status_code=303)

    # -- merge (#28) ------------------------------------------------------------

    def _merge_validation_error(
        a: StoredContact, b: StoredContact | None, uid: str, with_uid: str
    ) -> str:
        """Reject a merge attempt with a clear message rather than a 500:
        self-merge and either side being a group are both out of scope
        (spec: non-group contacts only, pick-two only)."""
        if not with_uid:
            return "Pick a contact to merge with."
        if uid == with_uid:
            return "Can't merge a contact with itself."
        if b is None:
            return "No such contact to merge with."
        if a.contact.is_group or b.contact.is_group:
            return "Groups can't be merged."
        return ""

    def _merge_context(a: StoredContact, b: StoredContact, keeper_uid: str = "") -> dict:
        """Review-screen context: the full keeper-first union of every
        multi-valued field (self-relation collapsed for `related`), each row
        indexed so the template can round-trip it through `_indexed_pairs`/
        `_indexed_addresses` on submit."""
        ac, bc = a.contact, b.contact
        related_union = drop_self_relations(
            union_values(ac.related, bc.related),
            ac.uid, bc.uid, ac.formatted_name, bc.formatted_name,
        )
        return {
            "contact_a": a,
            "contact_b": b,
            "keeper_uid": keeper_uid or ac.uid,
            "emails": list(enumerate(union_values(ac.emails, bc.emails))),
            "phones": list(enumerate(union_values(ac.phones, bc.phones))),
            "urls": list(enumerate(union_values(ac.urls, bc.urls))),
            "addresses": list(enumerate(union_values(ac.addresses, bc.addresses))),
            "related": list(enumerate(related_union)),
        }

    @app.get("/contacts/{uid}/merge/search", response_class=HTMLResponse)
    async def merge_search(request: Request, uid: str, q: str = "", creds: tuple[str, str] = Creds):
        # Merge-flavored search (#28 finding 3): mirrors /search's
        # empty-query-lists-all behavior, but excludes self and groups (not
        # mergeable) and links each result to the merge REVIEW screen, not
        # detail -- reusing _contacts.html verbatim isn't possible since its
        # links target detail.
        user = creds[0]
        # #31: a group can't be the merge *primary* either (the merge action is
        # rejected downstream and the picker is hidden on group pages since
        # #30) -- so offer no candidates rather than a populated list.
        primary = store.get_by_uid(user, uid)
        if primary is not None and primary.contact.is_group:
            return render("_merge_candidates.html", request, uid=uid, candidates=[])
        contacts = store.search(user, q) if q.strip() else store.list_contacts(user)
        candidates = [c for c in contacts if c.contact.uid != uid and not c.contact.is_group]
        return render("_merge_candidates.html", request, uid=uid, candidates=candidates)

    @app.get("/contacts/{uid}/merge", response_class=HTMLResponse)
    async def merge_form(request: Request, uid: str, creds: tuple[str, str] = Creds):
        user = creds[0]
        a = _get_or_404(user, uid)
        with_uid = request.query_params.get("with", "").strip()
        b = store.get_by_uid(user, with_uid) if with_uid else None
        error = _merge_validation_error(a, b, uid, with_uid)
        if error:
            return render(
                "detail.html", request, status_code=400,
                rec=a, contact=a.contact, related_uids={}, conflict=error,
            )
        return render("merge.html", request, **_merge_context(a, b))

    @app.post("/contacts/{uid}/merge")
    async def execute_merge(request: Request, uid: str, creds: tuple[str, str] = Creds):
        user = creds[0]
        dav = dav_for(creds)
        form = await request.form()
        with_uid = form.get("with", "").strip()
        a = _get_or_404(user, uid)
        b = store.get_by_uid(user, with_uid) if with_uid else None
        error = _merge_validation_error(a, b, uid, with_uid)
        if error:
            return render(
                "detail.html", request, status_code=400,
                rec=a, contact=a.contact, related_uids={}, conflict=error,
            )
        keeper_uid = form.get("keeper_uid", "").strip()
        # keeper_uid must be one of the two cards being merged -- anything
        # else (tampered form, stale link) is rejected rather than silently
        # defaulted, closing the tampering gap flagged in review.
        if keeper_uid not in (a.contact.uid, b.contact.uid):
            return render(
                "detail.html", request, status_code=400,
                rec=a, contact=a.contact, related_uids={},
                conflict="Invalid keeper selection for merge.",
            )
        keeper, source = (b, a) if keeper_uid == b.contact.uid else (a, b)

        # Field VALUE choices are resolved from contact_a/contact_b directly
        # (independent of which card is the keeper) -- the keeper only
        # decides which card's UID/href/raw base and unknown props survive.
        # Conflating the two inverted every field on a keeper-flip (#28
        # finding 1): apply_edits overwrites all managed props from the built
        # ContactFields regardless of whose raw is the base, so field values
        # must not depend on keeper identity.
        default_choice = "a" if keeper_uid == a.contact.uid else "b"
        choice = MergeChoice(
            given=form.get("name_choice", default_choice),
            family=form.get("name_choice", default_choice),
            org=form.get("org_choice", default_choice),
            note=form.get("note_choice", default_choice),
            bday=form.get("bday_choice", default_choice),
        )
        fields = build_merged_fields(
            keeper.contact, source.contact, choice,
            contact_a=a.contact, contact_b=b.contact,
            emails=_indexed_pairs(form, "email"),
            phones=_indexed_pairs(form, "phone"),
            urls=_indexed_pairs(form, "url"),
            addresses=_indexed_addresses(form),
            related=_indexed_pairs(form, "related"),
        )
        merged_raw = apply_edits(keeper.raw, fields)
        photo_choice = form.get("photo_choice", default_choice)
        if photo_choice == "remove":
            merged_raw = remove_photo(merged_raw)
        photo_warning = ""
        # The review screen only renders a photo choice at all when either
        # card actually has a photo -- otherwise "photo_choice" is absent
        # from the form and this falls back to default_choice ("a"/"b" per
        # keeper side), which is NOT a real user selection and must not warn.
        photo_offered = a.contact.has_photo or b.contact.has_photo
        if photo_offered and photo_choice in ("a", "b"):
            chosen = a.contact if photo_choice == "a" else b.contact
            # Only overwrite when the picked card actually has an embedded
            # base64 photo -- a URI-only PHOTO (photo_uri set, photo_b64
            # empty) still trips has_photo, and set_photo(raw, "", ...) would
            # emit a malformed empty PHOTO line, clobbering the keeper's good
            # photo (#28 finding 2). Otherwise the keeper's own PHOTO stays
            # untouched -- apply_edits never rewrites it. Surface that the
            # choice didn't silently take rather than dropping it (audit
            # finding 1) -- the keeper's own photo (if any) is untouched.
            if chosen.photo_b64:
                merged_raw = set_photo(merged_raw, chosen.photo_b64, chosen.photo_media_type)
            else:
                photo_warning = "photo not merged (selected photo is a link, not embedded)"

        # Step 1 (ADR-0006): keeper PUT first, etag-conditional. A conflict here
        # aborts the ENTIRE merge before any other write -- zero server changes.
        try:
            new_etag = await asyncio.to_thread(dav.put, keeper.href, merged_raw, keeper.etag)
        except ConflictError:
            await cache_after_write(user, dav, keeper.addressbook, keeper.href, keeper.raw, "")
            fresh = store.get_by_uid(user, keeper.contact.uid)
            return render(
                "detail.html", request, status_code=409,
                rec=fresh or keeper, contact=(fresh or keeper).contact, related_uids={},
                conflict="The keeper contact changed on the server while merging. "
                         "Nothing was written; review the latest version and retry.",
            )
        await cache_after_write(user, dav, keeper.addressbook, keeper.href, merged_raw, new_etag)

        # Step 2: group moves, source -> keeper, in every group that has the
        # source as a member. Failures warn but never abort or roll back the
        # keeper write above -- surfaced via ?merge_warn= (this flow's own
        # channel, distinct from #24's ?group_warn=; see below).
        warnings: list[str] = [photo_warning] if photo_warning else []
        for grp in store.list_groups(user):
            if source.contact.uid not in grp.contact.member_uids:
                continue
            new_members = rewrite_members(
                grp.contact.member_uids, source.contact.uid, keeper.contact.uid
            )
            edited_group = set_group(grp.raw, grp.contact.formatted_name, new_members)
            try:
                g_etag = await asyncio.to_thread(dav.put, grp.href, edited_group, grp.etag)
            except DavError:
                warnings.append(f"group {grp.contact.formatted_name!r} not updated")
                continue
            await cache_after_write(user, dav, grp.addressbook, grp.href, edited_group, g_etag)

        # Step 3 (ADR-0006): source DELETE last. A failure here warns but the
        # keeper write and any completed group moves stand -- the source
        # survives as a harmless leftover duplicate to retry.
        try:
            await asyncio.to_thread(dav.delete, source.href, source.etag)
        except DavError:
            warnings.append(f"{source.contact.formatted_name!r} could not be deleted")
        else:
            await locked_delete(user, source.href)

        if warnings:
            # Merge's OWN warning channel (?merge_warn=), distinct from #24's
            # ?group_warn= -- detail.html renders a #24-specific sentence for
            # group_warn ("...could not be added to: X") that reads as
            # nonsense for merge's warning strings (finding 2). The strings
            # here are already full clauses, so they're joined readably.
            warn = quote("; ".join(warnings))
            return RedirectResponse(
                f"/contacts/{keeper.contact.uid}?merge_warn={warn}", status_code=303
            )
        return RedirectResponse(f"/contacts/{keeper.contact.uid}", status_code=303)

    # -- birthdays ------------------------------------------------------------

    @app.get("/birthdays", response_class=HTMLResponse)
    async def birthdays_view(request: Request, creds: tuple[str, str] = Creds):
        user = creds[0]
        today = date.today()
        upcoming = []
        for rec in store.contacts_with_bday(user):
            result = next_birthday(rec.contact.bday, today)
            if result:
                upcoming.append((result[0], result[1], rec))
        upcoming.sort(key=lambda item: item[0])
        # ensure_feed_token writes on first use; keep it off the event loop
        # like every other store write.
        feed_token = await asyncio.to_thread(store.ensure_feed_token, user)
        feed_url = f"/feed/{feed_token}.ics"
        return render(
            "birthdays.html", request, upcoming=upcoming, today=today, feed_url=feed_url
        )

    @app.get("/feed/{token}.ics")
    async def birthday_feed(token: str):
        user = store.user_for_feed_token(token)
        if user is None:
            raise HTTPException(status_code=404)
        people = [
            (rec.contact.formatted_name, rec.contact.bday)
            for rec in store.contacts_with_bday(user)
        ]
        return Response(content=ics_feed(people), media_type="text/calendar; charset=utf-8")

    # -- groups --------------------------------------------------------------

    @app.post("/groups")
    async def create_group(request: Request, creds: tuple[str, str] = Creds):
        user = creds[0]
        dav = dav_for(creds)
        form = await request.form()
        name = form.get("name", "").strip()
        if not name:
            return RedirectResponse("/", status_code=303)
        raw = new_group(name)
        uid = parse_vcard(raw).uid
        book = await _write_book(dav)
        href, etag = await asyncio.to_thread(dav.create, book.url, uid, raw)
        await cache_after_write(user, dav, book.url, href, raw, etag)
        return RedirectResponse(f"/groups/{uid}", status_code=303)

    @app.get("/groups/{uid}", response_class=HTMLResponse)
    async def group_page(request: Request, uid: str, creds: tuple[str, str] = Creds):
        return _render_group(request, creds[0], uid)

    @app.post("/groups/{uid}")
    async def rename_group(request: Request, uid: str, creds: tuple[str, str] = Creds):
        form = await request.form()
        name = form.get("name", "").strip()
        return await _mutate_group(request, creds, uid, name=name or None)

    @app.post("/groups/{uid}/members")
    async def add_member(request: Request, uid: str, creds: tuple[str, str] = Creds):
        form = await request.form()
        member = form.get("member_uid", "").strip()
        return await _mutate_group(request, creds, uid, add=member or None)

    @app.post("/groups/{uid}/members/{member_uid}/remove")
    async def remove_member(
        request: Request, uid: str, member_uid: str, creds: tuple[str, str] = Creds
    ):
        return await _mutate_group(request, creds, uid, remove=member_uid)

    @app.post("/groups/{uid}/delete")
    async def delete_group(request: Request, uid: str, creds: tuple[str, str] = Creds):
        user = creds[0]
        dav = dav_for(creds)
        rec = _get_or_404(user, uid)
        try:
            await asyncio.to_thread(dav.delete, rec.href, rec.etag)
        except ConflictError:
            await cache_after_write(user, dav, rec.addressbook, rec.href, rec.raw, "")
            return _render_group(
                request, user, uid, status_code=409,
                conflict="This group changed on the server, so it was NOT deleted. "
                         "Review the latest version and retry.",
            )
        await locked_delete(user, rec.href)
        return RedirectResponse("/", status_code=303)

    def _render_group(
        request: Request, user: str, uid: str, status_code: int = 200, conflict: str = ""
    ) -> HTMLResponse:
        rec = _get_or_404(user, uid)
        members = set(rec.contact.member_uids)
        contacts = store.list_contacts(user)
        return render(
            "group.html", request, status_code=status_code,
            rec=rec, group=rec.contact, conflict=conflict,
            member_contacts=[c for c in contacts if c.contact.uid in members],
            candidates=[c for c in contacts if c.contact.uid not in members],
        )

    async def _mutate_group(
        request: Request, creds: tuple[str, str], uid: str,
        name: str | None = None, add: str | None = None, remove: str | None = None,
    ):
        user = creds[0]
        dav = dav_for(creds)
        rec = _get_or_404(user, uid)
        members = list(rec.contact.member_uids)
        if add and add not in members:
            members.append(add)
        if remove and remove in members:
            members.remove(remove)
        edited = set_group(rec.raw, name or rec.contact.formatted_name, members)
        try:
            new_etag = await asyncio.to_thread(dav.put, rec.href, edited, rec.etag)
        except ConflictError:
            await cache_after_write(user, dav, rec.addressbook, rec.href, rec.raw, "")
            return _render_group(
                request, user, uid, status_code=409,
                conflict="This group changed on the server; your change was NOT saved. "
                         "Review the latest version below and retry.",
            )
        await cache_after_write(user, dav, rec.addressbook, rec.href, edited, new_etag)
        return RedirectResponse(f"/groups/{uid}", status_code=303)

    async def _add_member_to_group(
        user: str, dav: DavClient, group_uid: str, member_uid: str
    ) -> tuple[bool, str]:
        """Add `member_uid` to group `group_uid`'s member list -- same write
        path as `_mutate_group` (load, append, `set_group`, etag-conditional
        PUT, `cache_after_write`), used by `create_contact`'s post-create
        group-assignment loop. On a 409 conflict, refetch the group and retry
        ONCE; on any OTHER DAV failure (500/403 -> DavError, transport drop ->
        UnreachableError) -- or a `group_uid` that no longer resolves to a
        group -- give up on that group WITHOUT raising.

        This must never propagate: the contact is already created and cached by
        the time this runs, so a raised error would hit the app-level handler
        and render "not saved", masking the successful create (the user retries
        and makes a duplicate contact). The caller surfaces the failed name via
        `group_warn` instead.

        Returns (True, group_name) on success, (False, name-or-uid) if the
        group couldn't be written.
        """
        rec = store.get_by_uid(user, group_uid)
        # A group_uid that no longer resolves to a group -- deleted between the
        # form GET and this POST, or a stale/tampered value. Don't 404 the whole
        # request (the contact is already created), and never set_group() a
        # non-group card (that would rewrite a normal contact INTO a group).
        # Report it as a failed assignment so the caller surfaces it.
        if rec is None or not rec.contact.is_group:
            return False, group_uid
        name = rec.contact.formatted_name
        for _attempt in range(2):
            members = list(rec.contact.member_uids)
            if member_uid not in members:
                members.append(member_uid)
            edited = set_group(rec.raw, name, members)
            try:
                new_etag = await asyncio.to_thread(dav.put, rec.href, edited, rec.etag)
            except ConflictError:
                await cache_after_write(user, dav, rec.addressbook, rec.href, rec.raw, "")
                rec = store.get_by_uid(user, group_uid)
                if rec is None or not rec.contact.is_group:
                    return False, group_uid
                name = rec.contact.formatted_name
                continue
            except DavError:
                # Any non-409 server/transport failure on the group PUT
                # (DavError covers plain DavError + UnreachableError). Don't let
                # it propagate past the already-created contact -- report the
                # failed assignment so the caller surfaces it via group_warn.
                return False, name
            await cache_after_write(user, dav, rec.addressbook, rec.href, edited, new_etag)
            return True, name
        return False, name

    # -- helpers -----------------------------------------------------------------

    async def _write_book(dav: DavClient):
        """The addressbook new cards go into: prefer the configured name/path
        segment, else the first discovered. Deterministic, never arbitrary."""
        books = await asyncio.to_thread(dav.addressbooks)
        if not books:
            raise DavError("no addressbooks found for user")
        want = settings.write_addressbook.strip().lower()
        if want:
            for book in books:
                if book.name.lower() == want or f"/{want}/" in book.url.lower():
                    return book
        return books[0]

    def _get_or_404(user: str, uid: str) -> StoredContact:
        rec = store.get_by_uid(user, uid)
        if rec is None:
            raise HTTPException(status_code=404, detail="No such contact")
        return rec

    return app


def app_from_env() -> FastAPI:
    return create_app(Settings.from_env())


def main() -> None:
    import uvicorn

    uvicorn.run(app_from_env(), host="0.0.0.0", port=8000)
