from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from tests.fixtures.build_fixtures import _build_dual_column_pdf, _build_simple_pdf


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "download_and_verify_papers.py"

sys.path.insert(0, str(REPO_ROOT))
from scripts.download_and_verify_papers import _build_verdict  # noqa: E402


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


# ---------------------------------------------------------------------------
# US-023: Explicit verification-mode field in batch outputs
# ---------------------------------------------------------------------------


def test_us023_download_and_verify_includes_verification_mode(tmp_path: Path) -> None:
    """AC1: download-and-verify summary.json must include verification_mode field."""
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
    assert "verification_mode" in payload, "Missing verification_mode in download-and-verify summary"
    assert payload["verification_mode"] == "isolated_per_paper"

    # Session summary should also include it
    sessions_dir = outdir / "sessions"
    assert sessions_dir.exists()
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    session_payload = json.loads(
        (session_dirs[0] / "summary.json").read_text(encoding="utf-8"),
    )
    assert "verification_mode" in session_payload
    assert session_payload["verification_mode"] == "isolated_per_paper"


def test_us023_download_and_verify_markdown_renders_verification_mode(tmp_path: Path) -> None:
    """AC2: markdown summary must render the verification mode."""
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
    assert "Verification mode" in md_text, "Missing Verification mode in markdown summary"
    assert "isolated_per_paper" in md_text, "Missing isolated_per_paper value in markdown summary"


# ---------------------------------------------------------------------------
# US-024: Prevent isolated-mode summaries from claiming unified wiki validation
# ---------------------------------------------------------------------------


def test_us024_build_verdict_isolated_uses_pipeline_wording() -> None:
    """AC2: _build_verdict in isolated mode must use '逐论文管线' wording."""
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 2,
            "success_count": 2,
            "usable_wiki_ready_count": 2,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": 1.0,
        },
    }
    selected = [{"id": "p1"}, {"id": "p2"}]
    downloads = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
    ]

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        verification_mode="isolated_per_paper",
    )
    assert verdict["status"] == "basically_yes"
    assert "逐论文管线" in verdict["headline"]
    assert "未对统一共享 wiki 库进行校验" in verdict["answer"]


def test_us024_build_verdict_isolated_partial_uses_pipeline_wording() -> None:
    """AC2: Partial yes in isolated mode uses pipeline wording."""
    verify_payload = {
        "verdict": {"status": "partial_yes", "headline": "test", "answer": "test"},
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

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        verification_mode="isolated_per_paper",
    )
    assert verdict["status"] == "partial_yes"
    assert "逐论文管线" in verdict["headline"]
    assert "未对统一共享 wiki 库进行校验" in verdict["answer"]


def test_us024_build_verdict_shared_uses_unified_wording() -> None:
    """When mode is shared_corpus_vault, the old unified wording is used."""
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 2,
            "success_count": 2,
            "usable_wiki_ready_count": 2,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": 1.0,
        },
    }
    selected = [{"id": "p1"}, {"id": "p2"}]
    downloads = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
    ]

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        verification_mode="shared_corpus_vault",
    )
    assert verdict["status"] == "basically_yes"
    assert "一键批量" in verdict["headline"]
    assert "未对统一共享 wiki 库进行校验" not in verdict["answer"]


def test_us024_build_verdict_default_is_isolated() -> None:
    """AC1: Default verification_mode must be isolated_per_paper."""
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 1,
            "success_count": 1,
            "usable_wiki_ready_count": 1,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": 1.0,
        },
    }
    selected = [{"id": "p1"}]
    downloads = [{"status": "downloaded", "filename": "a.pdf"}]

    verdict = _build_verdict(selected, downloads, verify_payload)
    assert "逐论文管线" in verdict["headline"]
    assert "未对统一共享 wiki 库进行校验" in verdict["answer"]


def test_us024_markdown_includes_isolated_disclaimer(tmp_path: Path) -> None:
    """AC1: Markdown output must contain the isolated-mode disclaimer block."""
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
    assert "did not validate a unified shared vault" in md_text


