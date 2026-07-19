# Spec — Merge duplicate contacts (#28)

_2026-07-16 · enhancement · surface: web UI (templates) + CardDAV writes (store/dav) · **destructive**_

## Problem

A CardDAV address book accumulates duplicates (the same person added twice, an
import doubling a card). peopleDB can create, edit, and delete contacts but has
no way to **combine** two cards into one — you must hand-copy fields across and
delete the loser, losing whichever data you forget. #28 adds a first-class merge.

## Intended behavior

**Manual, two-contact merge.** No duplicate-detection heuristics and no review
queue — the user picks the pair explicitly. Non-group contacts only (merging a
group, or a group with a contact, is out of scope).

**Entry + selection.**
- A `Merge with…` action on a contact's **detail page**.
- The user picks the second contact via the existing contact search. Self and
  groups are not selectable.

**Review screen** (server-rendered, edit-form idiom):
- **Keeper radio** — which card *survives*. Defaults to the contact the merge
  started from. The keeper keeps its **UID, PHOTO, and all unknown `X-`
  properties**; the other card is deleted. The screen states this so the choice
  is informed (unknown-prop preservation only holds on the keeper — the loser's
  custom props are lost on delete).
- **Single-valued fields** (N/name, org, bday, note): radio, keeper's value
  pre-selected, the other value selectable. Photo defaults to the keeper's with
  a toggle to take the source's.
- **Multi-valued fields** (emails, phones, URLs, addresses, related): **unioned**
  from both sides, exact-duplicate values dropped, each an all-checked-by-default
  checkbox so any entry can be dropped.

**Merge algorithm** — one POST, all cache mutation under `lock_for(user)` on a
single worker thread (ADR-0004), **delete last** (see ADR-0006):

1. Build merged `ContactFields` from the selections → `apply_edits(keeper.raw,
   fields)` (+ `set_photo` iff the photo changed) — preserves keeper unknown props.
2. **`dav.put(keeper.href, merged_raw, keeper.etag)`**, etag-conditional. On
   conflict (keeper edited elsewhere): **abort before any other write**, re-render
   with the existing conflict banner. Zero server changes.
3. **Group moves:** for every group (`list_groups`) whose members include the
   source UID, rewrite source→keeper (dedupe if keeper already a member) via
   `set_group` + etag-conditional PUT. Failures **warn, don't abort**
   (`?group_warn=` pattern from #24).
4. **`dav.delete(source.href, source.etag)`** — **last**. On failure, warn; the
   source survives as a harmless leftover duplicate to retry.
5. Cache: `cache_after_write` for keeper + each touched group; `locked_delete`
   for source — all under the held lock.

**Edge cases handled:** an A↔B relation *between the merged pair itself* collapses
to a self-reference and is dropped from the union; both cards in the same group →
keeper appears once after dedup; union dedup is exact string match on value
(keeps the first label seen).

## Out of scope / accepted residuals

- **Duplicate detection** (name/email/phone heuristics) and a review queue — v1 is
  manual pick-two only. A later cycle can feed pairs into this same flow.
- **Inbound `RELATED` to the source** left dangling — degrades gracefully (a dead
  related-UID just fails to resolve on the detail page). Groups are cleaned; other
  contacts' relations are not.
- **No phone/email normalization** in union dedup: `+15551234` and `555-1234` are
  distinct, both kept (uncheck one on the review screen).
- Merging 3+ at once; undo; group-with-group merges.
- **No atomicity/rollback** — a partial failure leaves a harmless leftover, never
  data loss (ADR-0006).

## Test approach

- **`/tdd` on the pure pieces:** field union + exact-dedup; source→keeper group
  member rewrite (incl. keeper-already-member dedup); self-relation drop.
- **Live-verify** the full write sequence against the throwaway CardDAV server
  (`-m live`): happy-path merge, **keeper-conflict abort** (no writes), group
  membership moved, **delete-fails → warn + source survives**.
- **`/code-review`** on the full diff + **`security` agent** (destructive CardDAV
  deletes acting on user data).
