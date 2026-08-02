# Brand kit — name + brief → zipped logo / assets / fonts kit

## Endpoint

`POST /v1/services/brand-kit/jobs`

```json
{
  "input": {
    "brand_name": "Solace",
    "description": "calm meditation app, minimalist, organic, wellness",
    "pick": 0
  }
}
```

## Runtime (Python / Genblaze)

Live path: `founderblaze.brand_kit` + FastAPI + Temporal.

One Genblaze `Pipeline`:

1. `AnalyzeProvider` — `genblaze_google.chat` (concepts + Google Fonts allowlist)
2. `LogoConceptsProvider` — `GeminiImageProvider` (`GEMINI_IMAGE_MODEL`)
3. `PaletteProvider` — palette from chosen logo
4. `FontsProvider` — Google Fonts TTF download + CSS/HTML
5. `VisualsProvider` — palette + typography specimen PNGs
6. `IconsProvider` — favicons / app icons
7. `BannerProvider` — multimodal Gemini image banners (logo reference)
8. `ZipProvider` → `ObjectStorageSink` on **Backblaze B2**

Artifact: `brand_kit_zip` (`application/zip`) with B2 URL.

## Env

- `GEMINI_API_KEY` (required)
- `GEMINI_TEXT_MODEL` (default `gemini-2.0-flash`)
- `GEMINI_IMAGE_MODEL` (default `gemini-2.5-flash-image`)
- `B2_*` for zip upload
- Optional `BRANDKIT_STEP_DELAY_MS` between image calls

## Local live-run

```bash
uv run --package founderblaze-brand-kit founderblaze-brand-kit-live \
  --brand-name 'Solace' \
  --description 'calm meditation app, minimalist wellness' \
  --no-b2
```

## Result

Poll `GET /v1/jobs/:id`. On success, `artifacts[]` includes a `brand_kit_zip` with `url` plus Genblaze provenance fields (`canonical_hash`, `sidecar_object_key`, …). See [genblaze-provenance.md](../genblaze-provenance.md).