def test_us024_build_verdict_isolated_no_downloads_uses_pipeline_wording() -> None:
    """AC2: No downloads in isolated mode must use pipeline wording."""
    selected = [{"id": "p1"}]
    downloads = [{"status": "failed", "filename": "a.pdf"}]
    verdict = _build_verdict(
        selected, downloads, None,
        verification_mode="isolated_per_paper",
    )
    assert "逐论文管线" in verdict["answer"]


def test_us024_build_verdict_isolated_quality_blocked_uses_pipeline_wording() -> None:
    """AC2: Quality blocked in isolated mode must use pipeline wording."""
    verify_payload = {
        "verdict": {"status": "quality_blocked", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 1,
            "success_count": 1,
            "usable_wiki_ready_count": 0,
            "quality_blocked_count": 1,
            "pending_review_count": 0,
            "gate_pass_rate": 0.0,
        },
    }
    selected = [{"id": "p1"}]
    downloads = [{"status": "downloaded", "filename": "a.pdf"}]

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        verification_mode="isolated_per_paper",
    )
    assert verdict["status"] == "quality_blocked"
    assert "逐论文管线" in verdict["headline"]


def test_us024_build_verdict_isolated_not_yet_uses_pipeline_wording() -> None:
    """AC2: Not-yet in isolated mode must use pipeline wording."""
    verify_payload = {
        "verdict": {"status": "not_yet", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 1,
            "success_count": 0,
            "usable_wiki_ready_count": 0,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": None,
        },
    }
    selected = [{"id": "p1"}]
    downloads = [{"status": "downloaded", "filename": "a.pdf"}]

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        verification_mode="isolated_per_paper",
    )
    assert verdict["status"] == "not_yet"
    assert "逐论文管线" in verdict["answer"]


# ---------------------------------------------------------------------------
# US-022: Obsidian-safe and readable page rates in download-and-verify
# ---------------------------------------------------------------------------


def test_us022_page_rate_fields_in_json(tmp_path: Path) -> None:
    """AC1: summary.json totals must include obsidian_safe_page_rate and readable_page_rate."""
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
    assert "obsidian_safe_page_rate" in totals, "Missing obsidian_safe_page_rate in totals"
    assert "readable_page_rate" in totals, "Missing readable_page_rate in totals"
    # Both should be present; readable_page_rate should be >= obsidian_safe_page_rate
    # (readable is a weaker criterion than Obsidian-safe)
    obs_rate = totals["obsidian_safe_page_rate"]
    read_rate = totals["readable_page_rate"]
    if obs_rate is not None and read_rate is not None:
        assert read_rate >= obs_rate, (
            f"readable_page_rate ({read_rate}) should be >= obsidian_safe_page_rate ({obs_rate})"
        )


def test_us022_page_rates_in_root_and_session_summaries(tmp_path: Path) -> None:
    """AC2: both root and session summary files contain page rate fields."""
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

    sessions_dir = outdir / "sessions"
    assert sessions_dir.exists()
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    session_json = session_dirs[0] / "summary.json"
    assert session_json.exists()
    session_payload = json.loads(session_json.read_text(encoding="utf-8"))

    for payload in (root_payload, session_payload):
        totals = payload["totals"]
        assert "obsidian_safe_page_rate" in totals
        assert "readable_page_rate" in totals
        assert "vault_validation_total_pages" in totals
        assert "vault_validation_passed_pages" in totals
        assert "vault_validation_failed_pages" in totals


def test_us022_markdown_includes_page_level_usability(tmp_path: Path) -> None:
    """AC1/AC3: markdown must include Page-Level Usability section with page rates."""
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
    assert "## Page-Level Usability" in md_text
    assert "Obsidian-safe page rate" in md_text
    assert "Readable page rate" in md_text


