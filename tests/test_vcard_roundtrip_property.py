"""Property-based test: unknown properties survive apply_edits — the main
data-loss risk in the whole design (spec: 'parse → edit → serialize preserves
unknown properties')."""

import string

import vobject
from hypothesis import given, strategies as st

from peopledb.vcard import ContactFields, apply_edits

prop_names = st.text(alphabet=string.ascii_uppercase + string.digits + "-", min_size=1, max_size=20).map(
    lambda s: "X-TEST-" + s.strip("-")
)
prop_values = st.text(
    alphabet=st.characters(codec="utf-8", exclude_characters="\r\n", exclude_categories=("Cs", "Cc")),
    min_size=1,
    max_size=60,
)


@given(props=st.dictionaries(prop_names, prop_values, min_size=1, max_size=5))
def test_unknown_properties_survive_edit(props):
    card = vobject.vCard()
    card.add("uid").value = "prop-test-1"
    card.add("fn").value = "Prop Test"
    card.add("n").value = vobject.vcard.Name(family="Test", given="Prop")
    for name, value in props.items():
        card.add(name.lower()).value = value
    raw = card.serialize()

    edited = apply_edits(raw, ContactFields(given="Edited", family="Test"))

    reparsed = vobject.readOne(edited)
    for name, value in props.items():
        stored = [p.value for p in reparsed.contents.get(name.lower(), [])]
        assert value in stored, f"{name} lost or corrupted by apply_edits"
