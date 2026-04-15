"""Tests for US-016: Make HarnessRunner patch-set aware."""

from __future__ import annotations

from docos.harness.runner import HarnessRunner
from docos.models.patch import BlastRadius, Change, ChangeType, Patch


def _make_patch(patch_id: str, target: str = "page.md", risk: float = 0.2) -> Patch:
    return Patch(
        patch_id=patch_id, run_id="run-001", source_id="src-001",
        changes=[Change(type=ChangeType.CREATE_PAGE, target=target)],
        risk_score=risk, blast_radius=BlastRadius(pages=2, claims=1),
    )


class TestHarnessPatchSetAware:
    """US-016: HarnessRunner uses full patch set for scoring."""

    def test_accepts_patches_list(self) -> None:
        """HarnessRunner accepts a patches list."""
        runner = HarnessRunner()
        patches = [_make_patch("p-001"), _make_patch("p-002")]
        report = runner.run(run_id="r1", source_id="s1", patches=patches)
        assert report is not None

    def test_total_pages_changed_metric(self) -> None:
        """Metrics include total pages changed across all patches."""
        runner = HarnessRunner()
        patches = [
            _make_patch("p-001", target="page-a.md"),
            _make_patch("p-002", target="page-b.md"),
            _make_patch("p-003", target="page-a.md"),  # duplicate target
        ]
        report = runner.run(run_id="r1", source_id="s1", patches=patches)
        metrics = report.maintenance_quality.metrics
        assert metrics["total_pages_changed"] == 2  # unique targets
        assert metrics["total_patches"] == 3

    def test_aggregate_risk_from_full_set(self) -> None:
        """Aggregate risk reflects max risk across all patches."""
        runner = HarnessRunner()
        patches = [
            _make_patch("p-001", risk=0.1),
            _make_patch("p-002", risk=0.7),
            _make_patch("p-003", risk=0.3),
        ]
        report = runner.run(run_id="r1", source_id="s1", patches=patches)
        metrics = report.maintenance_quality.metrics
        assert metrics["aggregate_risk_score"] == 0.7

    def test_backward_compat_single_patch(self) -> None:
        """Single patch parameter still works."""
        runner = HarnessRunner()
        patch = _make_patch("p-001")
        report = runner.run(run_id="r1", source_id="s1", patch=patch)
        assert report is not None
        assert report.maintenance_quality.metrics.get("total_patches") == 1

    def test_empty_patches(self) -> None:
        """Empty patches list works without error."""
        runner = HarnessRunner()
        report = runner.run(run_id="r1", source_id="s1", patches=[])
        assert report is not None
