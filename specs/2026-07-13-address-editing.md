# Spec: Address (ADR) editing (issue #1)

**Problem.** Addresses render read-only (parsed to a display string); `ContactFields`
has no addresses and `form.html` no address inputs — an ADR can never be added,
changed, or removed in the app.

**Intended behavior.**

1. **Model.** `Contact.addresses` becomes structured: `list[tuple[str, AddressParts]]`
   where `AddressParts` is a small dataclass with the RFC 6350 components we edit —
   `street`, `city` (locality), `region`, `code` (postal), `country` — plus the two we
   don't surface for editing but must not destroy: `pobox`, `extended`. Keep a
   `formatted` property (current "street, city, region, code, country" join) so
   detail.html / maps links keep working unchanged.
2. **Form.** `form.html` gets an addresses fieldset mirroring the email/phone row
   pattern: a label input plus street / city / region (state) / postal code / country
   inputs per row, add-row button, blank rows ignored (an address row counts as
   non-empty if any component is filled). `pobox`/`extended` ride along as hidden
   inputs so editing other fields doesn't drop them; new rows have them empty.
3. **Write-back.** `adr` joins the managed properties: `apply_edits` rewrites ADR
   from `ContactFields.addresses` (same delete-and-rewrite as email/tel), with labels
   via TYPE param or itemN.X-ABLABEL exactly like `_add_labeled`. Components map to
   `vobject.vcard.Address(box=pobox, extended=extended, street=..., city=...,
   region=..., code=..., country=...)`. Multi-line values must survive vobject's
   escaping round-trip.
4. **Fields plumbing.** `ContactFields.addresses` + `_fields_from_form` parses the
   parallel per-component input lists (`adr_label`, `adr_street`, `adr_city`,
   `adr_region`, `adr_code`, `adr_country`, `adr_pobox`, `adr_extended` — index-aligned
   via getlist). Edit form pre-populates rows from the parsed contact.

**Out of scope.** Address validation/geocoding; more than one line per component;
vCard 4 ADR LABEL param synthesis.

**Test approach.** TDD: mapper tests (parse structured components incl. pobox/extended;
apply_edits round-trip preserves unedited pobox/extended and other props; label
handling; removal by clearing all rows; add to a card with none), form/route tests
(create + edit with addresses through the app, template renders existing rows).
Live-verify note: edit a real Baikal contact's address in the app, confirm Apple
Contacts shows the change and no components were lost.
