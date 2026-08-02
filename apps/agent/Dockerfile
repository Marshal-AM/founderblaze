# syntax=docker/dockerfile:1
# Build from repo root:
#   docker build -f apps/agent/Dockerfile -t founderblaze-agent .
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

COPY pyproject.toml uv.lock ./
COPY packages/founderblaze/pyproject.toml packages/founderblaze/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/agent/pyproject.toml apps/agent/

RUN uv sync --no-dev --no-sources --package founderblaze-agent --no-install-project

COPY packages/founderblaze/src packages/founderblaze/src
COPY apps/agent/src apps/agent/src

RUN uv sync --no-dev --no-sources --package founderblaze-agent

EXPOSE 4022
CMD ["founderblaze-agent"]
