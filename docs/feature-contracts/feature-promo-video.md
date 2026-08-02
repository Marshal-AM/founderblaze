# Feature — Promo Video (Production)

Paid A2MCP service: `POST /v1/services/promo-video/jobs` → Temporal workflow → **Backblaze B2 MP4 URL**.

List price: **$2.99** per call. SLA: **15 minutes**.

**Defaults:** `duration` **10**, `resolution` **720p**.

**Runtime (Python / Genblaze):** `founderblaze.promo_video` + FastAPI + Temporal.

Vendors: **Google Gemini** (Google Search grounding for research + script) + **Segmind Seedance 2.0** (video) + **Backblaze B2** (final MP4).

---

## Sample input

```json
{
  "input": {
    "product_url": "https://linear.app",
    "duration": 10,
    "resolution": "720p"
  },
  "callback_url": "https://example.com/webhooks/founderblaze",
  "priority": "normal"
}
```

| Field | Required | Notes |
|---|---|---|
| `input.product_url` | yes | Product site to promo |
| `input.duration` | no | Seedance: **4** \| **5** \| **6** \| **8** \| **10** (default) \| **12** \| **15** |
| `input.resolution` | no | 480p \| **720p** (default) \| 1080p \| 4k |

**Input schema (code):** `PromoVideoInput` in `founderblaze.core`.

---

## Pipeline phases (Genblaze)

| Phase | Provider | Does |
|---|---|---|
| research | `ProductResearchProvider` | Gemini + **Google Search grounding** → `product_brief.json` |
| script | `ScriptProvider` | Gemini creative director (TS `script.ts` prompt) → `seedance_prompt` |
| video | `SeedanceProvider` | Segmind Seedance 2.0 submit + poll → local `promo.mp4` |
| sink | B2 | Upload final MP4 |

---

## Live CLI smoke test

```bash
uv run --package founderblaze-promo-video founderblaze-promo-video-live \
  --product-url "https://linear.app" \
  --duration 10 \
  --resolution 720p \
  --no-b2
```

### Env keys

| Key | Role |
|---|---|
| `GEMINI_API_KEY` | Grounded research + script |
| `GEMINI_TEXT_MODEL` | Prefer grounding-capable model |
| `SEGMIND_API_KEY` | Seedance 2.0 video generation |
| `B2_*` | Final MP4 upload (skip with `--no-b2`) |

---

## Code map

| Area | Path |
|---|---|
| Schema | `founderblaze.core` → `PromoVideoInput` |
| Pipeline | `founderblaze.promo_video` |
| Seedance client | `founderblaze.promo_video.seedance_provider` |
| Workflow | `apps/worker` → `PromoVideoWorkflow` |
| Package | `packages/founderblaze` → `founderblaze.promo_video` |
| Provenance | [genblaze-provenance.md](../genblaze-provenance.md) (pointer sidecar beside MP4) |
