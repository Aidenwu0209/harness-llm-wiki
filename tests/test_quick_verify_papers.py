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


# ---------------------------------------------------------------------------
# US-002: Classify gate-blocked runs as quality-blocked outcomes
# ---------------------------------------------------------------------------

# Import the pure classification function for direct unit testing.
sys.path.insert(0, str(REPO_ROOT))
from scripts.quick_verify_papers import _classify_verdict  # noqa: E402
from scripts.quick_verify_papers import _is_knowledge_sparse  # noqa: E402


def test_us002_gate_passed_false_classified_as_quality_blocked() -> None:
    """AC1: gate.passed=false must yield quality_blocked verdict."""
    item = {
        "run_status": "completed",
        "gate": {"passed": False, "decision": "blocked", "reasons": ["quality_score_below_threshold"]},
        "review_status": None,
        "counts": {"wiki_pages_exported": 3},
    }
    assert _classify_verdict(item) == "quality_blocked"


def test_us002_gate_blocked_even_with_exported_wiki_pages() -> None:
    """AC1: gate-blocked papers remain quality_blocked even when wiki pages exist."""
    item = {
        "run_status": "completed",
        "gate": {"passed": False, "decision": "blocked", "reasons": []},
        "review_status": "approved",
        "counts": {"wiki_pages_exported": 10},
    }
    assert _classify_verdict(item) == "quality_blocked"


def test_us002_gate_blocked_excluded_from_usable_wiki_ready_tally() -> None:
    """AC2: usable_wiki_ready_count must not include gate-blocked papers."""
    from collections import Counter

    items = [
        # This one should be usable_wiki_ready: gate passed, wiki exported
        {"run_status": "completed", "gate": {"passed": True}, "review_status": None, "counts": {"wiki_pages_exported": 3}},
        # These should be quality_blocked: gate failed
        {"run_status": "completed", "gate": {"passed": False}, "review_status": None, "counts": {"wiki_pages_exported": 5}},
        {"run_status": "completed", "gate": {"passed": False}, "review_status": "approved", "counts": {"wiki_pages_exported": 2}},
    ]
    for item in items:
        item["verdict"] = _classify_verdict(item)

    verdict_counts = Counter(item["verdict"] for item in items)
    assert verdict_counts.get("usable_wiki_ready", 0) == 1
    assert verdict_counts.get("quality_blocked", 0) == 2


def test_us002_per_paper_payload_preserves_gate_info(tmp_path: Path) -> None:
    """AC3: per-paper result preserves gate.decision and gate.reasons for blocked runs."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    for item in payload["files"]:
        # gate section must always exist with passed, decision, reasons
        assert "gate" in item, f"Missing gate section for {item['file_name']}"
        gate = item["gate"]
        assert "passed" in gate, f"Missing gate.passed for {item['file_name']}"
        assert "decision" in gate, f"Missing gate.decision for {item['file_name']}"
        assert "reasons" in gate, f"Missing gate.reasons for {item['file_name']}"


def test_us002_gate_passed_none_not_treated_as_blocked() -> None:
    """Edge case: gate.passed=None (gate never reached) should not be quality_blocked."""
    item = {
        "run_status": "completed",
        "gate": {"passed": None, "decision": None, "reasons": []},
        "review_status": None,
        "counts": {"wiki_pages_exported": 0},
    }
    # None means gate stage never reached — should be pipeline_runnable, not quality_blocked
    assert _classify_verdict(item) == "pipeline_runnable"


# ---------------------------------------------------------------------------
# US-003: Classify pending-review runs as non-deliverable results
# ---------------------------------------------------------------------------


def test_us003_pending_review_not_usable_wiki_ready() -> None:
    """AC1: review_status=pending must NOT be classified as usable_wiki_ready."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": "pending",
        "counts": {"wiki_pages_exported": 5},
    }
    assert _classify_verdict(item) != "usable_wiki_ready"
    assert _classify_verdict(item) == "quality_blocked"


def test_us003_pending_review_counted_separately_in_batch_summary(tmp_path: Path) -> None:
    """AC2: pending_review_count must appear as a separate counter in batch summary."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "pending_review_count" in totals, "Missing pending_review_count in batch totals"
    assert isinstance(totals["pending_review_count"], int)


def test_us003_per_paper_shows_verdict_and_review_status_together() -> None:
    """AC3: per-paper payload must include both verdict and review_status fields."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": "pending",
        "counts": {"wiki_pages_exported": 3},
    }
    verdict = _classify_verdict(item)
    assert verdict == "quality_blocked"
    # The per-paper dict carries both fields simultaneously
    assert "review_status" in item
    assert item["review_status"] == "pending"


def test_us003_markdown_includes_review_status_column(tmp_path: Path) -> None:
    """AC3: markdown summary must include Review Status column header."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Review Status" in md_text, "Missing Review Status column in markdown summary"
    assert "Pending review" in md_text, "Missing Pending review count in markdown summary"


# ---------------------------------------------------------------------------
# US-004: Mark knowledge-sparse runs from empty extracted knowledge
# ---------------------------------------------------------------------------


def test_us004_all_zero_counts_marked_knowledge_sparse() -> None:
    """AC1: entities=0, claims=0, relations=0 → knowledge_sparse=True."""
    item = {
        "counts": {"entities": 0, "claims": 0, "relations": 0},
    }
    assert _is_knowledge_sparse(item) is True


def test_us004_non_zero_entities_not_knowledge_sparse() -> None:
    """AC1: having at least some entities means NOT knowledge_sparse."""
    item = {
        "counts": {"entities": 1, "claims": 0, "relations": 0},
    }
    assert _is_knowledge_sparse(item) is False


def test_us004_knowledge_sparse_counter_in_batch_summary(tmp_path: Path) -> None:
    """AC2: batch summary must include knowledge_sparse_count."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "knowledge_sparse_count" in totals, "Missing knowledge_sparse_count in batch totals"
    assert isinstance(totals["knowledge_sparse_count"], int)


def test_us004_knowledge_sparse_coexists_with_verdict() -> None:
    """AC3: knowledge_sparse signal is observable alongside the verdict tier."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": None,
        "counts": {"entities": 0, "claims": 0, "relations": 0, "wiki_pages_exported": 5},
    }
    verdict = _classify_verdict(item)
    ks = _is_knowledge_sparse(item)
    # Knowledge-sparse does not change the verdict
    assert verdict in _VALID_VERDICTS
    # But the sparse signal is still True
    assert ks is True


def test_us004_knowledge_sparse_in_per_paper_result_json(tmp_path: Path) -> None:
    """AC1+AC3: per-paper result.json must include knowledge_sparse field."""
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
        assert "knowledge_sparse" in data, f"Missing knowledge_sparse in {result_json}"
        assert isinstance(data["knowledge_sparse"], bool)


def test_us004_markdown_includes_knowledge_sparse_count(tmp_path: Path) -> None:
    """AC2: markdown summary must show Knowledge sparse line."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Knowledge sparse" in md_text, "Missing Knowledge sparse in markdown summary"
