"""Pin the invalid-sync-token classification in DavClient.sync().

Verified against source (2026-07-13):
- sabre/dav (Baikal): any invalid/unknown/expired sync token -> HTTP 403 with
  body `<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>`
  (Sabre\\DAV\\Exception\\InvalidSyncToken extends Forbidden).
- Radicale: also 403, body via xmlutils.webdav_error("D:valid-sync-token")
  (deliberately not 409, for client compatibility).

dav.py's heuristic (`resp.status_code in (403, 409) and "valid-sync-token" in
resp.text`) is a plain substring match against the raw response body, so it is
already case-sensitive-agnostic to the "d:"/"D:" namespace prefix difference
between servers -- these tests confirm that and guard a plain-403 auth
failure isn't misclassified.
"""

from __future__ import annotations

import httpx
import pytest

from peopledb.dav import DavClient, InvalidSyncToken

SABRE_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>'
)

RADICALE_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:error xmlns:D="DAV:"><D:valid-sync-token/></D:error>'
)

PLAIN_FORBIDDEN_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:error xmlns:D="DAV:"><D:not-authorized/></D:error>'
)


def _client_with_response(status_code: int, body: str) -> DavClient:
    client = DavClient("http://example.test/dav.php/", "user", "pass")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_sabre_dav_403_valid_sync_token_raises_invalid_sync_token():
    client = _client_with_response(403, SABRE_BODY)
    with pytest.raises(InvalidSyncToken):
        client.sync("/dav.php/addressbooks/jason/default/", "stale-token")


def test_radicale_style_uppercase_prefix_still_classified():
    client = _client_with_response(403, RADICALE_BODY)
    with pytest.raises(InvalidSyncToken):
        client.sync("/dav.php/addressbooks/jason/default/", "stale-token")


def test_plain_403_without_valid_sync_token_element_is_not_invalid_token():
    client = _client_with_response(403, PLAIN_FORBIDDEN_BODY)
    with pytest.raises(Exception) as exc_info:
        client.sync("/dav.php/addressbooks/jason/default/", "stale-token")
    assert not isinstance(exc_info.value, InvalidSyncToken)
