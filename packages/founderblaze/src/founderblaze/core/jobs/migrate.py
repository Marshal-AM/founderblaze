from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger("founderblaze.db.migrate")

JOBS_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
  id UUID PRIMARY KEY,
  service TEXT NOT NULL,
  status TEXT NOT NULL,
  input JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifacts JSONB NOT NULL DEFAULT '[]'::jsonb,
  cost_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb,
  list_price_usd DOUBLE PRECISION NOT NULL,
  error TEXT,
  callback_url TEXT,
  idempotency_key TEXT,
  eta_seconds INTEGER,
  step TEXT,
  workflow_id TEXT,
  dispatched_at TIMESTAMPTZ,
  dispatch_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS jobs_service_idempotency_uidx
  ON jobs (service, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_queued_created_at_idx
  ON jobs (created_at)
  WHERE status = 'queued';
"""

MIGRATIONS = [
    ("001_jobs", JOBS_SQL),
]


async def migrate(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              id TEXT PRIMARY KEY,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        for mid, sql in MIGRATIONS:
            exists = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE id = $1", mid
            )
            if exists:
                continue
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (id) VALUES ($1)", mid
                )
            log.info("applied migration id=%s", mid)