def test_us022_build_verdict_references_page_usability() -> None:
    """AC3: _build_verdict answer text references page-level usability."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.download_and_verify_papers import _build_verdict

    # Simulate verify_payload with page-level validation data
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 1,
            "success_count": 1,
            "usable_wiki_ready_count": 1,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": 1.0,
            "vault_pass_rate": 0.9,
            "readable_page_rate": 0.95,
            "vault_validation_total_pages": 10,
            "vault_validation_passed_pages": 9,
            "vault_validation_failed_pages": 1,
        },
    }
    selected = [{"id": "p1"}]
    downloads = [{"status": "downloaded", "filename": "a.pdf"}]

    verdict = _build_verdict(selected, downloads, verify_payload)
    assert verdict["status"] == "basically_yes"
    # Answer should reference page-level usability
    assert "页面级可用性" in verdict["answer"]
    assert "Obsidian" in verdict["answer"] or "可读率" in verdict["answer"]


def test_us022_build_verdict_partial_yes_includes_page_rates() -> None:
    """AC3: partial_yes verdict also references page-level usability."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.download_and_verify_papers import _build_verdict

    verify_payload = {
        "verdict": {"status": "partial_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 2,
            "success_count": 2,
            "usable_wiki_ready_count": 1,
            "quality_blocked_count": 1,
            "pending_review_count": 0,
            "gate_pass_rate": 0.5,
            "vault_pass_rate": 0.8,
            "readable_page_rate": 0.85,
            "vault_validation_total_pages": 10,
            "vault_validation_passed_pages": 8,
            "vault_validation_failed_pages": 2,
        },
    }
    selected = [{"id": "p1"}, {"id": "p2"}]
    downloads = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
    ]

    verdict = _build_verdict(selected, downloads, verify_payload)
    assert verdict["status"] == "partial_yes"
    # Answer should reference page-level usability when vault pages exist
    assert "页面级可用性" in verdict["answer"]


# ---------------------------------------------------------------------------
# US-027: Propagate recommended vault path and start page in summaries
# ---------------------------------------------------------------------------


def test_us027_download_and_verify_includes_recommended_vault_path(tmp_path: Path) -> None:
    """AC1: download-and-verify summary.json must include recommended_vault_path."""
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
    assert "recommended_vault_path" in payload, "Missing recommended_vault_path in download-and-verify summary"

    # When wiki pages are exported, the path should be non-None
    if payload["totals"].get("verify_wiki_output_count", 0) > 0:
        assert payload["recommended_vault_path"] is not None


def test_us027_download_and_verify_includes_recommended_start_page(tmp_path: Path) -> None:
    """AC2: download-and-verify summary.json must include recommended_start_page."""
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
    assert "recommended_start_page" in payload, "Missing recommended_start_page in download-and-verify summary"


def test_us027_download_and_verify_markdown_includes_recommended_paths(tmp_path: Path) -> None:
    """AC3: markdown summary must render recommended vault path and start page."""
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
    assert "## Recommended Paths" in md_text, "Missing Recommended Paths section in markdown"
    assert "Recommended vault path" in md_text, "Missing Recommended vault path in markdown"
    assert "Recommended start page" in md_text, "Missing Recommended start page in markdown"


def test_us027_download_and_verify_session_summary_includes_recommended_paths(tmp_path: Path) -> None:
    """AC3: both root and session summary files contain recommended path fields."""
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

    sessions_dir = outdir / "sessions"
    assert sessions_dir.exists()
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    session_payload = json.loads(
        (session_dirs[0] / "summary.json").read_text(encoding="utf-8"),
    )

    for payload in (root_payload, session_payload):
        assert "recommended_vault_path" in payload
        assert "recommended_start_page" in payload


# ---------------------------------------------------------------------------
# US-029: Session-level delivery verdict for download-and-verify
# ---------------------------------------------------------------------------


def test_us029_delivery_verdict_fully_deliverable() -> None:
    """AC1: all papers usable_wiki_ready → fully_deliverable."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
    ]
    verify_payload = {
        "files": [
            {"verdict": "usable_wiki_ready", "status": "success"},
            {"verdict": "usable_wiki_ready", "status": "success"},
        ],
    }
    dv = _delivery_verdict(download_results, verify_payload)
    assert dv["delivery_verdict"] == "fully_deliverable"
    assert "2 of 2 papers produced usable wiki" in dv["delivery_summary"]
    assert "0 papers blocked" in dv["delivery_summary"]
    assert "pipeline-runnable but not wiki-ready: 0" in dv["delivery_summary"]


def test_us029_delivery_verdict_partially_deliverable() -> None:
    """AC1: some papers usable_wiki_ready → partially_deliverable."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
        {"status": "downloaded", "filename": "c.pdf"},
    ]
    verify_payload = {
        "files": [
            {"verdict": "usable_wiki_ready", "status": "success"},
            {"verdict": "quality_blocked", "status": "success"},
            {"verdict": "pipeline_runnable", "status": "success"},
        ],
    }
    dv = _delivery_verdict(download_results, verify_payload)
    assert dv["delivery_verdict"] == "partially_deliverable"
    assert "1 of 3 papers produced usable wiki" in dv["delivery_summary"]
    assert "1 papers blocked" in dv["delivery_summary"]
    assert "pipeline-runnable but not wiki-ready: 1" in dv["delivery_summary"]


