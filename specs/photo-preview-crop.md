# Photo upload: full-size preview + client-side crop (#14, #17)

## Problem
Selecting a contact photo previews tiny (inside the file-input row) and always uploads the
whole frame. The user can't see what they're about to save at avatar size, nor control framing.

## Intended behavior
On the contact create/edit form (`form.html`):

1. **Preview in the avatar spot (#14).** When a file is selected in the photo input, the
   existing avatar/initials at the top of the form is replaced by a live preview of the
   chosen image, rendered at the normal `.avatar` size (circular, object-fit cover), so the
   user sees exactly what the saved avatar will look like. Selecting a different file
   updates the preview; the "remove photo" checkbox (when present) and preview must not
   contradict each other (checking remove hides/clears the preview).
2. **Square crop before save (#17).** Alongside the preview, a crop surface appears:
   the full image with a square selection region, defaulting to the largest centered square.
   The user can drag the selection to reposition and resize it (pointer events; must work
   with mouse and touch). The avatar-spot preview live-reflects the current crop.
3. **Client-side export.** On form submit (or when the crop changes), the cropped square is
   exported via canvas (`toBlob`, JPEG, quality ≥ 0.9) and swapped into the form's file
   input via `DataTransfer`, so the server receives an ordinary JPEG upload. The server
   pipeline (`photos.py`: validate → EXIF-rotate → flatten → ≤512px → JPEG q85) is unchanged.
4. **Progressive enhancement.** With JS disabled, the form must still submit the original
   file exactly as today. No new server routes, no new form fields the server depends on.
5. **Style/JS conventions.** Follow existing patterns in `base.html`: IIFE-scoped script,
   data-attributes for state, CSS variables for colors (crop overlay must be legible in
   both themes; respect the accent system).

## Out of scope
- Non-square / freeform crop aspect ratios; rotation; zoom beyond crop-square resizing.
- Server-side crop, new endpoints, or persisting crop coordinates.
- List/detail-page avatar changes (#16 is separate).
- HEIC or formats the server doesn't accept (input stays JPEG/PNG).

## Test approach
- Existing suites (`test_photo_upload.py`, `test_photo_processing.py`, `test_photos.py`)
  stay green untouched — server path is unchanged.
- New template tests: form page markup contains the preview/crop hooks (container, canvas,
  file-input wiring) on both create and edit forms; edit form with an existing photo still
  renders the current avatar; markup absent nowhere it shouldn't be.
- Interaction (drag/resize/export) is live-verified in a real browser, not unit-tested.
