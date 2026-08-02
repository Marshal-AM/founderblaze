# Railway deploy (FounderForge)

You need **4 pieces**: Railway Postgres (jobs) · Temporal · api-gateway · orchestrator.  
Supabase + vendor API keys stay external. Redis is unused — skip it.

## Exactly what to do for Temporal

Jobs Postgres ≠ Temporal. Temporal needs its own server (and usually its own DB). Pick **one**:

### Option A — Temporal Cloud (simplest ops) ✅ recommended

1. Sign up at [cloud.temporal.io](https://cloud.temporal.io), create a namespace.
2. Create an **API key**.
3. Copy the gRPC address (e.g. `us-west-2.aws.api.temporal.io:7233`) and full namespace id (`name.account`).
4. Set on **both** `api-gateway` and `orchestrator`:

```bash
TEMPORAL_ADDRESS=<region>.aws.api.temporal.io:7233
TEMPORAL_NAMESPACE=<namespace>.<account>
TEMPORAL_API_KEY=<api-key>
TEMPORAL_TLS=true
TEMPORAL_TASK_QUEUE=founderforge
```

No Temporal container on Railway. App code already supports API key + TLS via `@founderforge/temporal`.

### Option B — Self-host Temporal on Railway

1. Add a **second** Railway Postgres dedicated to Temporal (recommended), or use a separate DB name on the jobs instance.
2. New Railway service → Dockerfile path `infra/temporal/Dockerfile` (image `temporalio/auto-setup:1.25.2`).
3. Private networking only (no public HTTP). Temporal must be in the **same Railway project** as that Postgres so `*.railway.internal` resolves.
4. Parse the Postgres URL into **discrete** env vars — do **not** put the full URL in `POSTGRES_SEEDS`.

Example URL:
`postgresql://USER:PASSWORD@HOST:5432/railway`

```bash
DB=postgres12
DB_PORT=5432
# ⚠️ DB_PORT defaults to 3306 in auto-setup — you MUST set 5432 or it loops forever
POSTGRES_USER=USER
POSTGRES_PWD=PASSWORD
POSTGRES_SEEDS=HOST
# host only, e.g. postgres-xxxx.railway.internal  — NO postgresql://, NO user, NO path
```

If it still loops on `Waiting for PostgreSQL to startup`:
- `POSTGRES_SEEDS` is wrong (full URL pasted, typo, or different Railway environment)
- `DB_PORT` missing / still 3306
- Temporal service not on the same private network as Postgres

After TCP connects, if schema setup fails with SSL errors, add:
```bash
POSTGRES_TLS_ENABLED=true
POSTGRES_TLS_DISABLE_HOST_VERIFICATION=true
```

Temporal will create DBs `temporal` + `temporal_visibility` (needs CREATE privilege — Railway’s default `postgres` user is fine).

5. On **api-gateway** + **orchestrator**:

```bash
TEMPORAL_ADDRESS=<temporal-service>.railway.internal:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=founderforge
# leave TEMPORAL_API_KEY unset
```

6. Deploy Temporal **before** (or with) the apps so workers can connect.

---

## Railway services checklist

| # | Service | Dockerfile | Public? |
|---|---------|------------|---------|
| 1 | Postgres (jobs) | plugin | — |
| 2 | Temporal | `infra/temporal/Dockerfile` **or** Temporal Cloud | private / SaaS |
| 3 | api-gateway | `apps/api-gateway/Dockerfile` | **yes** |
| 4 | orchestrator | `apps/orchestrator/Dockerfile` | **no** |

### api-gateway

- Builder: Dockerfile at `apps/api-gateway/Dockerfile` (context = repo root).
- Health: `GET /health` (includes Temporal probe + oldest queued age).
- Env: `DATABASE_URL` (jobs Postgres), `TEMPORAL_*`, `PORT`, `PUBLIC_API_BASE_URL`.

### orchestrator

- Builder: Dockerfile at `apps/orchestrator/Dockerfile` (Debian + Playwright Chromium).
- Env: same `DATABASE_URL` + `TEMPORAL_*`, plus `SUPABASE_*` and all feature API keys from `env.example`.
- Give it enough memory (Playwright / ffmpeg / long activities).

### Shared

```bash
DATABASE_URL=${{Postgres.DATABASE_URL}}   # jobs DB — gateway + worker
TEMPORAL_TASK_QUEUE=founderforge          # must match on gateway + worker
```

---

## Local Docker smoke (optional)

```bash
# from repo root
docker build -f apps/api-gateway/Dockerfile -t ff-gateway .
docker build -f apps/orchestrator/Dockerfile -t ff-orchestrator .
```

---

## Verify

```bash
curl -s https://YOUR_GATEWAY/health
curl -i -X POST https://YOUR_GATEWAY/v1/services/competitor-research/jobs \
  -H 'content-type: application/json' \
  -d '{"input":{"product_name":"Linear","product_url":"https://linear.app"}}'
# expect 202 + job_id
```

If create returns `202` but job stays `queued`, Temporal address / worker / task queue is wrong.
