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


# ---------------------------------------------------------------------------
# US-011: Independent quality summary for download-and-verify
# ---------------------------------------------------------------------------


def test_us011_quality_summary_fields_in_json(tmp_path: Path) -> None:
    """AC1: summary.json includes download_success_rate, verify_success_rate, gate_pass_rate, pending_review_count."""
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
    assert "download_success_rate" in totals
    assert "verify_success_rate" in totals
    assert "gate_pass_rate" in totals
    assert "pending_review_count" in totals
    assert "usable_wiki_ready_count" in totals
    assert "quality_blocked_count" in totals
    # Download should be fully successful in this test
    assert totals["download_success_rate"] == 1.0


def test_us011_verdict_not_passthrough(tmp_path: Path) -> None:
    """AC2: top-level verdict is independently composed, not a passthrough."""
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

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    # The download-and-verify verdict should have its own structure
    verdict = payload["verdict"]
    assert "status" in verdict
    assert "headline" in verdict
    assert "answer" in verdict
    # The verdict status should be one of the quality-aware values
    assert verdict["status"] in (
        "basically_yes", "partial_yes", "quality_blocked", "not_yet",
    )


def test_us011_session_and_root_summary_both_preserve_quality_fields(tmp_path: Path) -> None:
    """AC3: both root and session summary files contain the new quality summary fields."""
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

    root_payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))

    # Find session summary.json
    sessions_dir = outdir / "sessions"
    assert sessions_dir.exists()
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    session_json = session_dirs[0] / "summary.json"
    assert session_json.exists()
    session_payload = json.loads(session_json.read_text(encoding="utf-8"))

    # Both must have the same quality summary fields
    for payload in (root_payload, session_payload):
        totals = payload["totals"]
        assert "download_success_rate" in totals
        assert "verify_success_rate" in totals
        assert "gate_pass_rate" in totals
        assert "pending_review_count" in totals


def test_us011_markdown_quality_metrics_section(tmp_path: Path) -> None:
    """Quality Metrics section must appear in markdown output."""
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
    assert "## Quality Metrics" in md_text
    assert "Download success rate" in md_text
    assert "Verify success rate" in md_text
    assert "Gate pass rate" in md_text
    assert "Pending review" in md_text


def test_us011_partial_download_quality_fields(tmp_path: Path) -> None:
    """Quality fields must be present even when using max-files (partial batch)."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    alpha = source_dir / "alpha.pdf"
    beta = source_dir / "beta.pdf"
    alpha.write_bytes(_build_simple_pdf())
    beta.write_bytes(_build_simple_pdf())

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, [alpha, beta])

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
        "--max-files", "1",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert totals["download_success_rate"] == 1.0
    assert totals["manifest_total"] == 2
    assert totals["selected_paper_count"] == 1


def test_us011_build_verdict_quality_aware() -> None:
    """Unit test: _build_verdict produces quality-aware verdict, not passthrough."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.download_and_verify_papers import _build_verdict

    # Simulate verify_payload with quality signals
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 2,
            "success_count": 2,
            "usable_wiki_ready_count": 1,
            "quality_blocked_count": 1,
            "pending_review_count": 0,
            "gate_pass_rate": 0.5,
        },
    }
    selected = [{"id": "p1"}, {"id": "p2"}]
    downloads = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
    ]

    verdict = _build_verdict(selected, downloads, verify_payload)
    # Should be partial_yes because 1/2 usable_wiki_ready with quality_blocked > 0
    assert verdict["status"] == "partial_yes"
    assert "质量阻断" in verdict["answer"]
