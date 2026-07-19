"""vCard mapper: parse raw vCards into Contact models, create new cards,
and apply edits by mutating the stored raw vCard so unrendered properties
survive round-trips. vCard 3.0 with Apple conventions is the primary dialect."""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from dataclasses import dataclass, field

import vobject

# Apple wraps some labels in _$!<...>!$_ markers (e.g. _$!<HomePage>!$_).
_APPLE_LABEL_PREFIX = "_$!<"
_APPLE_LABEL_SUFFIX = ">!$_"

# TYPE values that describe transport/capability rather than a user-facing label.
_NON_LABEL_TYPES = {"internet", "voice", "pref", "x400"}

# Labels representable as a TYPE parameter; anything else becomes an
# itemN.X-ABLABEL group, the Apple convention for custom labels.
_TYPE_LABELS = {"home", "work", "cell", "main", "pager", "fax", "other", "school"}

# Labels Apple writes wrapped in _$!<...>!$_ markers.
_APPLE_CANONICAL_LABELS = {
    "HomePage", "Spouse", "Child", "Mother", "Father", "Parent", "Brother",
    "Sister", "Friend", "Manager", "Assistant", "Partner", "Anniversary",
}

# Multivalued/single-value properties apply_edits fully rewrites. N and ORG are
# deliberately NOT here: they carry sub-components this model doesn't surface
# (name prefix/middle/suffix, ORG department), so they are updated in place by
# _write_identity to avoid destroying those on every save.
_MANAGED_PROPS = ("fn", "note", "bday", "email", "tel", "url", "adr", "x-abrelatednames")

# PHOTO is parsed by hand rather than via vobject: vobject's default TextBehavior
# splits unencoded values on unescaped commas (icalendar TEXT semantics) and keeps
# only the first element, which silently truncates the vCard 4.0
# "data:image/jpeg;base64,<payload>" form at the comma before "base64". Regex
# extraction on the raw (unfolded) line sidesteps that entirely.
_PHOTO_LINE_RE = re.compile(
    r"^(?:[A-Za-z0-9_-]+\.)?PHOTO(?=[;:])((?:;[^:\r\n]*)*):(.*)$", re.IGNORECASE
)
# RFC 6350 param-value: either a bare run of non-semicolon/quote chars, or a
# "-quoted string in which semicolons are literal, not separators.
_PHOTO_PARAM_RE = re.compile(r';([A-Za-z0-9_-]+)=(?:"([^"]*)"|([^;]*))')
_DATA_URI_RE = re.compile(r"^data:([^;,]+);base64,(.*)$", re.IGNORECASE | re.DOTALL)


def _unfolded_lines(raw: str) -> list[str]:
    """Undo RFC 6350 line folding (CRLF/LF followed by a space or tab continues
    the previous line) so a wrapped PHOTO value reads as a single line."""
    lines = raw.replace("\r\n", "\n").split("\n")
    result: list[str] = []
    for line in lines:
        if line[:1] in (" ", "\t") and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def _clean_b64(value: str) -> str:
    """Strip whitespace and validate; invalid/incomplete base64 -> ''."""
    cleaned = re.sub(r"\s+", "", value)
    if not cleaned:
        return ""
    try:
        base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError):
        return ""
    return cleaned


def _normalize_media_type(type_param: str) -> str:
    t = type_param.strip()
    if not t:
        return "image/jpeg"  # embedded photos default to JPEG when TYPE is missing/unknown
    return t.lower() if "/" in t else f"image/{t.lower()}"


