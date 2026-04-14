"""Tests for US-011: Persist patch and report artifacts.

Acceptance criteria:
- The compile or patch stage writes a patch artifact to disk when page output changes
- The report stage writes a persisted report artifact instead of only printing transient output
- The RunManifest links to both patch and report artifact paths when they exist
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.artifact_stores import PatchStore, ReportStore
from docos.harness.runner import HarnessReport, HarnessSection, HarnessRunner
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType
from docos.models.patch import Change, ChangeType, MergeStatus, Patch
from docos.run_store import RunStore


def _make_patch(run_id: str, source_id: str) -> Patch:
    """Create a sample patch for testing."""
    return Patch(
        patch_id=f"patch_{run_id}",
        run_id=run_id,
        source_id=source_id,
        changes=[
            Change(
                type=ChangeType.CREATE_PAGE,
                target="test/document.md",
                summary="Create new page for test document",
            ),
        ],
        merge_status=MergeStatus.PENDING,
    )


def _make_report(run_id: str, source_id: str) -> HarnessReport:
    """Create a sample harness report for testing."""
    report = HarnessReport(
        run_id=run_id,
        source_id=source_id,
    )
    report.parse_quality = HarnessSection(
        name="parse_quality",
        metrics={"pages_parsed": 1, "blocks_extracted": 5},
        passed=True,
    )
    report.knowledge_quality = HarnessSection(
        name="knowledge_quality",
        metrics={"entities_found": 3},
        passed=True,
    )
    report.maintenance_quality = HarnessSection(
        name="maintenance_quality",
        passed=True,
    )
    report.compute_overall()
    return report


# ---------------------------------------------------------------------------
# AC1: Patch artifact written to disk
# ---------------------------------------------------------------------------


class TestPatchArtifactPersisted:
    """The compile or patch stage writes a patch artifact to disk when page
    output changes."""

    def test_patch_saved_to_disk(self, tmp_path: Path) -> None:
        """A patch artifact is saved to disk via PatchStore."""
        store = PatchStore(tmp_path / "patches")
        patch = _make_patch("run_p1", "src_p1")
        patch.stage()

        path = store.save(patch)
        assert path.exists()

    def test_patch_content_is_valid_json(self, tmp_path: Path) -> None:
        """The saved patch is valid JSON with expected fields."""
        store = PatchStore(tmp_path / "patches")
        patch = _make_patch("run_p2", "src_p2")
        patch.stage()

        store.save(patch)

        loaded = store.get(patch.patch_id)
        assert loaded is not None
        assert loaded.patch_id == patch.patch_id
        assert loaded.run_id == patch.run_id
        assert loaded.changes[0].type == ChangeType.CREATE_PAGE
        assert len(loaded.changes) == 1

    def test_patch_can_be_reloaded(self, tmp_path: Path) -> None:
        """A new PatchStore instance can reload the patch."""
        store = PatchStore(tmp_path / "patches")
        patch = _make_patch("run_p3", "src_p3")
        patch.stage()

        store.save(patch)

        new_store = PatchStore(tmp_path / "patches")
        loaded = new_store.get(patch.patch_id)
        assert loaded is not None
        assert loaded.patch_id == patch.patch_id

    def test_multiple_patches_persisted(self, tmp_path: Path) -> None:
        """Multiple patches for different pages are persisted independently."""
        store = PatchStore(tmp_path / "patches")

        p1 = _make_patch("run_multi", "src_multi")
        p1.stage()
        store.save(p1)

        p2 = Patch(
            patch_id=f"patch_{p1.patch_id}_update",
            run_id="run_multi",
            source_id="src_multi",
            changes=[
                Change(
                    type=ChangeType.UPDATE_PAGE,
                    target="test/other.md",
                    summary="Update existing page content",
                ),
            ],
            merge_status=MergeStatus.PENDING,
        )
        p2.stage()
        store.save(p2)

        assert store.get(p1.patch_id) is not None
        assert store.get(p2.patch_id) is not None


# ---------------------------------------------------------------------------
# AC2: Report artifact written to disk
# ---------------------------------------------------------------------------


class TestReportArtifactPersisted:
    """The report stage writes a persisted report artifact instead of only
    printing transient output."""

    def test_report_saved_to_disk(self, tmp_path: Path) -> None:
        """A harness report is saved to disk via ReportStore."""
        store = ReportStore(tmp_path / "reports")
        report = _make_report("run_r1", "src_r1")

        path = store.save(report)
        assert path.exists()

    def test_report_content_reloaded(self, tmp_path: Path) -> None:
        """The saved report can be reloaded with correct data."""
        store = ReportStore(tmp_path / "reports")
        report = _make_report("run_r2", "src_r2")

        store.save(report)

        loaded = store.get("run_r2")
        assert loaded is not None
        assert loaded.run_id == "run_r2"
        assert loaded.source_id == "src_r2"
        assert loaded.overall_passed is True
        assert loaded.release_decision == "auto_merge"

    def test_report_survives_restart(self, tmp_path: Path) -> None:
        """A new ReportStore instance can reload the report."""
        store = ReportStore(tmp_path / "reports")
        report = _make_report("run_r3", "src_r3")
        store.save(report)

        new_store = ReportStore(tmp_path / "reports")
        loaded = new_store.get("run_r3")
        assert loaded is not None
        assert loaded.run_id == "run_r3"

    def test_report_sections_preserved(self, tmp_path: Path) -> None:
        """Report sections (parse_quality, knowledge_quality, maintenance_quality) survive round-trip."""
        store = ReportStore(tmp_path / "reports")
        report = _make_report("run_r4", "src_r4")
        store.save(report)

        loaded = store.get("run_r4")
        assert loaded is not None
        assert loaded.parse_quality.passed is True
        assert loaded.knowledge_quality.metrics["entities_found"] == 3


# ---------------------------------------------------------------------------
# AC3: RunManifest links to both patch and report artifact paths
# ---------------------------------------------------------------------------


class TestManifestLinksPatchAndReport:
    """The RunManifest links to both patch and report artifact paths when
    they exist."""

    def test_manifest_links_patch_path(self, tmp_path: Path) -> None:
        """RunManifest.patch_artifact_path points to saved patch."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_pr",
            source_hash="a" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        run_id = manifest.run_id
        patch = _make_patch(run_id, "src_pr")
        patch.stage()

        patch_store = PatchStore(tmp_path / "patches")
        patch_store.save(patch)

        manifest.patch_artifact_path = str(tmp_path / "patches" / f"{patch.patch_id}.json")
        run_store.update(manifest)

        loaded = run_store.get(run_id)
        assert loaded is not None
        assert loaded.patch_artifact_path is not None
        assert Path(loaded.patch_artifact_path).exists()

    def test_manifest_links_report_path(self, tmp_path: Path) -> None:
        """RunManifest.report_artifact_path points to saved report."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_pr",
            source_hash="b" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        run_id = manifest.run_id
        report = _make_report(run_id, "src_pr")

        report_store = ReportStore(tmp_path / "reports")
        report_store.save(report)

        manifest.report_artifact_path = str(tmp_path / "reports" / f"{run_id}.json")
        run_store.update(manifest)

        loaded = run_store.get(run_id)
        assert loaded is not None
        assert loaded.report_artifact_path is not None
        assert Path(loaded.report_artifact_path).exists()

    def test_manifest_links_both_paths(self, tmp_path: Path) -> None:
        """RunManifest links to both patch and report paths simultaneously."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_both",
            source_hash="c" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        run_id = manifest.run_id

        # Save patch
        patch = _make_patch(run_id, "src_both")
        patch.stage()
        patch_store = PatchStore(tmp_path / "patches")
        patch_store.save(patch)

        # Save report
        report = _make_report(run_id, "src_both")
        report_store = ReportStore(tmp_path / "reports")
        report_store.save(report)

        # Link both
        manifest.patch_artifact_path = str(tmp_path / "patches" / f"{patch.patch_id}.json")
        manifest.report_artifact_path = str(tmp_path / "reports" / f"{run_id}.json")
        run_store.update(manifest)

        # Reload and verify both links
        loaded = run_store.get(run_id)
        assert loaded is not None
        assert loaded.patch_artifact_path is not None
        assert loaded.report_artifact_path is not None
        assert Path(loaded.patch_artifact_path).exists()
        assert Path(loaded.report_artifact_path).exists()
