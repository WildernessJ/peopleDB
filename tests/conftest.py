"""Shared fixtures. `dav_server` boots a throwaway local Radicale instance for
live CardDAV tests (marker: live) — never a production server. `make_dav_server`
lets a test own (and kill) its own instance for unreachability scenarios."""

import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn_radicale(tmp_path_factory):
    port = _free_port()
    storage = tmp_path_factory.mktemp("radicale-storage")
    htpasswd = tmp_path_factory.mktemp("radicale-auth") / "htpasswd"
    htpasswd.write_text("testuser:anything\n")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "radicale",
            "--server-hosts", f"127.0.0.1:{port}",
            "--auth-type", "htpasswd",
            "--auth-htpasswd-filename", str(htpasswd),
            "--auth-htpasswd-encryption", "plain",
            "--storage-filesystem-folder", str(storage),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            httpx.get(base_url, timeout=1)
            break
        except httpx.TransportError:
            if proc.poll() is not None:
                raise RuntimeError("radicale exited during startup")
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("radicale did not come up in time")

    # Create an addressbook collection for the test user.
    mkcol_body = (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        '<mkcol xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav">'
        "<set><prop>"
        "<resourcetype><collection/><CR:addressbook/></resourcetype>"
        "<displayname>Test Contacts</displayname>"
        "</prop></set></mkcol>"
    )
    resp = httpx.request(
        "MKCOL",
        f"{base_url}/testuser/contacts/",
        content=mkcol_body,
        headers={"Content-Type": "application/xml"},
        auth=("testuser", "anything"),
    )
    assert resp.status_code in (201, 207), resp.text

    return {
        "base_url": base_url,
        "username": "testuser",
        "password": "anything",
        "process": proc,
    }


@pytest.fixture(scope="session")
def dav_server(tmp_path_factory):
    server = _spawn_radicale(tmp_path_factory)
    yield server
    server["process"].terminate()
    server["process"].wait(timeout=5)


@pytest.fixture
def make_dav_server(tmp_path_factory):
    spawned = []

    def factory():
        server = _spawn_radicale(tmp_path_factory)
        spawned.append(server)
        return server

    yield factory
    for server in spawned:
        if server["process"].poll() is None:
            server["process"].terminate()
            server["process"].wait(timeout=5)