def test_us029_delivery_verdict_not_deliverable() -> None:
    """AC1: no papers usable_wiki_ready → not_deliverable."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
    ]
    verify_payload = {
        "files": [
            {"verdict": "quality_blocked", "status": "success"},
            {"verdict": "pipeline_runnable", "status": "success"},
        ],
    }
    dv = _delivery_verdict(download_results, verify_payload)
    assert dv["delivery_verdict"] == "not_deliverable"
    assert "0 of 2 papers produced usable wiki" in dv["delivery_summary"]


def test_us029_delivery_verdict_no_verify_payload() -> None:
    """Edge case: verify_payload is None → not_deliverable."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "downloaded", "filename": "a.pdf"},
    ]
    dv = _delivery_verdict(download_results, None)
    assert dv["delivery_verdict"] == "not_deliverable"


def test_us029_delivery_verdict_no_downloads() -> None:
    """Edge case: no successful downloads → not_deliverable."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "failed", "filename": "a.pdf"},
    ]
    dv = _delivery_verdict(download_results, None)
    assert dv["delivery_verdict"] == "not_deliverable"


def test_us029_delivery_verdict_blocked_paper_not_fully_deliverable() -> None:
    """AC2: blocked papers prevent fully_deliverable even when all others are ready."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
        {"status": "downloaded", "filename": "c.pdf"},
    ]
    verify_payload = {
        "files": [
            {"verdict": "usable_wiki_ready", "status": "success"},
            {"verdict": "quality_blocked", "status": "success"},
            {"verdict": "usable_wiki_ready", "status": "success"},
        ],
    }
    dv = _delivery_verdict(download_results, verify_payload)
    assert dv["delivery_verdict"] == "partially_deliverable"
    assert "1 papers blocked" in dv["delivery_summary"]


def test_us029_delivery_verdict_separates_pipeline_runnable_from_wiki_ready() -> None:
    """AC3: summary text explicitly separates pipeline-runnable from usable-wiki."""
    from scripts.download_and_verify_papers import _delivery_verdict

    download_results = [
        {"status": "downloaded", "filename": "a.pdf"},
        {"status": "downloaded", "filename": "b.pdf"},
        {"status": "downloaded", "filename": "c.pdf"},
    ]
    verify_payload = {
        "files": [
            {"verdict": "usable_wiki_ready", "status": "success"},
            {"verdict": "pipeline_runnable", "status": "success"},
            {"verdict": "pipeline_runnable", "status": "success"},
        ],
    }
    dv = _delivery_verdict(download_results, verify_payload)
    assert dv["delivery_verdict"] == "partially_deliverable"
    assert "pipeline-runnable but not wiki-ready: 2" in dv["delivery_summary"]
    assert "1 of 3 papers produced usable wiki" in dv["delivery_summary"]


def test_us029_summary_json_includes_delivery_verdict(tmp_path: Path) -> None:
    """AC1: summary.json must include delivery_verdict field."""
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
    assert "delivery_verdict" in payload, "Missing delivery_verdict in download-and-verify summary"
    dv = payload["delivery_verdict"]
    assert "delivery_verdict" in dv
    assert "delivery_summary" in dv
    assert dv["delivery_verdict"] in (
        "fully_deliverable", "partially_deliverable", "not_deliverable",
    )


