"""Tests for artifact stores — PatchStore, ReportStore, WikiStore."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from docos.artifact_stores import (
    PatchStore,
    ReportStore,
    WikiPageState,
    WikiStore,
)
from docos.harness.runner import HarnessReport, HarnessSection
from docos.models.patch import BlastRadius, Change, ChangeType, MergeStatus, Patch
from docos.run_store import RunStore


def _make_patch(patch_id: str = "pat_001", run_id: str = "run_001") -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id=run_id,
        source_id="src_test",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="source/src_test.md"),
        ],
        blast_radius=BlastRadius(pages=1),
        risk_score=0.2,
    )


def _make_report(run_id: str = "run_001") -> HarnessReport:
    report = HarnessReport(run_id=run_id, source_id="src_test")
    report.parse_quality.passed = True
    report.knowledge_quality.passed = True
    report.maintenance_quality.passed = True
    report.compute_overall()
    return report


# ---------------------------------------------------------------------------
# PatchStore
# ---------------------------------------------------------------------------


class TestPatchStore:
    def test_save_and_retrieve(self, tmp_path: Path) -> None:
        store = PatchStore(tmp_path / "patches")
        patch = _make_patch()
        store.save(patch)

        loaded = store.get("pat_001")
        assert loaded is not None
        assert loaded.patch_id == "pat_001"
        assert loaded.run_id == "run_001"
        assert len(loaded.changes) == 1

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = PatchStore(tmp_path / "patches")
        assert store.get("pat_missing") is None

    def test_exists(self, tmp_path: Path) -> None:
        store = PatchStore(tmp_path / "patches")
        assert not store.exists("pat_check")
        store.save(_make_patch("pat_check"))
        assert store.exists("pat_check")

    def test_reload_after_new_process(self, tmp_path: Path) -> None:
        store1 = PatchStore(tmp_path / "patches")
        store1.save(_make_patch("pat_reload"))

        store2 = PatchStore(tmp_path / "patches")
        loaded = store2.get("pat_reload")
        assert loaded is not None
        assert loaded.patch_id == "pat_reload"

    def test_manifest_links_patch_artifact(self, tmp_path: Path) -> None:
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_test",
            source_hash="a" * 64,
            source_file_path="/tmp/test.pdf",
        )

        ps = PatchStore(tmp_path / "patches")
        patch = _make_patch(run_id=manifest.run_id)
        ps_path = ps.save(patch)

        manifest.patch_artifact_path = str(ps_path)
        run_store.update(manifest)

        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.patch_artifact_path is not None


# ---------------------------------------------------------------------------
# ReportStore
# ---------------------------------------------------------------------------


class TestReportStore:
    def test_save_and_retrieve(self, tmp_path: Path) -> None:
        store = ReportStore(tmp_path / "reports")
        report = _make_report()
        store.save(report)

        loaded = store.get("run_001")
        assert loaded is not None
        assert loaded.run_id == "run_001"
        assert loaded.source_id == "src_test"
        assert loaded.overall_passed is True
        assert loaded.release_decision == "auto_merge"

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = ReportStore(tmp_path / "reports")
        assert store.get("run_missing") is None

    def test_reload_after_new_process(self, tmp_path: Path) -> None:
        store1 = ReportStore(tmp_path / "reports")
        store1.save(_make_report("run_reload"))

        store2 = ReportStore(tmp_path / "reports")
        loaded = store2.get("run_reload")
        assert loaded is not None
        assert loaded.run_id == "run_reload"
        assert loaded.overall_passed is True

    def test_manifest_links_report_artifact(self, tmp_path: Path) -> None:
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_test",
            source_hash="b" * 64,
            source_file_path="/tmp/test.pdf",
        )

        rs = ReportStore(tmp_path / "reports")
        report = _make_report(manifest.run_id)
        rs_path = rs.save(report)

        manifest.report_artifact_path = str(rs_path)
        run_store.update(manifest)

        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.report_artifact_path is not None

    def test_report_with_failed_section(self, tmp_path: Path) -> None:
        store = ReportStore(tmp_path / "reports")
        report = HarnessReport(run_id="run_fail", source_id="src_x")
        report.parse_quality.passed = False
        report.parse_quality.notes.append("No DocIR provided")
        report.compute_overall()

        store.save(report)
        loaded = store.get("run_fail")
        assert loaded is not None
        assert loaded.overall_passed is False
        assert loaded.release_decision == "review_required"


# ---------------------------------------------------------------------------
# WikiStore
# ---------------------------------------------------------------------------


class TestWikiStore:
    def test_save_and_retrieve(self, tmp_path: Path) -> None:
        store = WikiStore(tmp_path / "wiki")
        state = WikiPageState(
            page_path="source/src_test.md",
            run_id="run_001",
            frontmatter={"title": "Test Source", "type": "source"},
            body="# Test Source\n\nContent here.",
        )
        store.save(state)

        loaded = store.get("source/src_test.md")
        assert loaded is not None
        assert loaded.page_path == "source/src_test.md"
        assert loaded.run_id == "run_001"
        assert loaded.frontmatter["title"] == "Test Source"
        assert "Content here" in loaded.body

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = WikiStore(tmp_path / "wiki")
        assert store.get("nonexistent.md") is None

    def test_reload_after_new_process(self, tmp_path: Path) -> None:
        store1 = WikiStore(tmp_path / "wiki")
        state = WikiPageState(
            page_path="entity/test.md",
            run_id="run_w",
            frontmatter={"title": "Wiki Reload Test"},
            body="body text",
        )
        store1.save(state)

        store2 = WikiStore(tmp_path / "wiki")
        loaded = store2.get("entity/test.md")
        assert loaded is not None
        assert loaded.run_id == "run_w"

    def test_manifest_links_wiki_state(self, tmp_path: Path) -> None:
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_test",
            source_hash="c" * 64,
            source_file_path="/tmp/test.pdf",
        )

        ws = WikiStore(tmp_path / "wiki")
        state = WikiPageState(
            page_path="source/src_test.md",
            run_id=manifest.run_id,
            frontmatter={},
            body="",
        )
        ws.save(state)

        manifest.wiki_state_path = str(tmp_path / "wiki")
        run_store.update(manifest)

        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.wiki_state_path is not None
