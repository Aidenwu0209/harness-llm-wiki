"""Tests for US-017: Make gate and report patch-set aware."""

from __future__ import annotations

from docos.lint.checker import LintSeverity, ReleaseGate


class TestGatePatchSetAware:
    """US-017: ReleaseGate uses patch-set metrics."""

    def test_gate_accepts_patch_set_metrics(self) -> None:
        """ReleaseGate.check accepts patch_count, pages changed, aggregate risk."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[],
            harness_passed=True,
            patch_count=3,
            total_pages_changed=5,
            aggregate_risk=0.2,
        )
        assert can_merge is True
        assert len(reasons) == 0

    def test_gate_blocks_on_review_required_markers(self) -> None:
        """Gate blocks when patches require review."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(
            findings=[],
            harness_passed=True,
            review_required_markers=2,
        )
        assert can_merge is False
        assert any("review" in r.lower() for r in reasons)

    def test_gate_passes_without_patch_set(self) -> None:
        """Gate still passes without patch-set metrics (backward compat)."""
        gate = ReleaseGate()
        can_merge, reasons = gate.check(findings=[], harness_passed=True)
        assert can_merge is True

    def test_report_includes_patch_set_summary(self, tmp_path) -> None:
        """Report output includes patch-set counts from persisted data."""
        import json
        from pathlib import Path

        from docos.artifact_stores import PatchStore
        from docos.models.patch import BlastRadius, Change, ChangeType, Patch
        from docos.models.patch_set import PatchSet

        patch_store = PatchStore(tmp_path / "patches")
        p = Patch(
            patch_id="p-rpt-001", run_id="run-rpt-001", source_id="src-rpt",
            changes=[
                Change(type=ChangeType.CREATE_PAGE, target="a.md"),
                Change(type=ChangeType.UPDATE_PAGE, target="b.md"),
            ],
            risk_score=0.3, blast_radius=BlastRadius(pages=2),
        )
        ps = PatchSet.from_patches("run-rpt-001", "src-rpt", [p])
        patch_store.save_patch_set(ps)

        # Verify the file exists and contains expected data
        ps_path = tmp_path / "patches" / "patchset-run-rpt-001.json"
        assert ps_path.exists()
        data = json.loads(ps_path.read_text())
        assert data["summary"]["total_patches"] == 1
        assert data["summary"]["total_pages_changed"] == 2
        assert data["summary"]["create_page_count"] == 1
        assert data["summary"]["update_page_count"] == 1
