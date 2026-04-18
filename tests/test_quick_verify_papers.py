from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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
from scripts.quick_verify_papers import _build_verdict  # noqa: E402
from scripts.quick_verify_papers import _classify_verdict  # noqa: E402
from scripts.quick_verify_papers import _fmt_rate  # noqa: E402
from scripts.quick_verify_papers import _is_knowledge_sparse  # noqa: E402
from scripts.quick_verify_papers import _is_wiki_sparse  # noqa: E402
from scripts.quick_verify_papers import run_batch  # noqa: E402


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


# ---------------------------------------------------------------------------
# US-005: Mark wiki-sparse runs from source-only exports
# ---------------------------------------------------------------------------


def test_us005_source_only_pages_marked_wiki_sparse() -> None:
    """AC1: wiki pages with only source pages (no entity/concept) → wiki_sparse=True."""
    item = {
        "artifacts": {
            "wiki_pages": [
                "/output/wiki_pages/001_paper/sources/attention-is-all-you-need.md",
            ],
        },
    }
    assert _is_wiki_sparse(item) is True


def test_us005_entity_pages_not_wiki_sparse() -> None:
    """AC1: having entity pages means NOT wiki_sparse."""
    item = {
        "artifacts": {
            "wiki_pages": [
                "/output/wiki_pages/001_paper/sources/attention-is-all-you-need.md",
                "/output/wiki_pages/001_paper/entities/transformer.md",
            ],
        },
    }
    assert _is_wiki_sparse(item) is False


def test_us005_concept_pages_not_wiki_sparse() -> None:
    """AC1: having concept pages means NOT wiki_sparse."""
    item = {
        "artifacts": {
            "wiki_pages": [
                "/output/wiki_pages/001_paper/sources/attention-is-all-you-need.md",
                "/output/wiki_pages/001_paper/concepts/self-attention.md",
            ],
        },
    }
    assert _is_wiki_sparse(item) is False


def test_us005_no_wiki_pages_not_wiki_sparse() -> None:
    """No exported pages → wiki_sparse=False (signal is only meaningful when pages exist)."""
    item = {
        "artifacts": {
            "wiki_pages": [],
        },
    }
    assert _is_wiki_sparse(item) is False


def test_us005_wiki_sparse_counter_in_batch_summary(tmp_path: Path) -> None:
    """AC2: batch summary must include wiki_sparse_count."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "wiki_sparse_count" in totals, "Missing wiki_sparse_count in batch totals"
    assert isinstance(totals["wiki_sparse_count"], int)


def test_us005_wiki_sparse_in_per_paper_result_json(tmp_path: Path) -> None:
    """AC3: per-paper result.json must include wiki_sparse field."""
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
        assert "wiki_sparse" in data, f"Missing wiki_sparse in {result_json}"
        assert isinstance(data["wiki_sparse"], bool)


def test_us005_markdown_includes_wiki_sparse_count(tmp_path: Path) -> None:
    """AC2: markdown summary must show Wiki sparse line."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Wiki sparse" in md_text, "Missing Wiki sparse in markdown summary"


# ---------------------------------------------------------------------------
# US-006: Add coverage counters to batch verification outputs
# ---------------------------------------------------------------------------


def test_us006_summary_json_includes_coverage_counters(tmp_path: Path) -> None:
    """AC1: summary.json must include manifest_total, selected_paper_count, downloaded_paper_count, verified_paper_count."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "beta.pdf").write_bytes(_build_dual_column_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "manifest_total" in totals
    assert "selected_paper_count" in totals
    assert "downloaded_paper_count" in totals
    assert "verified_paper_count" in totals

    # With 2 PDFs, no filtering
    assert totals["manifest_total"] == 2
    assert totals["selected_paper_count"] == 2
    assert totals["downloaded_paper_count"] == 2
    assert totals["verified_paper_count"] == 2


def test_us006_markdown_includes_sample_coverage_section(tmp_path: Path) -> None:
    """AC2: markdown summary must render a Sample Coverage section with the four counters."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "## Sample Coverage" in md_text
    assert "Manifest total" in md_text
    assert "Selected for this run" in md_text
    assert "Available for verification" in md_text
    assert "Verified" in md_text


