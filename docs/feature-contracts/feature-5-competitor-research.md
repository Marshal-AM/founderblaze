# Feature 5 — Automated Competitor Research Report (Production)

Paid A2MCP service: `POST /v1/services/competitor-research/jobs` → Temporal workflow → Genblaze Pipeline → branded **PDF** (Backblaze B2 URL).

List price: **$1.00** per call · SLA **20 minutes**.

**Runtime requirements:** Postgres (`DATABASE_URL`), Temporal (`TEMPORAL_ADDRESS`), Python worker, Backblaze B2, Gemini, Jina Reader (recommended), search provider (Serper preferred; Brave failover; DuckDuckGo last resort).

---

## Sample input

```json
{
  "input": {
    "product_name": "Notion",
    "product_url": "https://www.notion.so"
  },
  "callback_url": "https://example.com/webhooks/founderblaze",
  "priority": "normal"
}
```

| Field | Required | Notes |
|---|---|---|
| `input.product_name` | yes | Human product / company name used in search queries |
| `input.product_url` | recommended | Homepage used as ground-truth for category, features, pricing |
| `callback_url` | no | Optional webhook POSTed when job completes / fails |
| `priority` | no | Accepted (`low` \| `normal` \| `high`); shared Temporal task queue today |

**Input schema (code):** `CompetitorResearchInput` in `founderblaze.core`.

**Headers**

- `Content-Type: application/json`
- `X-Idempotency-Key: <unique>` (recommended)

---

## Expected output

### Immediate create response (`202 Accepted`)

```json
{
  "job_id": "9f3c2a1b-…",
  "list_price_usd": 1.0,
  "eta_seconds": 1200,
  "status_url": "/v1/jobs/9f3c2a1b-…",
  "status": "queued"
}
```

`eta_seconds` = SLA × 60 (20 min → 1200).

### Completed job (`GET /v1/jobs/{job_id}`)

```json
{
  "id": "9f3c2a1b-…",
  "service": "competitor-research",
  "status": "completed",
  "list_price_usd": 1.0,
  "step": "completed",
  "artifacts": [
    {
      "type": "report_pdf",
      "url": "https://….backblazeb2.com/…",
      "object_key": "competitor-research/….pdf",
      "mime_type": "application/pdf"
    }
  ],
  "created_at": "…",
  "updated_at": "…"
}
```

**What the client gets:** the PDF artifact. Intermediate agent data (competitors, feature matrix, pricing, positioning) builds the PDF but is **not** returned on the job record.

Jobs live in **Postgres**. Execution runs in the **Python Temporal worker**.

---

## Production flow

```
Caller
  → FastAPI (validate + INSERT jobs)
  → Temporal start CompetitorResearchWorkflow
  → Worker activity → Genblaze Pipeline:
       FindCompetitorsProvider
       → GatherEvidenceProvider
       → DiffFeaturesProvider
       → ScrapePricingProvider
       → BuildPositioningProvider
       → CompileReportProvider (HTML → Playwright PDF)
       → ObjectStorageSink (B2)
  → UPDATE jobs completed + optional callback_url
  ← Client polls GET /v1/jobs/:id
```

**Providers**

1. **FindCompetitors** — Serper → Brave → DDG search; Gemini ranks ≤5 peers  
2. **GatherEvidence** — Jina Reader (+ HTTP fallback) for homepage / features / pricing pages  
3. **DiffFeatures** — category-fit dimensions + matrix from vendor evidence  
4. **ScrapePricing** — public tiers / pricing model  
5. **BuildPositioning** — SWOT, deterministic price×feature map, recommendations  
6. **CompileReport** — HTML template → Playwright PDF → B2 (`kind=competitor_research_pdf`)

---

## Production stack

| Concern | Provider | Env |
|---|---|---|
| LLM | Gemini (`genblaze_google.chat`) | `GEMINI_API_KEY`, `GEMINI_TEXT_MODEL` |
| Web search | Serper → Brave → DuckDuckGo (failover) | `SERPER_API_KEY`, `BRAVE_SEARCH_API_KEY` |
| Page fetch | Jina Reader (`r.jina.ai`) → HTTP fallback | `JINA_API_KEY` |
| Evidence | Vendor homepage / features + `/pricing` / `/plans` | — |
| PDF | Playwright `page.pdf()` | Playwright Chromium |
| Object store | Backblaze B2 (presigned URL) | `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`, `B2_REGION` |
| Job store | Postgres | `DATABASE_URL` |
| Orchestration | Temporal | `TEMPORAL_ADDRESS`, `TEMPORAL_TASK_QUEUE` |

---

## How to run

```bash
# 1) Postgres + Temporal
# 2) Env: DATABASE_URL, TEMPORAL_*, GEMINI_API_KEY, JINA_API_KEY, B2_*, SERPER_API_KEY (or BRAVE)

uv sync
uv run --package founderblaze-api founderblaze-api
uv run --package founderblaze-worker founderblaze-worker

curl -s -X POST http://localhost:4021/v1/services/competitor-research/jobs \
  -H 'content-type: application/json' \
  -H 'x-idempotency-key: demo-1' \
  -d '{"input":{"product_name":"Notion","product_url":"https://www.notion.so"}}'
```

Live CLI (same pipeline, outside Temporal — PDF uploads to B2; local scratch is deleted):

```bash
uv run --package founderblaze-competitor-research founderblaze-competitor-research-live \
  --product-name "Notion" --product-url "https://www.notion.so"
```

Live implementation is Python Genblaze under `founderblaze.competitor_research`.

Primary artifact includes Genblaze provenance fields and a B2 sidecar (`*.pdf.genblaze.json`). Optional `insight_chart` artifacts carry pointer sidecars. See [genblaze-provenance.md](../genblaze-provenance.md).

---

## Failure modes

| Failure | Behavior |
|---|---|
| Invalid input | 400 on create |
| Temporal unreachable | job → `failed` (`temporal_enqueue_failed:…`) |
| Search providers all fail | activity fails → Temporal retries → job `failed` |
| Missing B2 / Gemini | activity fails → job `failed` |
| PDF / upload failure | job `failed` |

---

## Code map

| Step | Path |
|---|---|
| HTTP admission | `apps/api` |
| Durable jobs | `founderblaze.core.jobs` store |
| Temporal client | `apps/api` |
| Workflow / activity | `apps/worker` |
| Genblaze package | `founderblaze.competitor_research` |
| Package | `packages/founderblaze` → `founderblaze.competitor_research` |