def _parse_photo(raw: str) -> tuple[str, str, str]:
    """Returns (media_type, b64, uri); at most one of b64/uri is set."""
    if "PHOTO" not in raw.upper():
        return "", "", ""  # cheap gate: skip the unfold pass on the common no-photo case

    for line in _unfolded_lines(raw):
        match = _PHOTO_LINE_RE.match(line)
        if not match:
            continue
        params_str, value = match.groups()
        params = {
            k.upper(): quoted or bare
            for k, quoted, bare in _PHOTO_PARAM_RE.findall(params_str)
        }
        value = value.strip()

        data_uri = _DATA_URI_RE.match(value)
        if data_uri:
            media_type, payload = data_uri.groups()
            b64 = _clean_b64(payload)
            if b64:
                return media_type.strip().lower(), b64, ""
            continue  # unusable -> keep scanning for a usable PHOTO line

        if params.get("ENCODING", "").lower() in ("b", "base64"):
            b64 = _clean_b64(value)
            if b64:
                return _normalize_media_type(params.get("TYPE", "")), b64, ""
            continue

        if params.get("VALUE", "").lower() == "uri" or value.lower().startswith(
            ("http://", "https://")
        ):
            return "", "", value

        continue  # unrecognized PHOTO form -> keep scanning
    return "", "", ""


@dataclass
class Contact:
    uid: str = ""
    formatted_name: str = ""
    given: str = ""
    family: str = ""
    org: str = ""
    note: str = ""
    bday: str = ""
    emails: list[tuple[str, str]] = field(default_factory=list)
    phones: list[tuple[str, str]] = field(default_factory=list)
    urls: list[tuple[str, str]] = field(default_factory=list)
    addresses: list[tuple[str, AddressParts]] = field(default_factory=list)
    related: list[tuple[str, str]] = field(default_factory=list)
    is_group: bool = False
    member_uids: list[str] = field(default_factory=list)
    photo_media_type: str = ""
    photo_b64: str = ""
    photo_uri: str = ""

    @property
    def has_photo(self) -> bool:
        return bool(self.photo_b64 or self.photo_uri)

    @property
    def initials(self) -> str:
        letters = "".join(part[0] for part in (self.given, self.family) if part)
        return letters.upper() if letters else self.formatted_name[:1].upper()

    @property
    def has_display_fields(self) -> bool:
        """Whether the detail-page field box has anything to show. Single
        source of truth for the box guard so adding a field type can't
        silently desync the `{% if %}` from the rows below it (#31 session)."""
        return bool(
            self.phones or self.emails or self.urls or self.addresses
            or self.related or self.bday or self.note
        )


def _clean_label(label: str) -> str:
    if label.startswith(_APPLE_LABEL_PREFIX) and label.endswith(_APPLE_LABEL_SUFFIX):
        return label[len(_APPLE_LABEL_PREFIX) : -len(_APPLE_LABEL_SUFFIX)]
    return label


def _ablabels(card: vobject.base.Component) -> dict[str, str]:
    """Map item group name (e.g. 'item1') -> its X-ABLABEL value."""
    labels: dict[str, str] = {}
    for prop in card.contents.get("x-ablabel", []):
        if prop.group:
            labels[prop.group] = _clean_label(prop.value)
    return labels


def _label_for(prop: vobject.base.ContentLine, group_labels: dict[str, str]) -> str:
    if prop.group and prop.group in group_labels:
        return group_labels[prop.group]
    types = [t.lower() for t in prop.params.get("TYPE", [])]
    for t in types:
        if t not in _NON_LABEL_TYPES:
            return t
    return ""


@dataclass
class AddressParts:
    """RFC 6350 ADR components. `pobox`/`extended` are carried but not surfaced
    for editing -- apply_edits round-trips whatever was there so unrelated saves
    don't destroy them."""

    street: str = ""
    city: str = ""
    region: str = ""
    code: str = ""
    country: str = ""
    pobox: str = ""
    extended: str = ""

    @property
    def formatted(self) -> str:
        parts = [self.street, self.city, self.region, self.code, self.country]
        return ", ".join(p for p in parts if p)


def _parse_address(value: vobject.vcard.Address) -> AddressParts:
    return AddressParts(
        street=value.street,
        city=value.city,
        region=value.region,
        code=value.code,
        country=value.country,
        pobox=value.box,
        extended=value.extended,
    )