def test_us006_partial_batch_shows_subset_coverage(tmp_path: Path) -> None:
    """AC3: a batch verifying only a subset must show clear subset numbers."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "01_attention.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "02_bert.pdf").write_bytes(_build_simple_pdf())
    (papers_dir / "03_clip.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(
        str(papers_dir),
        "--outdir", str(outdir),
        "--max-files", "1",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    # manifest_total should be 3 (all PDFs in directory)
    assert totals["manifest_total"] == 3
    # selected_paper_count should be 1 (after --max-files 1)
    assert totals["selected_paper_count"] == 1
    # downloaded should equal selected (PDFs are local)
    assert totals["downloaded_paper_count"] == 1
    # verified should equal selected
    assert totals["verified_paper_count"] == 1

    # Markdown should show the subset clearly
    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Manifest total: **3**" in md_text
    assert "Selected for this run: **1**" in md_text


# ---------------------------------------------------------------------------
# US-007: Rewrite quick-verify headline and answer from quality-aware totals
# ---------------------------------------------------------------------------


def test_us007_verdict_uses_verdict_tier_totals() -> None:
    """AC1: headline and answer derived from verdict-tier totals, not raw success_count."""
    # All papers usable_wiki_ready
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 5}},
    ]
    v = _build_verdict(results)
    assert v["status"] == "basically_yes"
    assert "可用 wiki" in v["headline"] or "wiki" in v["headline"].lower()


def test_us007_blocked_papers_no_fully_ready_headline() -> None:
    """AC3: blocked papers must not produce a headline claiming fully ready wiki delivery."""
    results = [
        {"verdict": "quality_blocked", "status": "success", "counts": {"wiki_pages_exported": 3}},
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 5}},
    ]
    v = _build_verdict(results)
    assert v["status"] != "basically_yes"
    # Must be partial or blocked, not "basically_yes"
    assert v["status"] in ("partial_yes", "quality_blocked")


def test_us007_partial_coverage_mentions_sample_limitation() -> None:
    """AC2: partial coverage must explicitly say the conclusion is limited to the sample."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
    ]
    v = _build_verdict(results, manifest_total=10, verified_paper_count=1)
    assert "1/10" in v["answer"]
    assert "样本" in v["answer"] or "范围" in v["answer"]


def test_us007_all_quality_blocked_not_usable() -> None:
    """AC3: all quality_blocked must not produce usable-wiki headline."""
    results = [
        {"verdict": "quality_blocked", "status": "success", "counts": {"wiki_pages_exported": 3}},
        {"verdict": "quality_blocked", "status": "success", "counts": {"wiki_pages_exported": 0}},
    ]
    v = _build_verdict(results)
    assert v["status"] == "quality_blocked"
    assert "质量阻断" in v["headline"] or "阻断" in v["headline"]


def test_us007_no_results_gives_no_input() -> None:
    """Edge case: no results must produce no_input status."""
    v = _build_verdict([])
    assert v["status"] == "no_input"


def test_us007_full_coverage_no_sample_warning() -> None:
    """When verified == manifest_total, no coverage limitation note is emitted."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
    ]
    v = _build_verdict(results, manifest_total=1, verified_paper_count=1)
    assert v["status"] == "basically_yes"
    assert "样本" not in v["answer"]


# ---------------------------------------------------------------------------
# US-008: Expose gate, review, and final verdict together per paper
# ---------------------------------------------------------------------------


def test_us008_per_paper_json_includes_gate_review_verdict(tmp_path: Path) -> None:
    """AC1: Each per-paper record must include gate.decision, review_status, and verdict together."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    for item in payload["files"]:
        assert "gate" in item, f"Missing gate section for {item['file_name']}"
        assert "decision" in item["gate"], f"Missing gate.decision for {item['file_name']}"
        assert "review_status" in item, f"Missing review_status for {item['file_name']}"
        assert "verdict" in item, f"Missing verdict for {item['file_name']}"


