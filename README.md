# peopleDB

A Cardhop-style web client for a **CardDAV** contacts server (e.g. [Baikal](https://sabre.io/baikal/)):
browse, search, add/edit contacts, manage groups, relationships, and birthdays — from any browser.
The CardDAV server stays canonical; peopleDB keeps a disposable local cache for speed.

Python / FastAPI / HTMX. See `docs/DECISIONS/ADR-0001-python-fastapi-htmx.md` for the stack decision
and `specs/2026-07-13-peopledb-v1-design.md` for the v1 design.

## Features

- **Sign in with your CardDAV account** — no separate user database; the server's ACLs decide
  what each household member sees.
- **Search as you type** across names, org, emails, phones, and notes (SQLite FTS5 cache).
- **Add / edit / delete contacts** — write-through to the server with etag conflict detection;
  concurrent edits are surfaced, never overwritten. Unrendered vCard properties (photos,
  social profiles, anything custom) survive edits untouched.
- **Interact**: `mailto:` / `tel:` / `sms:` / maps links on every relevant field.
- **Groups**: Apple-style `KIND=group` member-list cards — compatible with macOS/iOS
  Contacts and Cardhop syncing against the same server.
- **Relationships**: Apple `X-ABRELATEDNAMES`, navigable when the related person is a contact.
- **Birthdays**: upcoming view plus a tokened ICS feed URL to subscribe from any calendar app.
- **Degraded mode**: if the server is unreachable, cached data stays browsable (with a
  staleness banner); writes fail loudly and are never queued.

## Running

```sh
uv sync
PEOPLEDB_DAV_URL=https://dav.example.org/dav.php \
PEOPLEDB_SECRET_KEY=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())') \
uv run peopledb
```

### Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `PEOPLEDB_DAV_URL` | yes | Base URL of the CardDAV server (e.g. Baikal's `/dav.php`). |
| `PEOPLEDB_SECRET_KEY` | no | Fernet key encrypting session credentials at rest. **Empty → an ephemeral key is generated at startup, so every restart logs all users out.** Set a fixed key to keep sessions across restarts. |
| `PEOPLEDB_DB_PATH` | no | SQLite cache path (default `peopledb-cache.db`). Safe to delete; it's a mirror. |
| `PEOPLEDB_SYNC_INTERVAL` | no | Background refresh interval in seconds (default `300`). |
| `PEOPLEDB_WRITE_ADDRESSBOOK` | no | Which addressbook new contacts/groups are written to, matched by displayname or path segment (default `default`). Falls back to the first discovered if no match. |
| `PEOPLEDB_SECURE_COOKIES` | no | `0` to drop the `Secure` cookie flag for plain-HTTP localhost dev. Default (`1`) requires HTTPS. |

Never commit server URLs or credentials.

### Running with Docker

Images are built and published to GitHub Container Registry on every merge to `main`
(`ghcr.io/wildernessj/peopledb`) — see
[`docs/DECISIONS/ADR-0005-ghcr-github-actions-deploy.md`](docs/DECISIONS/ADR-0005-ghcr-github-actions-deploy.md).
Tags: `:latest` (tip of `main`), `:vX.Y.Z` (marked releases), `:sha-<short>` (any build, for pinning).
The package is **private**, so pull requires a one-time login with a read-only token
(`docker login ghcr.io -u <github-user> -p <PAT with read:packages>`).

```sh
docker run -d --name peopledb -p 8000:8000 \
  -v peopledb-data:/data \
  -e PEOPLEDB_DAV_URL=https://dav.example.org/dav.php \
  -e PEOPLEDB_SECRET_KEY=$(docker run --rm ghcr.io/wildernessj/peopledb:latest python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())') \
  ghcr.io/wildernessj/peopledb:latest
```

Then open `http://<host>:8000`. Notes:

- The SQLite cache lives in the `/data` volume (`PEOPLEDB_DB_PATH` is preset to
  `/data/peopledb-cache.db`); the named volume keeps it across restarts.
- Set a fixed `PEOPLEDB_SECRET_KEY` (as above) so sessions survive restarts —
  omit it and every restart logs all users out.
- Serving over plain HTTP (no TLS in front)? Add `-e PEOPLEDB_SECURE_COOKIES=0`,
  or the session cookie won't be sent and login will appear to fail.
- Images are `linux/amd64`. To build locally instead of pulling: `docker build -t peopledb .`
  (add `--platform linux/amd64` when building on Apple Silicon for an amd64 host).

See the env-var table above for the rest.

#### Unraid

`unraid/peopledb.xml` is a Docker-tab template — add it via **Add Container** (or drop it in
`/boot/config/plugins/dockerMan/templates-user/`), `docker login ghcr.io` once so the host can pull
the private image, fill `PEOPLEDB_DAV_URL` and a fixed `PEOPLEDB_SECRET_KEY`, and start. A new
`:latest` then shows "update ready" in the Docker tab; roll back by pointing the repository at a
`:sha-…` or `:vX.Y.Z` tag.

Two things that bite on a fresh Unraid deploy:

- **The `/data` (appdata) path must be writable by uid/gid `999`.** The container runs as the
  non-root `app` user (`999:999`). Unraid auto-creates a new bind path as `root`, so the app crashes
  on first boot with `sqlite3.OperationalError: unable to open database file`. Fix once:
  `chown -R 999:999 /mnt/user/appdata/peopledb`.
- **The default host port `8000` is a common collision** (Paperless-ngx, others publish it). If
  `docker` reports `Bind for 0.0.0.0:8000 failed: port is already allocated`, pick a free host port in
  the template's *WebUI Port* field — the container port stays `8000`.
- **Fronting it with a reverse proxy?** Put the container on the *same Docker network as the proxy*
  (not the default `bridge`) so the proxy can resolve it by container name, then proxy to
  `peopledb:8000` and set `PEOPLEDB_SECURE_COOKIES=1` (TLS terminates at the proxy).

## Development

```sh
uv run pytest            # unit tests
uv run pytest -m live    # end-to-end tests against a throwaway local Radicale
```