def test_us029_session_summary_includes_delivery_verdict(tmp_path: Path) -> None:
    """AC1: both root and session summaries must include delivery_verdict."""
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

    sessions_dir = outdir / "sessions"
    assert sessions_dir.exists()
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    session_payload = json.loads(
        (session_dirs[0] / "summary.json").read_text(encoding="utf-8"),
    )

    for payload in (root_payload, session_payload):
        assert "delivery_verdict" in payload
        assert payload["delivery_verdict"]["delivery_verdict"] in (
            "fully_deliverable", "partially_deliverable", "not_deliverable",
        )


def test_us029_markdown_includes_delivery_verdict(tmp_path: Path) -> None:
    """AC1: markdown must include Delivery Verdict section."""
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
    assert "## Delivery Verdict" in md_text, "Missing Delivery Verdict section in markdown"
    assert "Session delivery status" in md_text, "Missing Session delivery status in markdown"
    assert "papers produced usable wiki" in md_text, "Missing delivery summary in markdown"


# ---------------------------------------------------------------------------
# US-028: Broader coverage reporting for classic-llm batch validation
# ---------------------------------------------------------------------------


def test_us028_ten_paper_manifest_coverage_counters(tmp_path: Path) -> None:
    """AC1: Batch summaries can represent coverage for a 10-paper manifest."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    pdfs = []
    for i in range(10):
        pdf = source_dir / f"paper_{i:02d}.pdf"
        pdf.write_bytes(_build_simple_pdf())
        pdfs.append(pdf)

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, pdfs)

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
        "--max-files", "3",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    payload = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
    totals = payload["totals"]

    # AC1: counters exist and represent the full manifest
    assert "manifest_total" in totals
    assert "selected_paper_count" in totals
    assert "downloaded_paper_count" in totals
    assert "verified_paper_count" in totals

    # AC2: manifest size clearly distinguished from papers processed
    assert totals["manifest_total"] == 10
    assert totals["selected_paper_count"] == 3
    assert totals["downloaded_paper_count"] == 3
    assert totals["verified_paper_count"] == 3

    # AC1: verdict is not collapsed into binary pass/fail
    verdict = payload["verdict"]
    assert verdict["status"] in (
        "basically_yes", "partial_yes", "quality_blocked", "not_yet",
    )
    # Verdict must include actual counts, not just "pass" or "fail"
    assert verdict["headline"] not in ("pass", "fail", "PASS", "FAIL")


def test_us028_partial_batch_coverage_funnel_markdown(tmp_path: Path) -> None:
    """AC3: markdown shows coverage funnel for partial batches without implying full validation."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    pdfs = []
    for i in range(10):
        pdf = source_dir / f"paper_{i:02d}.pdf"
        pdf.write_bytes(_build_simple_pdf())
        pdfs.append(pdf)

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, pdfs)

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
        "--max-files", "3",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")

    # Coverage Funnel section must be present
    assert "### Coverage Funnel" in md_text, "Missing Coverage Funnel section in markdown"

    # Funnel must show the exact numbers, not collapsed
    assert "`10` (manifest)" in md_text, "Missing manifest count in funnel"
    assert "`3` (selected)" in md_text, "Missing selected count in funnel"
    assert "`3` (downloaded)" in md_text, "Missing downloaded count in funnel"


def test_us028_partial_batch_verdict_mentions_coverage_gap() -> None:
    """AC3: _build_verdict for partial batch must note the coverage gap."""
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 3,
            "success_count": 3,
            "usable_wiki_ready_count": 3,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": 1.0,
        },
    }
    selected = [{"id": f"p{i}"} for i in range(3)]
    downloads = [
        {"status": "downloaded", "filename": f"a{i}.pdf"}
        for i in range(3)
    ]

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        manifest_total=10,
    )
    # With only 3/10 papers selected, the verdict must acknowledge partial coverage
    assert "3/10" in verdict["answer"] or "仅覆盖" in verdict["answer"] or "manifest" in verdict["answer"].lower()


def test_us028_full_batch_no_coverage_gap_note() -> None:
    """When selected == manifest_total, no partial-coverage note is emitted."""
    verify_payload = {
        "verdict": {"status": "basically_yes", "headline": "test", "answer": "test"},
        "totals": {
            "pdfs_processed": 3,
            "success_count": 3,
            "usable_wiki_ready_count": 3,
            "quality_blocked_count": 0,
            "pending_review_count": 0,
            "gate_pass_rate": 1.0,
        },
    }
    selected = [{"id": f"p{i}"} for i in range(3)]
    downloads = [
        {"status": "downloaded", "filename": f"a{i}.pdf"}
        for i in range(3)
    ]

    verdict = _build_verdict(
        selected, downloads, verify_payload,
        manifest_total=3,
    )
    assert verdict["status"] == "basically_yes"
    assert "仅覆盖" not in verdict["answer"]