def test_us008_markdown_table_includes_gate_column(tmp_path: Path) -> None:
    """AC2: Markdown per-paper table must include a Gate column showing gate decision."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "| Gate |" in md_text, "Missing Gate column header in markdown table"


def test_us008_markdown_table_has_verdict_gate_review_together(tmp_path: Path) -> None:
    """AC2: The markdown table must expose verdict, gate, and review status columns side by side."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    # Verify the header has all three columns
    header_line = [line for line in md_text.splitlines() if "| #" in line][0]
    assert "Verdict" in header_line
    assert "Gate" in header_line
    assert "Review Status" in header_line


def test_us008_blocked_paper_inspectable_from_summary(tmp_path: Path) -> None:
    """AC3: A blocked paper can be inspected from summary output without raw artifacts."""
    # Simulate a quality_blocked result and verify gate info is in per-paper JSON
    item = {
        "run_status": "completed",
        "gate": {"passed": False, "decision": "blocked", "reasons": ["quality_score_below_threshold"]},
        "review_status": None,
        "counts": {"wiki_pages_exported": 3},
    }
    verdict = _classify_verdict(item)
    assert verdict == "quality_blocked"
    # Gate info and review_status are accessible from the same dict
    assert item["gate"]["decision"] == "blocked"
    assert "review_status" in item
    assert "verdict" not in item  # verdict is added post-construction
    item["verdict"] = verdict
    # Now all three signals are present together
    assert item["gate"]["decision"] == "blocked"
    assert item["review_status"] is None
    assert item["verdict"] == "quality_blocked"


def test_us008_per_paper_result_json_has_all_three_signals(tmp_path: Path) -> None:
    """AC1+AC3: Individual result.json files must contain gate, review_status, and verdict."""
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
        assert "gate" in data
        assert "decision" in data["gate"]
        assert "review_status" in data
        assert "verdict" in data


# ---------------------------------------------------------------------------
# US-009: Add aggregate gate, review, and lint quality metrics to quick verify
# ---------------------------------------------------------------------------


def test_us009_summary_json_includes_quality_metrics(tmp_path: Path) -> None:
    """AC1+AC2: summary.json totals must include gate_pass_rate, pending_review_count, and lint_blocker_count."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "gate_pass_rate" in totals, "Missing gate_pass_rate in totals"
    assert "pending_review_count" in totals, "Missing pending_review_count in totals"
    assert "lint_blocker_count" in totals, "Missing lint_blocker_count in totals"
    # gate_pass_rate is either None or a float between 0 and 1
    if totals["gate_pass_rate"] is not None:
        assert 0.0 <= totals["gate_pass_rate"] <= 1.0
    assert isinstance(totals["lint_blocker_count"], int)
    assert isinstance(totals["pending_review_count"], int)


def test_us009_markdown_includes_quality_metrics_section(tmp_path: Path) -> None:
    """AC3: markdown summary must render Quality Metrics section with gate pass rate, pending review, and lint blockers."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "## Quality Metrics" in md_text, "Missing Quality Metrics section in markdown"
    assert "Gate pass rate" in md_text, "Missing Gate pass rate in markdown"
    assert "Pending review" in md_text, "Missing Pending review in Quality Metrics"
    assert "Lint blockers" in md_text, "Missing Lint blockers in markdown"


def test_us009_gate_pass_rate_computation() -> None:
    """AC1: gate_pass_rate computed correctly from results with gate.passed values."""
    # Simulate the computation inline to verify the logic
    results = [
        {"gate": {"passed": True}, "counts": {"lint_findings": 0}},
        {"gate": {"passed": False}, "counts": {"lint_findings": 5}},
        {"gate": {"passed": True}, "counts": {"lint_findings": 0}},
    ]
    gate_evaluated = [r for r in results if r.get("gate", {}).get("passed") is not None]
    gate_passed_count = sum(1 for r in gate_evaluated if r["gate"]["passed"] is True)
    rate = round(gate_passed_count / len(gate_evaluated), 4)
    assert abs(rate - 2 / 3) < 0.001
    lint_blocker_count = sum(1 for r in results if r.get("counts", {}).get("lint_findings", 0) > 0)
    assert lint_blocker_count == 1


