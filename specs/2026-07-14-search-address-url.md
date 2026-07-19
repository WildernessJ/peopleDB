# Expand search to address + URL fields (#15)

## Problem
Full-text search (`contacts_fts`, `store.py`) indexes name, org, emails, phones, and note.
It does **not** index postal addresses or URLs, so searching for a street, town, postcode, or
a contact's website returns nothing — surfaced while testing the Dockerized build against real
Baikal.

## Intended behavior
1. **Index address.** Each contact's postal addresses are indexed for search. All ADR
   components that get surfaced (street, city, region, code, country) are searchable — reuse
   `AddressParts.formatted` joined across the contact's `addresses`. A term matching any part
   of any address returns the contact (prefix-match, same as today's search).
2. **Index URL.** Each contact's URLs (`contact.urls` values) are indexed and searchable the
   same way.
3. **Ranking/behavior unchanged.** Results still order by `sort_name`; the query parser
   (per-term quote + prefix wildcard) is unchanged. Groups and broken cards remain excluded
   from the index, as today.
4. **Migration for existing caches.** Adding FTS columns changes the `contacts_fts` schema.
   FTS5 has no `ALTER … ADD COLUMN`, and the cache is disposable, so on startup an existing DB
   whose `contacts_fts` predates this change is **dropped and rebuilt** from the canonical
   `contacts.raw` blobs (re-parsed through the same upsert projection). Tracked via
   `PRAGMA user_version` so the rebuild runs exactly once, not on every boot. A fresh DB just
   gets the new schema. No re-sync from the server is required.

## Out of scope
- Indexing title / nickname (needs new `Contact` parser fields — deferred; not in this change).
- Per-field weighting / relevance ranking (bm25) — order stays `sort_name`.
- Any UI, route, or search-box changes — this is index coverage only.
- Changing how addresses/URLs are parsed, stored, or round-tripped.

## Test approach
- Bug/feature unit tests (`test_store.py` or equivalent): a contact with a distinctive
  street / city / postcode / country token is found by searching that token; a contact with a
  distinctive URL token is found by searching it; a term matching none still returns nothing;
  existing name/org/email search stays green (the pre-existing phone/note columns have no
  dedicated test — not regressed here, but not newly covered either).
- Migration test: seed a DB with the **old** `contacts_fts` column set + `contacts` rows,
  open the store, assert the FTS table is rebuilt with the new columns and address/url search
  works — and that `user_version` gating means a second open does not rebuild again.
- Live-verify: search address + URL terms against a real CardDAV server in the browser.
