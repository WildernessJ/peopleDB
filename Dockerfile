# syntax=docker/dockerfile:1
#
# Multi-stage build for peopleDB (Python 3.12 / FastAPI / uv).
# Build:  docker build -t peopledb .
# Run:    see README "Running with Docker".

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Resolve and install dependencies into .venv first, using only the lockfiles,
# so this layer is cached across source-only changes. --frozen fails the build
# if uv.lock is out of date rather than silently drifting.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Then add the project source and install the package itself.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

# Non-root runtime user; owns the writable data dir.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

# Put the project's virtualenv on PATH so the `peopledb` entry point resolves.
ENV PATH="/app/.venv/bin:$PATH"

# SQLite cache lives on a volume so it survives container recreation. It's a
# disposable mirror of the CardDAV server, but keeping it avoids a full re-sync
# on every restart. WAL/shm sidecar files land alongside it in /data.
ENV PEOPLEDB_DB_PATH=/data/peopledb-cache.db
VOLUME /data

USER app
EXPOSE 8000

# main() runs uvicorn on 0.0.0.0:8000. PEOPLEDB_DAV_URL must be supplied at run
# time; see README for the full env-var list.
CMD ["peopledb"]
