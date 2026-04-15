"""Shared eval service — single entrypoint for pipeline and CLI.

Both the pipeline runner and ``docos eval --run-id`` call this service
so that harness output is consistent between unified runs and stage replay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docos.harness.runner import HarnessReport, HarnessRunner
from docos.models.knowledge import ClaimRecord, EntityRecord
from docos.models.patch import Patch


def run_eval_for_run(
    base_dir: Path,
    run_id: str,
) -> HarnessReport | None:
    """Run harness evaluation using persisted artifacts for a given run.

    Loads real DocIR, KnowledgeArtifact, PatchSet, and previous report.
    Returns HarnessReport or None if run not found.
    """
    from docos.artifact_stores import PatchStore, ReportStore
    from docos.ir_store import IRStore
    from docos.knowledge_store import KnowledgeStore
    from docos.run_store import RunStore

    run_store = RunStore(base_dir)
    manifest = run_store.get(run_id)
    if manifest is None:
        return None

    # Load DocIR
    ir_store = IRStore(base_dir / "ir")
    docir = ir_store.get(run_id)

    # Load knowledge
    ks = KnowledgeStore(base_dir / "knowledge")
    knowledge = ks.get(run_id)
    claims: list[ClaimRecord] = knowledge.claims if knowledge else []
    entities: list[EntityRecord] = knowledge.entities if knowledge else []

    # Load patches
    patch_store = PatchStore(base_dir / "patches")
    ps = patch_store.get_patch_set(run_id)
    patches: list[Patch] = ps.patches if ps else []

    # Load previous report for regression check
    rs = ReportStore(base_dir / "reports")
    previous_report = rs.get(run_id)

    runner = HarnessRunner()
    report = runner.run(
        run_id=run_id,
        source_id=manifest.source_id,
        docir=docir,
        claims=claims if claims else None,
        entities=entities if entities else None,
        patches=patches if patches else None,
        previous_report=previous_report,
    )

    return report
