# Social listening — Reddit engagement pack PDF

## Endpoint

`POST /v1/services/social-listening/jobs`

```json
{
  "input": {
    "product_url": "https://example.com",
    "product_name": "Example App",
    "max_posts": 5
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `product_url` | yes | Product site to research |
| `product_name` | no | Fallback if scrape fails |
| `max_posts` | no | Cap recommendations (1–20) |
| `live` | no | Deprecated / ignored — no auto-posting |

## Runtime (Python / Genblaze)

Live path: `founderblaze.social_listening` + FastAPI + Temporal.

One Genblaze `Pipeline`:

1. `ProductDiscoverProvider` — httpx (+ optional Jina) + `genblaze_google.chat` product profile
2. `ThreadDiscoverProvider` — Gemini need-statement + **Tavily Research** Reddit threads
3. `DraftComplianceProvider` — Tavily `suggested_reply` or Gemini draft + compliance
4. `CompileReportProvider` — Playwright HTML → PDF → `ObjectStorageSink` on **Backblaze B2**

Artifacts: `pdf_report` (primary) + `reddit_thread` URLs. List price **$1.00**, SLA **15 min**.

Empty packs fail (`reddit_no_threads` / `reddit_no_drafts`) — no blank PDF.

No Groq. No Supabase. No ReddAPI / auto-posting.

## Env

- `GEMINI_API_KEY` (required)
- `GEMINI_TEXT_MODEL` (default `gemini-2.0-flash`)
- `TAVILY_API_KEY` (required)
- `TAVILY_REDDIT_MODE=research` (default)
- `TAVILY_RESEARCH_MODEL` (default `mini`)
- Optional `JINA_API_KEY` for scrape fallback
- `B2_*` for PDF upload (skip with `--no-b2` for local smoke)

## Local live-run

```bash
uv run --package founderblaze-social-listening founderblaze-social-listening-live \
  --product-url 'https://example.com' \
  --max-posts 3 \
  --no-b2
```

## Result

Poll `GET /v1/jobs/:id`. On success, `artifacts[]` includes `pdf_report` with `url` (plus Genblaze provenance fields), optional `insight_chart` images, and `reddit_thread` entries. See [genblaze-provenance.md](../genblaze-provenance.md).