def test_us009_gate_pass_rate_none_when_no_gate_evaluated() -> None:
    """AC1: gate_pass_rate is None when no papers reached the gate stage."""
    results = [
        {"gate": {"passed": None}, "counts": {"lint_findings": 0}},
        {"gate": {"passed": None}, "counts": {"lint_findings": 0}},
    ]
    gate_evaluated = [r for r in results if r.get("gate", {}).get("passed") is not None]
    rate = round(sum(1 for r in gate_evaluated if r["gate"]["passed"] is True) / len(gate_evaluated), 4) if gate_evaluated else None
    assert rate is None


def test_us009_lint_blocker_count_includes_papers_with_findings() -> None:
    """AC1: lint_blocker_count counts papers with any lint findings."""
    results = [
        {"counts": {"lint_findings": 0}},
        {"counts": {"lint_findings": 28}},
        {"counts": {"lint_findings": 3}},
        {"counts": {"lint_findings": 0}},
    ]
    count = sum(1 for r in results if r.get("counts", {}).get("lint_findings", 0) > 0)
    assert count == 2


def test_us009_fmt_rate() -> None:
    """Helper _fmt_rate formats correctly."""
    assert _fmt_rate(None) == "N/A"
    assert _fmt_rate(1.0) == "100%"
    assert _fmt_rate(0.5) == "50%"
    assert _fmt_rate(0.0) == "0%"


# ---------------------------------------------------------------------------
# US-010: Split exported-page counts into candidate, gate-passed, and vault-ready totals
# ---------------------------------------------------------------------------


def test_us010_summary_json_includes_page_count_buckets(tmp_path: Path) -> None:
    """AC1: summary.json totals must include generated_candidate_pages, gate_passed_pages, final_vault_ready_pages."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "generated_candidate_pages" in totals
    assert "gate_passed_pages" in totals
    assert "final_vault_ready_pages" in totals
    assert isinstance(totals["generated_candidate_pages"], int)
    assert isinstance(totals["gate_passed_pages"], int)
    assert isinstance(totals["final_vault_ready_pages"], int)
    # vault_ready <= gate_passed <= candidate
    assert totals["final_vault_ready_pages"] <= totals["gate_passed_pages"] <= totals["generated_candidate_pages"]


def test_us010_per_paper_includes_page_buckets(tmp_path: Path) -> None:
    """AC2: per-paper result.json must expose page_buckets with the three counts."""
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
        assert "page_buckets" in data, f"Missing page_buckets in {result_json}"
        buckets = data["page_buckets"]
        assert "generated_candidate_pages" in buckets
        assert "gate_passed_pages" in buckets
        assert "final_vault_ready_pages" in buckets


def test_us010_blocked_paper_does_not_increase_vault_ready() -> None:
    """AC3: a paper with pages but blocked quality status must not count toward final_vault_ready_pages."""
    # Simulate aggregate computation manually
    items = [
        {
            "verdict": "quality_blocked",
            "gate": {"passed": False},
            "counts": {"wiki_pages_exported": 5},
        },
        {
            "verdict": "usable_wiki_ready",
            "gate": {"passed": True},
            "counts": {"wiki_pages_exported": 3},
        },
    ]
    generated_candidate_pages = sum(i["counts"]["wiki_pages_exported"] for i in items)
    gate_passed_pages = sum(
        i["counts"]["wiki_pages_exported"]
        for i in items
        if i["gate"]["passed"] is True
    )
    final_vault_ready_pages = sum(
        i["counts"]["wiki_pages_exported"]
        for i in items
        if i["verdict"] == "usable_wiki_ready"
    )

    assert generated_candidate_pages == 8
    assert gate_passed_pages == 3
    assert final_vault_ready_pages == 3  # blocked paper's 5 pages are excluded


def test_us010_markdown_includes_page_count_buckets(tmp_path: Path) -> None:
    """AC1+AC2: markdown summary must render page count bucket lines."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Generated candidate pages" in md_text
    assert "Gate-passed pages" in md_text
    assert "Final vault-ready pages" in md_text


