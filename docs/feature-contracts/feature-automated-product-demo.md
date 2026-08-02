# Feature — Automated Product Demo Video (Production)

Paid A2MCP service: `POST /v1/services/automated-product-demo/jobs` → Temporal workflow → narrated **MP4** (Supabase public or signed URL).

List price: **$4.99** per call (see `docs/pricing/pricing.md`).

**Runtime requirements:** Postgres (`DATABASE_URL`), Temporal (`TEMPORAL_ADDRESS`), orchestrator worker, Supabase Storage, Firecrawl, Gemini, Deepgram TTS, ffmpeg/ffprobe (static binaries bundled).

---

## Sample input

```json
{
  "input": {
    "website_url": "https://surveys.free/google-forms-alternative/",
    "script": "Create a Birthday RSVP form with name, email, and attendance fields, then show the share link."
  },
  "callback_url": "https://example.com/webhooks/founderforge",
  "priority": "normal"
}
```

| Field | Required | Notes |
|---|---|---|
| `input.website_url` | yes | Target product URL already open when the demo starts |
| `input.script` | yes | Natural-language demo script guiding browser steps + narration |
| `callback_url` | no | Optional webhook POSTed when job completes / fails |
| `priority` | no | Accepted (`low` \| `normal` \| `high`); shared Temporal task queue today |

**Input schema (code):** `AutomatedProductDemoInputSchema` in `packages/schemas` — `website_url` + `script`.

**Headers**

- `Content-Type: application/json`
- `X-Idempotency-Key: <unique>` (recommended)
---

## Expected output

### Immediate create response (`202 Accepted`)

```json
{
  "job_id": "9f3c2a1b-…",
  "list_price_usd": 4.99,
  "eta_seconds": 1800,
  "status_url": "/v1/jobs/9f3c2a1b-…",
  "status": "queued"
}
```

`eta_seconds` = SLA × 60 (30 min → 1800).

### Completed job (`GET /v1/jobs/{job_id}`)

```json
{
  "id": "9f3c2a1b-…",
  "service": "automated-product-demo",
  "status": "completed",
  "list_price_usd": 4.99,
  "step": "upload",
  "artifacts": [
    {
      "type": "video",
      "url": "https://….supabase.co/storage/v1/object/public/demos/product-demos/….mp4",
      "object_key": "product-demos/….mp4",
      "mime_type": "video/mp4"
    }
  ],
  "cost_breakdown": [
    { "vendor": "llm", "operation": "plan", "amount_usd": 0.01 },
    { "vendor": "browser", "operation": "record", "amount_usd": 0.5 },
    { "vendor": "tts", "operation": "narrate", "amount_usd": 0.05 },
    { "vendor": "media", "operation": "assemble", "amount_usd": 0.01 },
    { "vendor": "storage", "operation": "upload", "amount_usd": 0.01 }
  ],
  "created_at": "…",
  "updated_at": "…"
}
```

**What the client gets:** the video artifact (+ costs). Intermediate plan/steps and temp media are **not** returned on the job record.

Jobs live in **Postgres**. Execution runs in the **Temporal orchestrator worker**.

---

## Production flow

```
Caller
  → API Gateway (pay + validate + INSERT jobs)
  → Temporal start automatedProductDemoWorkflow
  → Orchestrator worker activity runAutomatedProductDemoActivity:
       plan → record → narrate → assemble → upload
       (setJobStep around phases; one durable activity for v1)
  → UPDATE jobs completed + optional callback_url
  ← Client polls GET /v1/jobs/:id
```

**Pipeline phases** (Genblaze `Pipeline` of SyncProviders)

1. **plan** — `PlanProvider` / Gemini → JSON plan text Asset  
2. **record** — `RecordProvider` / Firecrawl + Playwright CDP → silent screencast video Asset  
3. **narrate** — `LMNTProvider` → narration audio Asset  
4. **assemble** — `FFmpegCompositor` mux (`input_from=[0,1]`) → final MP4  
5. **upload** — `ObjectStorageSink` → Backblaze B2; job stores `object_key` + resolved URL

Firecrawl `stopInteraction` / session close always runs on success, error, or cancel.

---

## Production stack

| Concern | Provider | Env |
|---|---|---|
| Planner | Gemini (`GEMINI_TEXT_MODEL`) via Genblaze | `GEMINI_API_KEY` |
| Browser + screencast | Firecrawl interact + CDP | `FIRECRAWL_API_KEY` |
| TTS | LMNT (`LMNT_VOICE`, default `lily`) | `LMNT_API_KEY` |
| Mux | ffmpeg (`FFmpegCompositor`) | — |
| Object store | Backblaze B2 via `genblaze-s3` | `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`, `B2_REGION`, optional `B2_PUBLIC_URL_BASE` |
| Job store | Postgres | `DATABASE_URL` |
| Durable jobs | Temporal (queue `founderblaze`) | `TEMPORAL_ADDRESS`, `TEMPORAL_TASK_QUEUE` |
| HTTP A2MCP | FastAPI (`apps/api`) | `PUBLIC_API_BASE_URL` |

---

## How to run

```bash
# 1) Postgres + Temporal (e.g. docker-compose.smoke.yml)
# 2) Env: DATABASE_URL, TEMPORAL_*, FIRECRAWL_API_KEY, GEMINI_API_KEY,
#    LMNT_API_KEY, B2_*

uv sync --all-packages
uv run --package founderblaze-worker founderblaze-worker
uv run --package founderblaze-api founderblaze-api

curl -s -X POST http://localhost:4021/v1/services/automated-product-demo/jobs \
  -H 'content-type: application/json' \
  -H 'x-idempotency-key: apd-1' \
  -d '{"input":{"website_url":"https://surveys.free/google-forms-alternative/","script":"Create a Birthday RSVP form…"}}'
```

Live CLI (same Genblaze pipeline, outside Temporal):

```bash
uv run --package founderblaze-apd founderblaze-apd-live \
  --url 'https://surveys.free/google-forms-alternative/' \
  --script 'Create a Birthday RSVP form…'
```

---

## Failure modes

| Failure | Behavior |
|---|---|
| Invalid input | 400 on create |
| Temporal unreachable | job → `failed` (`temporal_enqueue_failed:…`) |
| Missing Firecrawl / Gemini / LMNT / B2 | activity fails → job `failed` |
| Firecrawl session / interact race | warm-up retries; session always closed |
| ffmpeg / odd dimensions | even-dimension scale filter; else job `failed` |
| Upload failure | job `failed` |

---

## Code map

| Step | Path |
|---|---|
| HTTP A2MCP | `apps/api` |
| Durable jobs | `packages/founderblaze` → `founderblaze.core.jobs` |
| Temporal worker | `apps/worker` |
| Genblaze pipeline | `packages/founderblaze` → `founderblaze.apd.pipeline` |
| Plan / record providers | `founderblaze.apd.plan_provider`, `record_provider`, `browser` |
| B2 sink helpers | `founderblaze.core.storage.b2` |
| Provenance | [genblaze-provenance.md](../genblaze-provenance.md) (pointer sidecar beside MP4) |
