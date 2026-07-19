# Spec: Photo upload / editing (issue #11)

**Problem.** Photos display (#9) but can't be added, replaced, or removed in the app.

**Intended behavior.**

1. **Form.** `form.html` gains a photo section: current avatar preview (reuse the
   avatar macro), `<input type="file" name="photo" accept="image/jpeg,image/png">`,
   and a "remove photo" checkbox shown only when the contact has one. Applies to both
   create and edit (shared template); `enctype="multipart/form-data"`.
2. **Processing (new `src/peopledb/photos.py`).** Pillow (new dependency):
   - Accept JPEG/PNG uploads; reject other types and anything over 10 MB with a
     rendered form error (no 500).
   - Normalize: EXIF-orient, flatten alpha onto white, downscale so the longest side
     is ≤ 512 px, re-encode JPEG quality 85. Output: (b64 payload, "image/jpeg").
   - Corrupt/undecodable image → form error, contact unchanged.
3. **vCard write-back (`vcard.py`).** `set_photo(raw, b64, media_type)` and
   `remove_photo(raw)` splice PHOTO at the raw-line level (same infrastructure as
   `_parse_photo`/`_read_card`), replacing ALL existing PHOTO lines:
   - VERSION:3.0 card → `PHOTO;ENCODING=b;TYPE=JPEG:<b64>` folded at 75 octets.
   - VERSION:4.0 card → `PHOTO:data:image/jpeg;base64,<b64>`.
   - Every other line byte-preserved; result must re-parse (`parse_vcard` sees the
     new photo). Removal deletes PHOTO lines only.
4. **Routes (`app.py`).** `create_contact` and `update_contact` read the multipart
   file + `photo_remove` flag; photo change applies on top of `apply_edits` output
   before the DAV PUT (one write). No file → photo untouched (edit) / none (create).
   Photo-only edits still bump via the normal conflict/etag path.

**Out of scope.** Cropping UI; multiple photos; preserving the original resolution;
GIF/WebP/HEIC input.

**Test approach.** TDD: photos.py unit tests (downscale, EXIF rotate, alpha flatten,
reject oversize/corrupt/wrong-type — generate images with Pillow in-test); vcard
set/remove tests (v3 folding + dialect choice, v4 data URI, replace-all, byte-
preservation of other lines, reparse); route tests (upload through TestClient
multipart on the seeded-store pattern where possible, plus live Radicale end-to-end:
upload → raw card on server has folded PHOTO → /photo route serves re-encoded bytes;
remove → PHOTO gone). Live-verify note: photo set in app must render in Apple
Contacts/Cardhop against real Baikal.