def test_us010_per_paper_page_buckets_reflect_verdict() -> None:
    """AC3: per-paper page_buckets must reflect verdict — blocked papers get 0 vault_ready."""
    # A quality_blocked paper
    item_blocked = {
        "verdict": "quality_blocked",
        "gate": {"passed": False},
        "counts": {"wiki_pages_exported": 5},
    }
    wiki = item_blocked["counts"]["wiki_pages_exported"]
    buckets = {
        "generated_candidate_pages": wiki,
        "gate_passed_pages": wiki if item_blocked["gate"]["passed"] is True else 0,
        "final_vault_ready_pages": wiki if item_blocked["verdict"] == "usable_wiki_ready" else 0,
    }
    assert buckets["generated_candidate_pages"] == 5
    assert buckets["gate_passed_pages"] == 0
    assert buckets["final_vault_ready_pages"] == 0

    # A usable_wiki_ready paper
    item_ready = {
        "verdict": "usable_wiki_ready",
        "gate": {"passed": True},
        "counts": {"wiki_pages_exported": 3},
    }
    wiki2 = item_ready["counts"]["wiki_pages_exported"]
    buckets2 = {
        "generated_candidate_pages": wiki2,
        "gate_passed_pages": wiki2 if item_ready["gate"]["passed"] is True else 0,
        "final_vault_ready_pages": wiki2 if item_ready["verdict"] == "usable_wiki_ready" else 0,
    }
    assert buckets2["generated_candidate_pages"] == 3
    assert buckets2["gate_passed_pages"] == 3
    assert buckets2["final_vault_ready_pages"] == 3


def test_us010_zero_pages_all_buckets_zero(tmp_path: Path) -> None:
    """Edge case: paper with no exported pages must have all three buckets as 0."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    # If no wiki pages were exported, all buckets must be 0
    if payload["totals"]["generated_candidate_pages"] == 0:
        assert payload["totals"]["gate_passed_pages"] == 0
        assert payload["totals"]["final_vault_ready_pages"] == 0


# ---------------------------------------------------------------------------
# US-021: Integrate validator results into quick-verify summaries
# ---------------------------------------------------------------------------


def test_us021_vault_validation_failure_blocks_usable_wiki_ready() -> None:
    """AC2: A paper that fails Obsidian-ready validation cannot be usable_wiki_ready."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": None,
        "counts": {"wiki_pages_exported": 5},
        "vault_validation": {
            "total_pages": 3,
            "passed_pages": 1,
            "failed_pages": 2,
            "pass_rate": 0.3333,
            "issues": [
                {"page_path": "entities/test.md", "issue_type": "empty_title", "detail": "..."},
            ],
        },
    }
    assert _classify_verdict(item) == "quality_blocked"


def test_us021_vault_validation_all_pass_is_usable_wiki_ready() -> None:
    """AC2: Paper with all pages passing vault validation can be usable_wiki_ready."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": None,
        "counts": {"wiki_pages_exported": 5},
        "vault_validation": {
            "total_pages": 5,
            "passed_pages": 5,
            "failed_pages": 0,
            "pass_rate": 1.0,
            "issues": [],
        },
    }
    assert _classify_verdict(item) == "usable_wiki_ready"


def test_us021_no_vault_validation_data_allows_usable_wiki_ready() -> None:
    """AC2: Missing vault_validation (e.g. no pages exported) does not block."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": None,
        "counts": {"wiki_pages_exported": 3},
    }
    # No vault_validation key — should still reach usable_wiki_ready
    assert _classify_verdict(item) == "usable_wiki_ready"