def _read_card(raw: str) -> vobject.base.Component:
    try:
        return vobject.readOne(raw)
    except (binascii.Error, ValueError):
        # A malformed embedded PHOTO (bad base64) makes vobject's own decode
        # raise before we ever see the card. Retry with PHOTO stripped so the
        # rest of the contact still parses; our own regex-based _parse_photo
        # (below) independently treats the bad photo as absent. If stripping
        # PHOTO lines didn't change anything, the failure wasn't PHOTO-related
        # -- re-raise the original exception rather than obscuring it with an
        # identical retry.
        lines = _unfolded_lines(raw)
        stripped_lines = [line for line in lines if not _PHOTO_LINE_RE.match(line)]
        if len(stripped_lines) == len(lines):
            raise
        return vobject.readOne("\r\n".join(stripped_lines))


def parse_vcard(raw: str) -> Contact:
    card = _read_card(raw)
    contact = Contact()
    group_labels = _ablabels(card)

    if "uid" in card.contents:
        contact.uid = card.uid.value
    if "fn" in card.contents:
        contact.formatted_name = card.fn.value
    if "n" in card.contents:
        contact.given = card.n.value.given
        contact.family = card.n.value.family
    if "org" in card.contents:
        org = card.org.value
        contact.org = org[0] if isinstance(org, list) else org
    if "note" in card.contents:
        contact.note = card.note.value
    if "bday" in card.contents:
        contact.bday = card.bday.value

    for prop in card.contents.get("email", []):
        contact.emails.append((_label_for(prop, group_labels), prop.value))
    for prop in card.contents.get("tel", []):
        contact.phones.append((_label_for(prop, group_labels), prop.value))
    for prop in card.contents.get("url", []):
        contact.urls.append((_label_for(prop, group_labels), prop.value))
    for prop in card.contents.get("adr", []):
        contact.addresses.append((_label_for(prop, group_labels), _parse_address(prop.value)))
    for prop in card.contents.get("x-abrelatednames", []):
        contact.related.append((_label_for(prop, group_labels), prop.value))
    # vCard 4.0 RELATED: read (and round-trip; never introduced on our writes).
    for prop in card.contents.get("related", []):
        types = [t.lower() for t in prop.params.get("TYPE", []) if t.lower() != "text"]
        contact.related.append((types[0] if types else "", prop.value))

    kind = card.contents.get("x-addressbookserver-kind", [])
    if kind and kind[0].value.lower() == "group":
        contact.is_group = True
        for prop in card.contents.get("x-addressbookserver-member", []):
            contact.member_uids.append(prop.value.removeprefix("urn:uuid:"))

    contact.photo_media_type, contact.photo_b64, contact.photo_uri = _parse_photo(raw)

    return contact


@dataclass
class ContactFields:
    """Editable subset of a contact, as collected from the add/edit form."""

    given: str = ""
    family: str = ""
    org: str = ""
    note: str = ""
    bday: str = ""
    emails: list[tuple[str, str]] = field(default_factory=list)
    phones: list[tuple[str, str]] = field(default_factory=list)
    urls: list[tuple[str, str]] = field(default_factory=list)
    addresses: list[tuple[str, AddressParts]] = field(default_factory=list)
    related: list[tuple[str, str]] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


def _wrap_label(label: str) -> str:
    if label in _APPLE_CANONICAL_LABELS:
        return f"{_APPLE_LABEL_PREFIX}{label}{_APPLE_LABEL_SUFFIX}"
    return label


def _next_item_counter(card: vobject.base.Component) -> int:
    highest = 0
    for props in card.contents.values():
        for prop in props:
            match = re.fullmatch(r"item(\d+)", prop.group or "")
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


class _ItemGroups:
    """Allocates fresh itemN group names that don't collide with existing ones."""

    def __init__(self, card: vobject.base.Component) -> None:
        self._counter = _next_item_counter(card)

    def allocate(self) -> str:
        name = f"item{self._counter}"
        self._counter += 1
        return name


def _apply_label(
    card: vobject.base.Component, prop: vobject.base.ContentLine, label: str, groups: _ItemGroups
) -> None:
    if not label:
        return
    if label.lower() in _TYPE_LABELS:
        prop.type_param = label.upper()
    else:
        group = groups.allocate()
        prop.group = group
        ablabel = card.add("x-ablabel")
        ablabel.value = _wrap_label(label)
        ablabel.group = group


