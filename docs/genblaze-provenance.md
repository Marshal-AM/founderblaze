# Genblaze provenance (FounderBlaze)

Every Genblaze service closes the hash ↔ storage ↔ verify loop after `Pipeline.run(sink=…)`:

1. `sink.read_manifest(run, verify=True)` — re-read the B2 manifest and check integrity
2. `result.save(local_deliverable)` — write a sidecar next to the primary file
   - **PDF / ZIP** → full sidecar (`.pdf.genblaze.json` / `.zip.genblaze.json`)
   - **MP4 / PNG** → pointer sidecar (`canonical_hash` + `manifest_uri`)
3. Upload the sidecar to B2 beside the deliverable key
4. Return provenance fields on the primary job artifact

Canonical asset bytes on B2 are **not** overwritten after embed (keeps pre-embed `asset.sha256` valid).

## Artifact fields

```json
{
  "type": "pdf_report",
  "url": "https://…",
  "object_key": "founderblaze/…/report.pdf",
  "mime_type": "application/pdf",
  "canonical_hash": "…",
  "manifest_key": "founderblaze/…/manifests/….json",
  "manifest_url": "https://…",
  "sidecar_object_key": "founderblaze/…/report.pdf.genblaze.json",
  "sidecar_url": "https://…",
  "provenance_verified": true,
  "embed_method": "sidecar"
}
```

Insight chart PNGs (outreach / social / competitor) may also appear as `insight_chart` artifacts with their own pointer sidecars.

## Verify smoke

After a live run, download the sidecar JSON (or manifest) and check the hash:

```powershell
# PDF services — sidecar is full canonical JSON
uv run --package founderblaze-core python -c "
from pathlib import Path
import json
from genblaze_core.models.manifest import parse_manifest
text = Path('report.pdf.genblaze.json').read_text(encoding='utf-8')
m = parse_manifest(json.loads(text))
print('verify_hash', m.verify_hash())
print('hash', m.canonical_hash)
"

# MP4 pointer sidecar — fetch full manifest via manifest_uri, then:
#   genblaze extract video.mp4.genblaze.json
#   genblaze verify <manifest.json>
```

Or use the Genblaze CLI against an embedded/pointer media file when available:

```bash
genblaze verify path/to/file.mp4
```

## Unit test

```powershell
uv run --with pytest --package founderblaze pytest packages/founderblaze/tests/test_provenance.py -v
```