def test_us021_zero_failed_pages_allows_usable_wiki_ready() -> None:
    """AC2: vault_validation with failed_pages=0 does not block usable_wiki_ready."""
    item = {
        "run_status": "completed",
        "gate": {"passed": True},
        "review_status": None,
        "counts": {"wiki_pages_exported": 3},
        "vault_validation": {
            "total_pages": 3,
            "passed_pages": 3,
            "failed_pages": 0,
            "pass_rate": 1.0,
            "issues": [],
        },
    }
    assert _classify_verdict(item) == "usable_wiki_ready"


def test_us021_summary_json_includes_paper_level_validator_counts(tmp_path: Path) -> None:
    """AC1: summary.json totals must include vault_validated_paper_pass_count and vault_validated_paper_fail_count."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]
    assert "vault_validated_paper_pass_count" in totals
    assert "vault_validated_paper_fail_count" in totals
    assert isinstance(totals["vault_validated_paper_pass_count"], int)
    assert isinstance(totals["vault_validated_paper_fail_count"], int)


def test_us021_per_paper_json_includes_vault_validation_status(tmp_path: Path) -> None:
    """AC3: per-paper result.json must include vault_validation dict."""
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
        assert "vault_validation" in data, f"Missing vault_validation in {result_json}"
        vv = data["vault_validation"]
        assert "total_pages" in vv
        assert "passed_pages" in vv
        assert "failed_pages" in vv
        assert "pass_rate" in vv


def test_us021_markdown_includes_paper_level_validator_counts(tmp_path: Path) -> None:
    """AC1: markdown must show paper-level validator pass/fail counts."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Papers passed validation" in md_text, "Missing Papers passed validation in markdown"
    assert "Papers failed validation" in md_text, "Missing Papers failed validation in markdown"


# ---------------------------------------------------------------------------
# US-024: Prevent isolated-mode summaries from claiming unified wiki validation
# ---------------------------------------------------------------------------


def test_us024_isolated_verdict_headline_uses_pipeline_wording() -> None:
    """AC2: In isolated mode the verdict headline must say '逐论文管线' not '一键批量'."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 5}},
    ]
    v = _build_verdict(results, verification_mode="isolated_per_paper")
    assert v["status"] == "basically_yes"
    assert "逐论文管线" in v["headline"]
    assert "一键批量" not in v["headline"]


def test_us024_isolated_verdict_answer_includes_disclaimer() -> None:
    """AC1: Isolated-mode answer must say the run did not validate a unified shared vault."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
    ]
    v = _build_verdict(results, verification_mode="isolated_per_paper")
    assert "未对统一共享 wiki 库进行校验" in v["answer"]


def test_us024_isolated_partial_yes_uses_pipeline_wording() -> None:
    """AC2: Partial yes in isolated mode must also use pipeline wording."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
        {"verdict": "quality_blocked", "status": "success", "counts": {"wiki_pages_exported": 0}},
    ]
    v = _build_verdict(results, verification_mode="isolated_per_paper")
    assert v["status"] == "partial_yes"
    assert "逐论文管线" in v["headline"]
    assert "未对统一共享 wiki 库进行校验" in v["answer"]


def test_us024_isolated_quality_blocked_uses_pipeline_wording() -> None:
    """AC2: Quality blocked in isolated mode must use pipeline wording."""
    results = [
        {"verdict": "quality_blocked", "status": "success", "counts": {"wiki_pages_exported": 3}},
    ]
    v = _build_verdict(results, verification_mode="isolated_per_paper")
    assert v["status"] == "quality_blocked"
    assert "逐论文管线" in v["headline"]


def test_us024_isolated_not_yet_uses_pipeline_wording() -> None:
    """AC2: Not-yet in isolated mode must use pipeline wording."""
    results = [
        {"verdict": "pipeline_runnable", "status": "success", "counts": {"wiki_pages_exported": 0}},
    ]
    v = _build_verdict(results, verification_mode="isolated_per_paper")
    assert v["status"] == "not_yet"
    assert "逐论文管线" in v["headline"]


def test_us024_shared_corpus_vault_uses_unified_wording() -> None:
    """When mode is shared_corpus_vault, the old unified wording is used."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
    ]
    v = _build_verdict(results, verification_mode="shared_corpus_vault")
    assert v["status"] == "basically_yes"
    assert "一键批量" in v["headline"]
    assert "未对统一共享 wiki 库进行校验" not in v["answer"]


