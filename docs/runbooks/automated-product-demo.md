# Runbook — Automated Product Demo (Python / Genblaze)

Narrated MP4 from `{ website_url, script }` via Genblaze Pipeline:

`PlanProvider` (Gemini) → `RecordProvider` (Firecrawl + Playwright) → `LMNTProvider` → `FFmpegCompositor` → Backblaze B2 (`ObjectStorageSink`).

Live runtime: **FounderBlaze Python** (`apps/api` + `apps/worker`). The Node APD service / gateway path is retired.

Contract: `docs/feature-contracts/feature-automated-product-demo.md`

---

## Prerequisites

1. Copy `env.example` → `.env` and fill:
   - `FIRECRAWL_API_KEY`, `GEMINI_API_KEY`, `LMNT_API_KEY`
   - `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET` (+ optional `B2_PUBLIC_URL_BASE`)
   - `DATABASE_URL`, `TEMPORAL_*` (task queue `founderblaze`)
2. `uv sync --all-packages`
3. Infra: `docker compose -f infra/docker/docker-compose.smoke.yml up -d`  
   (or `docker-compose.python.yml` — see `env.example`)
4. `ffmpeg` on PATH; Playwright browsers: `uv run playwright install chromium`

---

## Terminals

```bash
uv run --package founderblaze-api founderblaze-api
uv run --package founderblaze-worker founderblaze-worker
```

---

## Service-only smoke (bypass Temporal)

```bash
uv run --package founderblaze-apd founderblaze-apd-live \
  --url 'https://surveys.free/google-forms-alternative/' \
  --script 'Create a Birthday RSVP form with name, email, and attendance fields.'
```

Expect JSON with `artifacts[0].url` on B2 and a Genblaze `manifest_hash`.

---

## Protocol smoke

```bash
curl -s http://localhost:4021/health
curl -s http://localhost:4021/v1/discovery
curl -s -X POST http://localhost:4021/v1/services/automated-product-demo/jobs \
  -H 'content-type: application/json' \
  -d '{"input":{"website_url":"https://linear.app","script":"Show homepage and pricing."}}'
curl -s http://localhost:4021/v1/jobs/<job_id>
```