def test_us028_render_coverage_funnel() -> None:
    """Unit test: _render_coverage_funnel formats correctly for partial batch."""
    from scripts.download_and_verify_papers import _render_coverage_funnel

    funnel = _render_coverage_funnel({
        "manifest_total": 10,
        "selected_paper_count": 3,
        "downloaded_paper_count": 2,
        "verified_paper_count": 2,
    })
    assert "`10` (manifest)" in funnel
    assert "`3` (selected)" in funnel
    assert "`2` (downloaded)" in funnel
    assert "`2` (verified)" in funnel


def test_us028_render_coverage_funnel_full_batch() -> None:
    """Unit test: funnel shows equal numbers for a full batch."""
    from scripts.download_and_verify_papers import _render_coverage_funnel

    funnel = _render_coverage_funnel({
        "manifest_total": 10,
        "selected_paper_count": 10,
        "downloaded_paper_count": 10,
        "verified_paper_count": 10,
    })
    assert "`10` (manifest)" in funnel
    assert "`10` (verified)" in funnel


def test_us028_ten_paper_manifest_sample_coverage_section(tmp_path: Path) -> None:
    """AC2: markdown Sample Coverage section shows distinct counters for 10-paper manifest."""
    source_dir = tmp_path / "source-pdfs"
    source_dir.mkdir()
    pdfs = []
    for i in range(10):
        pdf = source_dir / f"paper_{i:02d}.pdf"
        pdf.write_bytes(_build_simple_pdf())
        pdfs.append(pdf)

    manifest_path = tmp_path / "papers.yaml"
    _make_manifest(manifest_path, pdfs)

    outdir = tmp_path / "verify-output"
    result = _run_download_and_verify(
        "--manifest", str(manifest_path),
        "--outdir", str(outdir),
        "--max-files", "3",
    )
    assert result.returncode == 0, result.stderr or result.stdout

    md_text = (outdir / "summary.md").read_text(encoding="utf-8")
    assert "## Sample Coverage" in md_text
    assert "Manifest total: **10**" in md_text
    assert "Selected for this run: **3**" in md_text
    assert "Downloaded successfully: **3**" in md_text
    assert "Verified: **3**" in md_text


def test_us028_classic_llm_10_manifest_loads() -> None:
    """AC1: configs/paper_sets/classic_llm_10.yaml can be loaded and parsed."""
    from scripts.download_and_verify_papers import _load_manifest

    manifest_path = REPO_ROOT / "configs" / "paper_sets" / "classic_llm_10.yaml"
    assert manifest_path.exists(), "classic_llm_10.yaml must exist"

    manifest = _load_manifest(manifest_path)
    assert manifest["name"] == "classic_llm_10"
    assert len(manifest["papers"]) == 10

    # Each paper must have required fields
    for i, paper in enumerate(manifest["papers"], start=1):
        assert "id" in paper, f"Paper #{i} missing id"
        assert "title" in paper, f"Paper #{i} missing title"
        assert "filename" in paper, f"Paper #{i} missing filename"
        assert "pdf_url" in paper, f"Paper #{i} missing pdf_url"
        assert paper["filename"].endswith(".pdf"), f"Paper #{i} filename must end with .pdf"


def test_us028_ten_paper_select_subset_coverage() -> None:
    """AC3: selecting a subset of a 10-paper manifest shows clear coverage gaps in JSON."""
    from scripts.download_and_verify_papers import _select_papers

    manifest = {
        "papers": [{"id": f"p{i}", "title": f"Paper {i}", "filename": f"{i}.pdf", "pdf_url": f"http://example.com/{i}.pdf"} for i in range(10)],
    }
    selected = _select_papers(manifest, max_files=3)
    assert len(selected) == 3
    assert len(manifest["papers"]) == 10  # original manifest unchanged
