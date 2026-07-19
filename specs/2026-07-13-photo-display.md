# Spec: Display contact photos (issue #9)

**Problem.** `PHOTO` is preserved on edit but never parsed or displayed. Users see no
avatars anywhere in the app.

**Intended behavior.**

1. **Parsing (`vcard.py`).** `parse_vcard` populates new `Contact` fields:
   - `photo_media_type: str` (e.g. `"image/jpeg"`), `photo_b64: str` (base64 payload,
     whitespace stripped) for embedded photos, `photo_uri: str` for URI-valued PHOTO.
   - Handle all three real-world forms:
     - vCard 3.0: `PHOTO;ENCODING=b;TYPE=JPEG:<base64>` (TYPE may be `JPEG`/`PNG`/
       `image/jpeg`; ENCODING may be `b` or `BASE64`).
     - vCard 4.0: `PHOTO:data:image/jpeg;base64,<base64>`.
     - URI: `PHOTO;VALUE=uri:https://...` or a bare `http(s)` value → `photo_uri`.
   - Unparseable/invalid base64 → treat as absent (no crash, no fallback garbage).
   - `Contact.has_photo` convenience (embedded or uri).
2. **Serving (`app.py`).** `GET /contacts/{uid}/photo`:
   - Embedded photo → decoded bytes with the parsed media type (default `image/jpeg`
     when TYPE missing), `Cache-Control: private, max-age=3600`, and an `ETag` from the
     store record's etag with `If-None-Match` → 304 support.
   - No photo or URI-only → 404. Auth required like other contact routes.
3. **Templates.**
   - `detail.html`: avatar at top of the contact card — `<img>` from
     `/contacts/{uid}/photo` (embedded) or the external URI (uri form); otherwise an
     initials fallback (first letters of given/family, else first char of FN) styled
     as a circle. Alt text = contact name.
   - `_contacts.html`: small avatar (same rules, initials fallback) per row.
   - Initials derivation lives in Python (model property or filter), not Jinja logic.
4. **Round-trip safety.** PHOTO stays out of `_MANAGED_PROPS`; add a regression test
   that `apply_edits` on a card with an embedded PHOTO leaves the PHOTO property
   byte-identical.

**Out of scope.** Upload/replace/remove (issue #11). Group cards get no avatar change
beyond the shared list partial. Proxying external URI photos.

**Test approach.** TDD in `tests/test_vcard_mapper.py` (parse forms, invalid b64,
round-trip) and a new `tests/test_photos.py` (route: 200 with bytes + media type,
ETag/304, 404 when absent, auth redirect; template: initials fallback appears).
Live-verify note: check a real Baikal card with an Apple-written photo renders.