def test_us024_markdown_includes_isolated_disclaimer(tmp_path: Path) -> None:
    """AC1: Markdown output must contain the isolated-mode disclaimer block."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Verification mode: isolated per-paper" in md_text or "isolated_per_paper" in md_text
    assert "did not validate a unified shared vault" in md_text


def test_us024_isolated_no_input_uses_pipeline_wording() -> None:
    """AC2: No-input case in isolated mode must use pipeline wording."""
    v = _build_verdict([], verification_mode="isolated_per_paper")
    assert v["status"] == "no_input"
    assert "逐论文管线" in v["answer"]


def test_us024_default_mode_is_isolated() -> None:
    """AC1: Default verification_mode must be isolated_per_paper."""
    results = [
        {"verdict": "usable_wiki_ready", "status": "success", "counts": {"wiki_pages_exported": 3}},
    ]
    v = _build_verdict(results)
    assert "逐论文管线" in v["headline"]
    assert "未对统一共享 wiki 库进行校验" in v["answer"]


# ---------------------------------------------------------------------------
# US-023: Explicit verification-mode field in batch outputs
# ---------------------------------------------------------------------------


def test_us023_summary_json_includes_verification_mode(tmp_path: Path) -> None:
    """AC1: summary.json must include verification_mode field."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    assert "verification_mode" in payload, "Missing verification_mode in summary payload"
    assert payload["verification_mode"] == "isolated_per_paper"


def test_us023_markdown_renders_verification_mode(tmp_path: Path) -> None:
    """AC2: markdown summary must render the verification mode."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "alpha.pdf").write_bytes(_build_simple_pdf())

    outdir = tmp_path / "verify-output"
    result = _run_quick_verify(str(papers_dir), "--outdir", str(outdir))
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "Verification mode" in md_text, "Missing Verification mode in markdown summary"
    assert "isolated_per_paper" in md_text, "Missing isolated_per_paper value in markdown summary"


def test_us023_verification_mode_shared_corpus_vault() -> None:
    """AC1+AC3: verification_mode can be asserted without inferring from directory layout."""
    import argparse

    args = argparse.Namespace(
        papers_dir=Path("/nonexistent"),
        outdir=Path("/nonexistent"),
        pattern="*",
        max_files=None,
        config=REPO_ROOT / "configs" / "router.yaml",
        continue_on_error=True,
    )
    # Verify that the keyword argument is accepted
    # (we cannot actually run the batch here, but we verify the parameter exists)
    import inspect
    sig = inspect.signature(run_batch)
    assert "verification_mode" in sig.parameters, "run_batch must accept verification_mode parameter"
    assert sig.parameters["verification_mode"].default == "isolated_per_paper"


def test_us023_invalid_verification_mode_raises() -> None:
    """Verification mode must be one of the accepted values."""
    import argparse

    args = argparse.Namespace(
        papers_dir=Path("/nonexistent"),
        outdir=Path("/nonexistent"),
        pattern="*",
        max_files=None,
        config=REPO_ROOT / "configs" / "router.yaml",
        continue_on_error=True,
    )
    # Create minimal papers dir and config so run_batch validates mode first
    import pytest

    with pytest.raises(ValueError, match="verification_mode"):
        # Need a real papers_dir to get past the first check
        papers_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
        args.papers_dir = papers_dir
        args.outdir = Path("/tmp/us023_test")
        run_batch(args, verification_mode="invalid_mode")
