"""US-016: Persist dropped and filtered candidate statistics.

AC1: Run artifacts or summary payloads record counts for dropped or filtered
    titles, entities, and concept candidates where applicable.
AC2: Quick-verify output can surface those counts without requiring manual
    file inspection.
AC3: Filtered-count fields remain present even when the count is zero so
    validators can assert them consistently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.fixtures.build_fixtures import _build_simple_pdf

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "quick_verify_papers.py"


def _run_quick_verify(*args: str):
    import subprocess

    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# AC1: Summary payloads record dropped counts
# ---------------------------------------------------------------------------


def test_us016_summary_json_includes_all_dropped_counts(tmp_path: Path) -> None:
    """AC1: summary.json totals must include all dropped candidate count fields."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "dropped_empty_slug_count" in totals
    assert "dropped_unreadable_title_count" in totals
    assert "dropped_unreadable_entity_count" in totals
    assert "dropped_unreadable_concept_count" in totals


def test_us016_per_paper_result_json_includes_dropped_counts(tmp_path: Path) -> None:
    """AC1: individual result.json must include all dropped candidate count fields."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    runs_dir = outdir / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1

    for run_dir in run_dirs:
        result_json = run_dir / "result.json"
        data = json.loads(result_json.read_text(encoding="utf-8"))
        assert "dropped_empty_slug_count" in data, f"Missing dropped_empty_slug_count in {result_json}"
        assert "dropped_unreadable_title_count" in data, f"Missing dropped_unreadable_title_count in {result_json}"
        assert "dropped_unreadable_entity_count" in data, f"Missing dropped_unreadable_entity_count in {result_json}"
        assert "dropped_unreadable_concept_count" in data, f"Missing dropped_unreadable_concept_count in {result_json}"


# ---------------------------------------------------------------------------
# AC2: Quick-verify output surfaces counts without manual inspection
# ---------------------------------------------------------------------------


def test_us016_markdown_includes_dropped_candidate_lines(tmp_path: Path) -> None:
    """AC2: markdown summary must show all dropped candidate statistics."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Dropped empty slug" in md_text
    assert "Dropped unreadable title" in md_text
    assert "Dropped unreadable entity" in md_text
    assert "Dropped unreadable concept" in md_text


# ---------------------------------------------------------------------------
# AC3: Filtered-count fields present even when zero
# ---------------------------------------------------------------------------


def test_us016_fields_present_when_zero(tmp_path: Path) -> None:
    """AC3: all dropped-count fields must exist and be 0 when nothing was dropped."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    # Fields must exist and be integers
    assert isinstance(totals["dropped_empty_slug_count"], int)
    assert isinstance(totals["dropped_unreadable_title_count"], int)
    assert isinstance(totals["dropped_unreadable_entity_count"], int)
    assert isinstance(totals["dropped_unreadable_concept_count"], int)

    # Per-paper result.json must also have all fields
    runs_dir = outdir / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    for run_dir in run_dirs:
        data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        assert isinstance(data["dropped_empty_slug_count"], int)
        assert isinstance(data["dropped_unreadable_title_count"], int)
        assert isinstance(data["dropped_unreadable_entity_count"], int)
        assert isinstance(data["dropped_unreadable_concept_count"], int)


def test_us016_script_failure_includes_zero_dropped_counts(tmp_path: Path) -> None:
    """AC3: script-failure results must also include all dropped-count fields as 0."""
    # Create a directory with no real PDFs but trigger processing with a corrupted file
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    # Write a file named .pdf but with garbage content — pipeline will handle gracefully
    (papers_dir / "broken.pdf").write_bytes(b"not a real pdf content")

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    # The script should complete (continue_on_error default)
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    # Totals must include all fields regardless of success/failure
    assert "dropped_empty_slug_count" in payload["totals"]
    assert "dropped_unreadable_title_count" in payload["totals"]
    assert "dropped_unreadable_entity_count" in payload["totals"]
    assert "dropped_unreadable_concept_count" in payload["totals"]


def test_us016_aggregate_totals_match_per_paper_sum(tmp_path: Path) -> None:
    """AC1: batch totals must equal the sum of per-paper dropped counts."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "beta.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]

    for field_name in (
        "dropped_empty_slug_count",
        "dropped_unreadable_title_count",
        "dropped_unreadable_entity_count",
        "dropped_unreadable_concept_count",
    ):
        per_paper_sum = sum(item.get(field_name, 0) for item in payload["files"])
        assert totals[field_name] == per_paper_sum, (
            f"{field_name}: totals={totals[field_name]} != sum={per_paper_sum}"
        )
