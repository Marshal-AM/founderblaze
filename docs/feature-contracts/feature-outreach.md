# Outreach — investor intelligence PDF

## Endpoint

`POST /v1/services/outreach/jobs`

```json
{
  "input": {
    "website_url": "https://example.com",
    "sheet_url": "https://cdn.example/revenue.xlsx"
  }
}
```

## Runtime (Python / Genblaze)

Live path: `founderblaze.outreach` + FastAPI + Temporal.

One Genblaze `Pipeline`:

1. `SheetDownloadProvider` — HTTP download (or local path for CLI)
2. `WebsiteAnalyzeProvider` — Exa contents + `genblaze_google.chat` product summary
3. `RevenueAnalyzeProvider` — Gemini on workbook extract
4. `InvestorFinderProvider` — Gemini craft/synth + Exa search
5. `PortfolioBenchmarkProvider` — Gemini + Exa portfolio comps
6. `PartnerContactsProvider` — Gemini + Exa partner shortlist
7. `ContactEnrichProvider` — Exa person enrichment
8. `CompileReportProvider` — Playwright HTML → PDF → `ObjectStorageSink` on **Backblaze B2**

Artifact: `pdf_report` (`application/pdf`) with B2 URL. List price **$1.00**, SLA **15 min**.

No Groq. No Firecrawl. Website and all web research use Exa; LLM via Gemini only.

## Env

- `GEMINI_API_KEY` (required)
- `GEMINI_TEXT_MODEL` (default `gemini-2.0-flash`)
- `EXA_SEARCH_API_KEY` (or `EXA_API_KEY`)
- `B2_*` for PDF upload (skip with `--no-b2` for local smoke)

## Local live-run

```bash
uv run --package founderblaze-outreach founderblaze-outreach-live \
  --website-url 'https://example.com' \
  --sheet-path './path/to/revenue.xlsx' \
  --no-b2
```

## Result

Poll `GET /v1/jobs/:id`. On success, `artifacts[]` includes a `pdf_report` with `url` plus Genblaze provenance fields (`canonical_hash`, `manifest_key`, `sidecar_object_key`, `provenance_verified`). See [genblaze-provenance.md](../genblaze-provenance.md).