def _add_labeled(
    card: vobject.base.Component, prop_name: str, label: str, value: str, groups: _ItemGroups
) -> None:
    prop = card.add(prop_name)
    prop.value = value
    _apply_label(card, prop, label, groups)


def _add_labeled_address(
    card: vobject.base.Component, label: str, parts: AddressParts, groups: _ItemGroups
) -> None:
    prop = card.add("adr")
    prop.value = vobject.vcard.Address(
        box=parts.pobox,
        extended=parts.extended,
        street=parts.street,
        city=parts.city,
        region=parts.region,
        code=parts.code,
        country=parts.country,
    )
    _apply_label(card, prop, label, groups)


def _write_identity(card: vobject.base.Component, fields: ContactFields) -> None:
    """Set the name/company fields in place, preserving vCard sub-components the
    Contact model doesn't surface (name prefix/middle/suffix, ORG department)."""
    if "n" in card.contents:
        card.n.value.given = fields.given
        card.n.value.family = fields.family
    else:
        card.add("n").value = vobject.vcard.Name(family=fields.family, given=fields.given)

    fn = f"{fields.given} {fields.family}".strip() or fields.org
    if "fn" in card.contents:
        card.fn.value = fn
    else:
        card.add("fn").value = fn

    if fields.org:
        if "org" in card.contents and isinstance(card.org.value, list) and card.org.value:
            card.org.value[0] = fields.org  # keep department components
        else:
            card.add("org").value = [fields.org]
    else:
        card.contents.pop("org", None)  # cleared company -> drop ORG entirely


def _write_fields(card: vobject.base.Component, fields: ContactFields) -> None:
    groups = _ItemGroups(card)

    _write_identity(card, fields)
    if fields.note:
        card.add("note").value = fields.note
    if fields.bday:
        card.add("bday").value = fields.bday

    for label, value in fields.emails:
        _add_labeled(card, "email", label, value, groups)
    for label, value in fields.phones:
        _add_labeled(card, "tel", label, value, groups)
    for label, value in fields.urls:
        _add_labeled(card, "url", label, value, groups)
    for label, parts in fields.addresses:
        _add_labeled_address(card, label, parts, groups)
    for label, value in fields.related:
        # Relationships are always item-grouped; that's how Apple clients write them.
        group = groups.allocate()
        prop = card.add("x-abrelatednames")
        prop.value = value
        prop.group = group
        ablabel = card.add("x-ablabel")
        ablabel.value = _wrap_label(label)
        ablabel.group = group


def new_vcard(fields: ContactFields) -> str:
    card = vobject.vCard()
    card.add("uid").value = str(uuid.uuid4())
    _write_fields(card, fields)
    return card.serialize()


def new_group(name: str, member_uids: list[str] | None = None) -> str:
    card = vobject.vCard()
    card.add("uid").value = str(uuid.uuid4())
    _write_group(card, name, member_uids or [])
    return card.serialize()


def set_group(raw: str, name: str, member_uids: list[str]) -> str:
    """Rewrite a group card's name and member list, preserving other properties."""
    card = _read_card(raw)
    for prop_name in ("fn", "n", "x-addressbookserver-kind", "x-addressbookserver-member"):
        card.contents.pop(prop_name, None)
    _write_group(card, name, member_uids)
    return card.serialize()


def _write_group(card: vobject.base.Component, name: str, member_uids: list[str]) -> None:
    card.add("fn").value = name
    card.add("n").value = vobject.vcard.Name(family=name)
    card.add("x-addressbookserver-kind").value = "group"
    for uid in member_uids:
        card.add("x-addressbookserver-member").value = f"urn:uuid:{uid}"


_VERSION_4_RE = re.compile(r"^VERSION:\s*4(\.\d+)?\s*$", re.IGNORECASE | re.MULTILINE)
_FOLD_LIMIT = 75  # RFC 6350 octets per physical line, incl. the leading fold space


