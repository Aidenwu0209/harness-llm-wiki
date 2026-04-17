from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from tests.fixtures.build_fixtures import _build_dual_column_pdf, _build_simple_pdf


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "download_and_verify_papers.py"


def _run_download_and_verify(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _make_manifest(manifest_path: Path, pdf_paths: list[Path]) -> None:
    papers = []
    for index, pdf_path in enumerate(pdf_paths, start=1):
        papers.append(
            {
                "id": f"paper_{index:02d}",
                "title": f"Paper {index}",
                "filename": f"{index:02d}_{pdf_path.name}",
                "pdf_url": pdf_path.resolve().as_uri(),
            },
        )

    manifest = {
        "name": "local_test_set",
        "description": "Local PDFs exposed through file:// URLs for smoke testing.",
        "papers": papers,
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def test_download_and_verify_runs_end_to_end_from_file_manifest(tmp_path: Path) -> None:
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    alpha = source_dir / "alpha.pdf"
    beta = source_dir / "beta.pdf"
    alpha.write_bytes(_build_simple_pdf())
    beta.write_bytes(_build_dual_column_pdf())

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, [alpha, beta])

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest",
        str(manifest_path),
        "--outdir",
        str(outdir),
    )

    assert result.returncode == 0, result.stderr or result.stdout

    summary_json = outdir / "summary.json"
    summary_md = outdir / "summary.md"
    assert summary_json.exists()
    assert summary_md.exists()

    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["totals"]["selected_papers"] == 2
    assert payload["totals"]["download_success_count"] == 2
    assert payload["totals"]["verify_processed_count"] == 2
    assert payload["verification"]["summary_json_path"] is not None

    for item in payload["files"]:
        assert item["download"]["status"] in ("downloaded", "reused")
        assert Path(item["download"]["file_path"]).exists()
        assert item["verify"] is not None
        assert item["verify"]["artifacts"]["wiki_pages"]


def test_download_and_verify_respects_max_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    alpha = source_dir / "alpha.pdf"
    beta = source_dir / "beta.pdf"
    gamma = source_dir / "gamma.pdf"
    alpha.write_bytes(_build_simple_pdf())
    beta.write_bytes(_build_simple_pdf())
    gamma.write_bytes(_build_simple_pdf())

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, [alpha, beta, gamma])

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest",
        str(manifest_path),
        "--outdir",
        str(outdir),
        "--max-files",
        "1",
    )

    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    assert payload["totals"]["selected_papers"] == 1
    assert len(payload["files"]) == 1
    assert payload["files"][0]["filename"].startswith("01_")


# ---------------------------------------------------------------------------
# US-006: Coverage counters in download-and-verify outputs
# ---------------------------------------------------------------------------


def test_us006_download_and_verify_includes_coverage_counters(tmp_path: Path) -> None:
    """AC1: download-and-verify summary.json must include explicit coverage counters."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    alpha = source_dir / "alpha.pdf"
    beta = source_dir / "beta.pdf"
    alpha.write_bytes(_build_simple_pdf())
    beta.write_bytes(_build_dual_column_pdf())

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, [alpha, beta])

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
    )
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "manifest_total" in totals
    assert "selected_paper_count" in totals
    assert "downloaded_paper_count" in totals
    assert "verified_paper_count" in totals

    assert totals["manifest_total"] == 2
    assert totals["selected_paper_count"] == 2
    assert totals["downloaded_paper_count"] == 2
    assert totals["verified_paper_count"] == 2


def test_us006_download_and_verify_partial_batch_coverage(tmp_path: Path) -> None:
    """AC3: partial batch must show subset coverage clearly."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    alpha = source_dir / "alpha.pdf"
    beta = source_dir / "beta.pdf"
    gamma = source_dir / "gamma.pdf"
    alpha.write_bytes(_build_simple_pdf())
    beta.write_bytes(_build_simple_pdf())
    gamma.write_bytes(_build_simple_pdf())

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, [alpha, beta, gamma])

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
        "--max-files", "1",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert totals["manifest_total"] == 3
    assert totals["selected_paper_count"] == 1
    assert totals["downloaded_paper_count"] == 1
    assert totals["verified_paper_count"] == 1

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "## Sample Coverage" in md_text
    assert "Manifest total: **3**" in md_text
    assert "Selected for this run: **1**" in md_text


def test_us006_download_and_verify_markdown_includes_sample_coverage(tmp_path: Path) -> None:
    """AC2: markdown must render Sample Coverage section."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    alpha = source_dir / "alpha.pdf"
    alpha.write_bytes(_build_simple_pdf())

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, [alpha])

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
    )
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "## Sample Coverage" in md_text
    assert "Manifest total" in md_text
    assert "Selected for this run" in md_text
    assert "Downloaded successfully" in md_text
    assert "Verified" in md_text
