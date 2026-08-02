# syntax=docker/dockerfile:1
# Build from repo root:
#   docker build -f apps/api/Dockerfile -t founderblaze-api .
FROM ghcr.io/astral-sh/uv:0.8.4 AS uv

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv

# Workspace metadata first (better layer cache)
COPY pyproject.toml uv.lock ./
COPY packages/founderblaze/pyproject.toml packages/founderblaze/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/agent/pyproject.toml apps/agent/

# Ignore path genblaze pins — resolve published packages from PyPI
RUN uv sync --no-dev --no-sources --package founderblaze-api --no-install-project

COPY packages/founderblaze/src packages/founderblaze/src
COPY apps/api/src apps/api/src

RUN uv sync --no-dev --no-sources --package founderblaze-api

EXPOSE 4021
CMD ["founderblaze-api"]
