from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from genblaze_core.models.manifest import Manifest
from genblaze_core.models.run import Run
from genblaze_core.models.step import Step
from genblaze_core.pipeline.result import PipelineResult

from founderblaze.core.storage.provenance import (
    merge_provenance,
    pick_primary_local_path,
    finalize_run_provenance,
    _resolve_mode,
)


def test_merge_provenance_copies_fields() -> None:
    art = {"type": "report_pdf", "url": "https://example.com/a.pdf", "object_key": "k"}
    prov = {
        "canonical_hash": "abc",
        "manifest_key": "m/key.json",
        "manifest_url": "https://example.com/m.json",
        "sidecar_object_key": "k.genblaze.json",
        "sidecar_url": "https://example.com/k.genblaze.json",
        "provenance_verified": True,
        "embed_method": "sidecar",
    }
    merged = merge_provenance(art, prov)
    assert merged["type"] == "report_pdf"
    assert merged["canonical_hash"] == "abc"
    assert merged["provenance_verified"] is True
    assert merged["sidecar_object_key"] == "k.genblaze.json"


def test_resolve_mode_auto() -> None:
    assert _resolve_mode("auto", Path("x.pdf")) == "sidecar"
    assert _resolve_mode("auto", Path("x.zip")) == "sidecar"
    assert _resolve_mode("auto", Path("x.mp4")) == "pointer"
    assert _resolve_mode("auto", Path("x.png")) == "pointer"
    assert _resolve_mode("sidecar", Path("x.mp4")) == "sidecar"
    assert _resolve_mode("pointer", Path("x.pdf")) == "pointer"


def test_pick_primary_local_path_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    step = SimpleNamespace(
        assets=[
            SimpleNamespace(
                url=pdf.resolve().as_uri(),
                media_type="application/pdf",
                metadata={"kind": "competitor_research_pdf"},
            )
        ]
    )
    result = SimpleNamespace(run=SimpleNamespace(steps=[step]))
    found = pick_primary_local_path(result, kind="pdf")
    assert found is not None
    assert found.name == "report.pdf"
    assert found.is_file()


def test_finalize_run_provenance_writes_sidecar(tmp_path: Path) -> None:
    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    step = Step(provider="test", model="test-model", prompt="hello")
    run = Run(steps=[step], tenant_id="t1", project_id="p1")
    manifest = Manifest.from_run(run)
    manifest.manifest_uri = "https://example.com/manifests/run.json"
    result = PipelineResult(run, manifest)

    prov = finalize_run_provenance(
        result,
        sink=None,
        primary_local_path=pdf,
        object_key=None,
        upload_sidecar=False,
        mode="sidecar",
    )
    sidecar = pdf.with_suffix(pdf.suffix + ".genblaze.json")
    assert sidecar.is_file()
    assert prov["canonical_hash"] == manifest.canonical_hash
    assert prov["embed_method"] in {"sidecar", "pointer"}
    assert prov["local_sidecar_path"] == str(sidecar)
    assert prov["provenance_verified"] is True
