"""Pure merge logic for combining two contacts (#28): multi-valued field
union with exact-value dedup, self-relation collapse, single-valued field
selection, and group-member-list rewrite. No DAV/HTTP -- importable and
unit-testable standalone. `app.py` wires this to the etag-conditional write
sequence (delete-last, no rollback -- ADR-0006)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from peopledb.vcard import Contact, ContactFields

T = TypeVar("T")


def union_values(
    keeper_items: list[tuple[str, T]], source_items: list[tuple[str, T]]
) -> list[tuple[str, T]]:
    """Union a multi-valued field (emails/phones/urls/addresses/related):
    keeper's entries first, then source entries whose value hasn't already
    appeared, exact match (`==`) on value -- first label seen wins. Works for
    both plain string values and AddressParts (a plain dataclass, so `==`
    compares fields without needing hashability)."""
    result = list(keeper_items)
    seen = [value for _, value in keeper_items]
    for label, value in source_items:
        if value not in seen:
            result.append((label, value))
            seen.append(value)
    return result


def drop_self_relations(
    related: list[tuple[str, str]],
    keeper_uid: str,
    source_uid: str,
    keeper_name: str = "",
    source_name: str = "",
) -> list[tuple[str, str]]:
    """Drop any `related` entry whose value resolves to the keeper's or
    source's own identity -- once the pair is merged, an A<->B relation
    *between them* is a self-reference and doesn't survive. RELATED values
    are either a UID (vCard 4) or a display name (vCard 3 X-ABRELATEDNAMES),
    so both are checked."""
    self_targets = {t for t in (keeper_uid, source_uid, keeper_name, source_name) if t}
    return [(label, value) for label, value in related if value not in self_targets]


def rewrite_members(
    members: list[str], source_uid: str, keeper_uid: str
) -> list[str]:
    """Pure source->keeper member-list rewrite for a group move: replace every
    occurrence of `source_uid` with `keeper_uid`, then dedup keeping the first
    occurrence -- a group where both the keeper and source were already
    members ends up with the keeper listed once."""
    replaced = [keeper_uid if uid == source_uid else uid for uid in members]
    result: list[str] = []
    for uid in replaced:
        if uid not in result:
            result.append(uid)
    return result


@dataclass
class MergeChoice:
    """Which card -- 'a' (contact_a) or 'b' (contact_b) -- each single-valued
    field takes in a merge. This is deliberately independent of which card is
    the *keeper* (the survivor): keeper identity decides which card's UID/href
    and unknown properties persist, never which field VALUES win -- conflating
    the two inverted every field on a keeper-flip (#28 finding 1). Defaults to
    'a' everywhere, matching the review screen's pre-selected radios."""

    given: str = "a"
    family: str = "a"
    org: str = "a"
    note: str = "a"
    bday: str = "a"


def resolve_single(a_value: str, b_value: str, choice: str) -> str:
    """`choice` is 'a' (default, contact_a's value) or 'b' (contact_b's)."""
    return b_value if choice == "b" else a_value


def build_merged_fields(
    keeper: Contact,
    source: Contact,
    choice: MergeChoice,
    *,
    contact_a: Contact,
    contact_b: Contact,
    emails: list[tuple[str, str]] | None = None,
    phones: list[tuple[str, str]] | None = None,
    urls: list[tuple[str, str]] | None = None,
    addresses: list | None = None,
    related: list[tuple[str, str]] | None = None,
) -> ContactFields:
    """Build the merged `ContactFields`, ready for `apply_edits(keeper.raw,
    fields)`. Multi-valued arguments default to the full keeper-first union
    (with self-relation collapse applied to `related`) when not given
    explicitly -- the review screen instead passes the user's checked subset
    of that same union. Single-valued fields (given/family/org/note/bday) are
    resolved from `contact_a`/`contact_b` per `choice`, NOT from keeper/source
    -- the keeper only supplies the raw base, UID/href and unknown props that
    `apply_edits` leaves alone; it must never flip which value wins."""
    if emails is None:
        emails = union_values(keeper.emails, source.emails)
    if phones is None:
        phones = union_values(keeper.phones, source.phones)
    if urls is None:
        urls = union_values(keeper.urls, source.urls)
    if addresses is None:
        addresses = union_values(keeper.addresses, source.addresses)
    if related is None:
        related = drop_self_relations(
            union_values(keeper.related, source.related),
            keeper.uid, source.uid, keeper.formatted_name, source.formatted_name,
        )
    return ContactFields(
        given=resolve_single(contact_a.given, contact_b.given, choice.given),
        family=resolve_single(contact_a.family, contact_b.family, choice.family),
        org=resolve_single(contact_a.org, contact_b.org, choice.org),
        note=resolve_single(contact_a.note, contact_b.note, choice.note),
        bday=resolve_single(contact_a.bday, contact_b.bday, choice.bday),
        emails=emails,
        phones=phones,
        urls=urls,
        addresses=addresses,
        related=related,
    )
