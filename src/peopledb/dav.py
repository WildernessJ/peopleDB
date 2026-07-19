"""CardDAV client over httpx: discovery, sync-collection REPORT, and
etag-conditional writes. Hand-rolled because the `caldav` library is
CalDAV-only (see ADR-0001 amendment). The server stays canonical; every
write is conditional so concurrent edits surface as ConflictError."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import escape as _xml_escape

import httpx

_DAV = "DAV:"
_CARDDAV = "urn:ietf:params:xml:ns:carddav"


class DavError(Exception):
    """A CardDAV request failed."""


class ConflictError(DavError):
    """Conditional write refused (412): the card changed on the server."""


class InvalidSyncToken(DavError):
    """The server rejected our stored sync-token; a full resync is required."""


class UnreachableError(DavError):
    """The CardDAV server could not be reached."""


@dataclass
class Addressbook:
    url: str  # server-absolute path, e.g. /dav.php/addressbooks/user/default/
    name: str


@dataclass
class SyncChange:
    href: str
    etag: str
    raw: str


@dataclass
class SyncResult:
    token: str
    changed: list[SyncChange] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def _tag(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


class DavClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 15.0):
        parts = urlsplit(base_url)
        self._origin = f"{parts.scheme}://{parts.netloc}"
        self._base_path = parts.path or "/"
        self._http = httpx.Client(
            auth=(username, password), timeout=timeout, follow_redirects=True
        )

    def close(self) -> None:
        self._http.close()

    def _url(self, path: str) -> str:
        return urljoin(self._origin, path)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, self._url(path), **kwargs)
        except httpx.TransportError as exc:
            raise UnreachableError(str(exc)) from exc

    def _propfind(self, path: str, body: str, depth: str) -> ET.Element:
        resp = self._request(
            "PROPFIND", path, content=body,
            headers={"Depth": depth, "Content-Type": "application/xml"},
        )
        if resp.status_code != 207:
            raise DavError(f"PROPFIND {path} -> {resp.status_code}")
        return ET.fromstring(resp.content)

    # -- auth / discovery ---------------------------------------------------

    def validate_credentials(self) -> bool:
        body = (
            '<?xml version="1.0"?><propfind xmlns="DAV:">'
            "<prop><current-user-principal/></prop></propfind>"
        )
        resp = self._request(
            "PROPFIND", self._base_path, content=body,
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        return resp.status_code == 207

    def principal_path(self) -> str:
        body = (
            '<?xml version="1.0"?><propfind xmlns="DAV:">'
            "<prop><current-user-principal/></prop></propfind>"
        )
        tree = self._propfind(self._base_path, body, "0")
        href = tree.find(
            f".//{_tag(_DAV, 'current-user-principal')}/{_tag(_DAV, 'href')}"
        )
        if href is None or not href.text:
            raise DavError("no current-user-principal in response")
        return href.text

    def addressbook_home_path(self) -> str:
        body = (
            '<?xml version="1.0"?>'
            '<propfind xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav">'
            "<prop><CR:addressbook-home-set/></prop></propfind>"
        )
        tree = self._propfind(self.principal_path(), body, "0")
        href = tree.find(
            f".//{_tag(_CARDDAV, 'addressbook-home-set')}/{_tag(_DAV, 'href')}"
        )
        if href is None or not href.text:
            raise DavError("no addressbook-home-set in response")
        return href.text

    def addressbooks(self) -> list[Addressbook]:
        body = (
            '<?xml version="1.0"?><propfind xmlns="DAV:">'
            "<prop><resourcetype/><displayname/></prop></propfind>"
        )
        tree = self._propfind(self.addressbook_home_path(), body, "1")
        books = []
        for response in tree.findall(_tag(_DAV, "response")):
            rtype = response.find(
                f".//{_tag(_DAV, 'resourcetype')}/{_tag(_CARDDAV, 'addressbook')}"
            )
            if rtype is None:
                continue
            href = response.findtext(_tag(_DAV, "href"), "")
            name = response.findtext(
                f".//{_tag(_DAV, 'displayname')}", ""
            ) or href.rstrip("/").rsplit("/", 1)[-1]
            books.append(Addressbook(url=href, name=name))
        return books

    # -- sync ----------------------------------------------------------------

    def sync(self, addressbook_path: str, token: str | None) -> SyncResult:
        body = (
            '<?xml version="1.0"?><sync-collection xmlns="DAV:">'
            f"<sync-token>{token or ''}</sync-token>"
            "<sync-level>1</sync-level>"
            "<prop><getetag/></prop>"
            "</sync-collection>"
        )
        resp = self._request(
            "REPORT", addressbook_path, content=body,
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        if resp.status_code in (403, 409) and "valid-sync-token" in resp.text:
            raise InvalidSyncToken(token or "")
        if resp.status_code != 207:
            raise DavError(f"sync-collection REPORT -> {resp.status_code}: {resp.text[:200]}")
        tree = ET.fromstring(resp.content)

        new_token = tree.findtext(_tag(_DAV, "sync-token"), "")
        changed_hrefs: list[str] = []
        deleted: list[str] = []
        for response in tree.findall(_tag(_DAV, "response")):
            href = response.findtext(_tag(_DAV, "href"), "")
            if href.rstrip("/") == addressbook_path.rstrip("/"):
                continue
            status = response.findtext(_tag(_DAV, "status"), "")
            if "404" in status:
                deleted.append(href)
            else:
                changed_hrefs.append(href)

        return SyncResult(
            token=new_token,
            changed=self._multiget(addressbook_path, changed_hrefs),
            deleted=deleted,
        )

    def _multiget(self, addressbook_path: str, hrefs: list[str]) -> list[SyncChange]:
        if not hrefs:
            return []
        href_xml = "".join(f"<href>{_xml_escape(h)}</href>" for h in hrefs)
        body = (
            '<?xml version="1.0"?>'
            '<CR:addressbook-multiget xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav">'
            "<prop><getetag/><CR:address-data/></prop>"
            f"{href_xml}"
            "</CR:addressbook-multiget>"
        )
        resp = self._request(
            "REPORT", addressbook_path, content=body,
            headers={"Depth": "1", "Content-Type": "application/xml"},
        )
        if resp.status_code != 207:
            raise DavError(f"addressbook-multiget -> {resp.status_code}")
        tree = ET.fromstring(resp.content)
        changes = []
        for response in tree.findall(_tag(_DAV, "response")):
            href = response.findtext(_tag(_DAV, "href"), "")
            etag = response.findtext(f".//{_tag(_DAV, 'getetag')}", "")
            raw = response.findtext(f".//{_tag(_CARDDAV, 'address-data')}", "")
            if raw:
                changes.append(SyncChange(href=href, etag=etag, raw=raw))
        return changes

    # -- card CRUD -----------------------------------------------------------

    def get(self, href: str, missing_ok: bool = False) -> tuple[str | None, str | None]:
        resp = self._request("GET", href)
        if resp.status_code == 404 and missing_ok:
            return None, None
        if resp.status_code != 200:
            raise DavError(f"GET {href} -> {resp.status_code}")
        return resp.text, resp.headers.get("ETag", "")

    def create(self, addressbook_path: str, uid: str, raw: str) -> tuple[str, str]:
        href = addressbook_path.rstrip("/") + f"/{uid}.vcf"
        etag = self._conditional_put(href, raw, {"If-None-Match": "*"})
        return href, etag

    def put(self, href: str, raw: str, etag: str) -> str:
        return self._conditional_put(href, raw, {"If-Match": etag})

    def _conditional_put(self, href: str, raw: str, condition: dict[str, str]) -> str:
        resp = self._request(
            "PUT", href, content=raw,
            headers={"Content-Type": "text/vcard; charset=utf-8", **condition},
        )
        if resp.status_code == 412:
            raise ConflictError(f"PUT {href}: card changed on server")
        if resp.status_code not in (200, 201, 204):
            raise DavError(f"PUT {href} -> {resp.status_code}: {resp.text[:200]}")
        etag = resp.headers.get("ETag")
        if not etag:
            # Some servers omit ETag on PUT; fetch it.
            _, etag = self.get(href)
        return etag or ""

    def delete(self, href: str, etag: str | None = None) -> None:
        headers = {"If-Match": etag} if etag else {}
        resp = self._request("DELETE", href, headers=headers)
        if resp.status_code == 412:
            raise ConflictError(f"DELETE {href}: card changed on server")
        if resp.status_code not in (200, 204, 404):
            raise DavError(f"DELETE {href} -> {resp.status_code}")