def _line_eol(raw: str) -> str:
    """The line-ending style of `raw`, so a splice can match it exactly."""
    return "\r\n" if "\r\n" in raw else "\n"


def _fold(line: str) -> list[str]:
    """Fold a single logical property line into RFC 6350 physical lines: the
    first line up to _FOLD_LIMIT octets, continuations up to _FOLD_LIMIT - 1
    (the extra octet reserved for the mandatory leading space), Apple-style.
    ASCII-only content (base64) makes octet-counting == char-counting safe."""
    if len(line) <= _FOLD_LIMIT:
        return [line]
    parts = [line[:_FOLD_LIMIT]]
    rest = line[_FOLD_LIMIT:]
    while rest:
        parts.append(" " + rest[: _FOLD_LIMIT - 1])
        rest = rest[_FOLD_LIMIT - 1 :]
    return parts


def _photo_value_line(b64: str, media_type: str, is_v4: bool) -> str:
    if is_v4:
        return f"PHOTO:data:{media_type};base64,{b64}"
    type_param = media_type.split("/", 1)[-1].upper() if media_type else "JPEG"
    return f"PHOTO;ENCODING=b;TYPE={type_param}:{b64}"


def _splice_photo(raw: str, new_value_line: str | None) -> str:
    """Raw-line splice shared by set_photo/remove_photo: drop every existing
    PHOTO property (the line and any RFC 6350 fold continuations of it),
    leaving all other physical lines byte-identical, then -- if a replacement
    is given -- insert it (folded) just before END:VCARD.

    Splitting uses a universal-newline regex rather than the card's single
    detected eol: a card that's mostly CRLF but has one stray bare-LF-terminated
    line (seen from some non-Apple writers) would otherwise leave that line
    un-split, so a PHOTO line on it is neither matched for removal nor folded
    correctly. The whole result is rejoined on the card's dominant eol."""
    eol = _line_eol(raw)
    lines = re.split(r"\r\n|\n", raw)

    groups: list[list[str]] = []
    for line in lines:
        if line[:1] in (" ", "\t") and groups:
            groups[-1].append(line)
        else:
            groups.append([line])

    kept = [g for g in groups if not _PHOTO_LINE_RE.match(g[0])]

    if new_value_line is not None:
        new_group = _fold(new_value_line)
        end_idx = next(
            (i for i, g in enumerate(kept) if g[0].strip().upper() == "END:VCARD"),
            len(kept),
        )
        kept.insert(end_idx, new_group)

    return eol.join(line for group in kept for line in group)


def set_photo(raw: str, b64: str, media_type: str) -> str:
    """Replace all PHOTO properties on a raw vCard with `b64`/`media_type`,
    dialected by the card's own VERSION (default 3.0 if absent). Every other
    line is preserved byte-for-byte; the result re-parses via parse_vcard."""
    is_v4 = bool(_VERSION_4_RE.search(raw))
    return _splice_photo(raw, _photo_value_line(b64, media_type, is_v4))


def remove_photo(raw: str) -> str:
    """Delete all PHOTO properties from a raw vCard; every other line
    preserved byte-for-byte."""
    return _splice_photo(raw, None)


def apply_edits(raw: str, fields: ContactFields) -> str:
    """Rewrite the managed properties of an existing raw vCard from `fields`,
    leaving every other property (PHOTO, X-*, ...) untouched. ADR is managed:
    rewritten from fields like email/tel (unknown ADR params don't survive)."""
    card = _read_card(raw)

    managed_groups = set()
    for name in _MANAGED_PROPS:
        for prop in card.contents.get(name, []):
            if prop.group:
                managed_groups.add(prop.group)
        card.contents.pop(name, None)

    # Drop X-ABLABELs that belonged to properties we just removed.
    labels = card.contents.get("x-ablabel", [])
    remaining = [p for p in labels if p.group not in managed_groups]
    if remaining:
        card.contents["x-ablabel"] = remaining
    else:
        card.contents.pop("x-ablabel", None)

    _write_fields(card, fields)
    return card.serialize()
