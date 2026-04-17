from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.fixtures.build_fixtures import _build_dual_column_pdf, _build_simple_pdf


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "quick_verify_papers.py"


def _run_quick_verify(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_quick_verify_writes_summary_and_exports_wiki_pages(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "beta.pdf").write_bytes(_build_dual_column_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))

    assert result.returncode == 0, result.stderr or result.stdout

    summary_json = outdir / "summary.json"
    summary_md = outdir / "summary.md"
    assert summary_json.exists()
    assert summary_md.exists()

    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["totals"]["pdfs_discovered"] == 2
    assert payload["totals"]["pdfs_selected"] == 2
    assert len(payload["files"]) == 2
    assert payload["totals"]["success_count"] >= 1

    for item in payload["files"]:
        wiki_pages = item["artifacts"]["wiki_pages"]
        assert wiki_pages, f"No wiki pages exported for {item['file_name']}"
        for wiki_page in wiki_pages:
            assert Path(wiki_page).exists()


def test_quick_verify_respects_pattern_and_max_files(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "01_attention.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "02_bert.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "03_clip.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(
        str(papers_dir),
        "--outdir",
        str(outdir),
        "--pattern",
        "0*_*.pdf",
        "--max-files",
        "1",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    assert payload["totals"]["pdfs_discovered"] == 3
    assert payload["totals"]["pdfs_selected"] == 1
    assert len(payload["files"]) == 1
    assert payload["files"][0]["file_name"] == "01_attention.pdf"


# ---------------------------------------------------------------------------
# US-001: Structured verdict tiers
# ---------------------------------------------------------------------------

_VALID_VERDICTS = {"pipeline_runnable", "quality_blocked", "usable_wiki_ready"}


def test_quick_verify_includes_verdict_field_per_paper(tmp_path: Path) -> None:
    """Each per-paper result must have a verdict drawn from the three-tier set."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    for item in payload["files"]:
        assert "verdict" in item, f"Missing verdict field for {item['file_name']}"
        assert item["verdict"] in _VALID_VERDICTS, (
            f"Unexpected verdict '{item['verdict']}' for {item['file_name']}"
        )


def test_quick_verify_summary_json_includes_verdict_tier_counts(tmp_path: Path) -> None:
    """Batch summary.json must include verdict tier counters in totals."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "pipeline_runnable_count" in totals
    assert "quality_blocked_count" in totals
    assert "usable_wiki_ready_count" in totals
    assert totals["pipeline_runnable_count"] + totals["quality_blocked_count"] + totals["usable_wiki_ready_count"] == totals["pdfs_processed"]


def test_quick_verify_per_file_result_json_includes_verdict(tmp_path: Path) -> None:
    """Individual run result.json files must also include the verdict field."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    # Find the result.json in the run directory
    runs_dir = outdir / "runs"
    assert runs_dir.exists()
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1

    for run_dir in run_dirs:
        result_json = run_dir / "result.json"
        assert result_json.exists(), f"Missing result.json in {run_dir}"
        data = json.loads(result_json.read_text(encoding="utf-8"))
        assert "verdict" in data, f"Missing verdict in {result_json}"
        assert data["verdict"] in _VALID_VERDICTS
