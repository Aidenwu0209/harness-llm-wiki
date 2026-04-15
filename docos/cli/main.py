"""CLI entry point for docos."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group()
def cli() -> None:
    """Document Parsing Knowledge OS CLI."""


# ---------------------------------------------------------------------------
# Ingest pipeline commands
# ---------------------------------------------------------------------------

@cli.command("run")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--origin", default="cli", help="Source origin")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--config", "config_path", default=None, help="Path to router.yaml config")
def run_pipeline(file_path: str, origin: str, tags: str, config_path: str | None) -> None:
    """Run the full pipeline on a document (ingest to report)."""
    from docos.pipeline.runner import PipelineRunner

    base = Path(".")
    cfg = Path(config_path) if config_path else None
    runner = PipelineRunner(base_dir=base, config_path=cfg)
    result = runner.run(
        file_path=Path(file_path),
        origin=origin,
        tags=tags.split(",") if tags else [],
    )

    output: dict[str, object] = {
        "run_id": result.run_id,
        "source_id": result.source_id,
        "status": result.status.value,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
    }

    if result.failed_stage:
        output["failed_stage"] = result.failed_stage
        output["error_detail"] = result.error_detail

    if result.route_decision:
        output["route"] = result.route_decision.selected_route
        output["parser"] = result.route_decision.primary_parser

    if result.docir:
        output["ir_pages"] = result.docir.page_count
        output["ir_blocks"] = len(result.docir.blocks)

    if result.entities:
        output["entities"] = len(result.entities)
    if result.claims:
        output["claims"] = len(result.claims)
    if result.patches:
        output["patches"] = len(result.patches)

    output["lint_findings"] = result.lint_findings_count
    output["harness_passed"] = result.harness_passed
    output["gate_passed"] = result.gate_passed

    if result.gate_reasons:
        output["gate_reasons"] = result.gate_reasons

    click.echo(json.dumps(output, indent=2, default=str))

    if result.status.value == "failed":
        raise SystemExit(1)


@cli.command("rerun")
@click.argument("source_id")
@click.option("--config", "config_path", default=None, help="Path to router.yaml config")
def rerun_pipeline(source_id: str, config_path: str | None) -> None:
    """Rerun the full pipeline for an existing source."""
    from docos.pipeline.runner import PipelineRunner
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    cfg = Path(config_path) if config_path else None

    # Look up existing source
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    # Use the stored raw file as input
    file_path = Path(source.raw_storage_path or source.file_name)
    if not file_path.exists():
        click.echo(json.dumps({"error": f"Source file not found: {file_path}"}))
        raise SystemExit(1)

    runner = PipelineRunner(base_dir=base, config_path=cfg)
    result = runner.run(
        file_path=file_path,
        origin="rerun",
        tags=[],
    )

    output: dict[str, object] = {
        "run_id": result.run_id,
        "source_id": result.source_id,
        "status": result.status.value,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
    }

    if result.failed_stage:
        output["failed_stage"] = result.failed_stage
        output["error_detail"] = result.error_detail

    click.echo(json.dumps(output, indent=2, default=str))

    if result.status.value == "failed":
        raise SystemExit(1)


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--origin", default="cli", help="Source origin")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--run", is_flag=True, default=False, help="Create a run manifest during ingest")
def ingest(file_path: str, origin: str, tags: str, run: bool) -> None:
    """Ingest a document into the system."""
    from docos.registry import SourceRegistry
    from docos.run_store import RunStore
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)

    source = registry.register(
        source_file=Path(file_path),
        origin=origin,
        tags=tags.split(",") if tags else [],
    )

    result: dict[str, object] = {
        "source_id": source.source_id,
        "status": source.status.value,
    }

    if run:
        run_store = RunStore(base)
        manifest = run_store.create(
            source_id=source.source_id,
            source_hash=source.source_hash,
            source_file_path=str(Path(file_path).resolve()),
        )
        result["run_id"] = manifest.run_id
        result["artifactRoot"] = manifest.artifact_root

    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.argument("source_id")
def route(source_id: str) -> None:
    """Route a source to the best parser."""
    import yaml  # type: ignore[import-untyped]
    from docos.models.config import AppConfig
    from docos.pipeline.router import ParserRouter
    from docos.pipeline.signal_extractor import SignalExtractor, signals_to_dict
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)

    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    config_path = Path("configs/router.yaml")
    with open(config_path) as f:
        config = AppConfig.model_validate(yaml.safe_load(f))

    # Extract signals from the real source file
    source_file_path = source.raw_storage_path or source.file_name
    extractor = SignalExtractor()
    signals = extractor.extract(Path(source_file_path))

    router = ParserRouter(config, log_dir=base / "route_logs")
    decision = router.route(source, signals)

    click.echo(json.dumps({
        "selected_route": decision.selected_route,
        "primary_parser": decision.primary_parser,
        "fallback_parsers": decision.fallback_parsers,
        "review_policy": decision.review_policy,
        "signals": signals_to_dict(signals),
    }, indent=2))


@cli.command()
@click.argument("source_id")
@click.option("--run-id", default=None, help="Run ID to use")
def parse(source_id: str, run_id: str | None) -> None:
    """Parse a source document using route + registry + orchestrator."""
    import yaml
    from docos.debug_store import DebugAssetStore
    from docos.models.config import AppConfig
    from docos.pipeline.orchestrator import PipelineOrchestrator
    from docos.pipeline.parser import ParserRegistry
    from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
    from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
    from docos.pipeline.router import DocumentSignals, ParserRouter
    from docos.pipeline.signal_extractor import SignalExtractor
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    # Load config and route
    config_path = Path("configs/router.yaml")
    with open(config_path) as f:
        config = AppConfig.model_validate(yaml.safe_load(f))

    source_file_path = source.raw_storage_path or source.file_name
    extractor = SignalExtractor()
    signals = extractor.extract(Path(source_file_path))

    router = ParserRouter(config, log_dir=base / "route_logs")
    decision = router.route(source, signals)

    # Build parser registry and execute via orchestrator
    parser_registry = ParserRegistry()
    parser_registry.register(StdlibPDFParser())
    parser_registry.register(BasicTextFallbackParser())

    debug_store = DebugAssetStore(base / "debug")
    effective_run_id = run_id or "cli_standalone"
    orchestrator = PipelineOrchestrator(
        parser_registry=parser_registry,
        debug_dir=base / "debug",
        debug_store=debug_store,
    )
    file_path = Path(source_file_path)
    result = orchestrator.execute(
        run_id=effective_run_id,
        source_id=source_id,
        file_path=file_path,
        route_decision=decision,
    )

    click.echo(json.dumps({
        "success": result.success,
        "route": decision.selected_route,
        "parser": result.final_parser,
        "primary_succeeded": result.primary_succeeded,
        "fallback_used": result.fallback_used,
        "fallback_parser": result.fallback_parser,
        "pages_parsed": result.docir.page_count if result.docir else 0,
        "blocks_extracted": len(result.docir.blocks) if result.docir else 0,
        "error": result.failure_reason,
    }, indent=2))


@cli.command()
@click.argument("source_id")
@click.option("--run-id", default=None, help="Run ID to use for artifact lookup")
def normalize(source_id: str, run_id: str | None) -> None:
    """Normalize parsed output into canonical DocIR."""
    from docos.ir_store import IRStore
    from docos.pipeline.normalizer import GlobalRepair, RepairLog
    from docos.run_store import RunStore

    base = Path(".")
    ir_store = IRStore(base / "ir")

    # Resolve run_id
    if run_id is None:
        # Find latest run for this source
        run_store = RunStore(base)
        run_id = run_store.find_latest_run(source_id)
        if run_id is None:
            click.echo(json.dumps({"error": f"No run found for source: {source_id}"}))
            raise SystemExit(1)

    docir = ir_store.get(run_id)
    if docir is None:
        click.echo(json.dumps({"error": f"No parse artifact found for run: {run_id}"}))
        raise SystemExit(1)

    repair_log = RepairLog(source_id=source_id, run_id=run_id)
    repaired = GlobalRepair().repair(docir, repair_log)
    ir_store.save(repaired, run_id)

    click.echo(json.dumps({"status": "normalized", "source_id": source_id, "run_id": run_id}))


@cli.command()
@click.argument("source_id")
@click.option("--run-id", default=None, help="Run ID to use for artifact lookup")
def extract(source_id: str, run_id: str | None) -> None:
    """Extract entities, claims, and relations from stored DocIR."""
    from docos.ir_store import IRStore
    from docos.knowledge.extractor import KnowledgeExtractionPipeline
    from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
    from docos.run_store import RunStore

    base = Path(".")

    # Resolve run_id
    if run_id is None:
        run_store = RunStore(base)
        run_id = run_store.find_latest_run(source_id)
        if run_id is None:
            click.echo(json.dumps({"error": f"No run found for source: {source_id}"}))
            raise SystemExit(1)

    ir_store = IRStore(base / "ir")
    docir = ir_store.get(run_id)
    if docir is None:
        click.echo(json.dumps({"error": f"No parse artifact found for run: {run_id}"}))
        raise SystemExit(1)

    pipeline = KnowledgeExtractionPipeline()
    entities, claims, relations = pipeline.extract(docir)

    # Persist knowledge artifacts
    ks = KnowledgeStore(base / "knowledge")
    artifact = KnowledgeArtifact(
        run_id=run_id,
        source_id=source_id,
        entities=entities,
        claims=claims,
        relations=relations,
    )
    ks.save(artifact)

    click.echo(json.dumps({
        "status": "extracted",
        "source_id": source_id,
        "run_id": run_id,
        "entities": len(entities),
        "claims": len(claims),
        "relations": len(relations),
    }))


@cli.command("compile")
@click.argument("source_id")
@click.option("--run-id", default=None, help="Run ID to use for artifact lookup")
def compile_cmd(source_id: str, run_id: str | None) -> None:
    """Compile wiki pages from stored DocIR and knowledge artifacts."""
    from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
    from docos.ir_store import IRStore
    from docos.knowledge_store import KnowledgeStore
    from docos.models.patch_set import PatchSet
    from docos.run_store import RunStore
    from docos.wiki.compiler import CompiledPage, WikiCompiler

    base = Path(".")

    # Resolve run_id
    if run_id is None:
        run_store = RunStore(base)
        run_id = run_store.find_latest_run(source_id)
        if run_id is None:
            click.echo(json.dumps({"error": f"No run found for source: {source_id}"}))
            raise SystemExit(1)

    # Load DocIR
    ir_store = IRStore(base / "ir")
    docir = ir_store.get(run_id)
    if docir is None:
        click.echo(json.dumps({"error": f"No parse artifact found for run: {run_id}"}))
        raise SystemExit(1)

    # Load knowledge
    ks = KnowledgeStore(base / "knowledge")
    knowledge = ks.get(run_id)
    entities = knowledge.entities if knowledge else []
    claims = knowledge.claims if knowledge else []

    # Compile pages
    compiler = WikiCompiler(base / "wiki")
    wiki_store = WikiStore(base / "wiki_state")
    patch_store = PatchStore(base / "patches")
    patches = []
    page_types: list[str] = []

    from docos.source_store import RawStorage
    from docos.registry import SourceRegistry

    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)

    if source is not None:
        # Source page
        fm, body, page_path = compiler.compile_source_page(source, docir, entities, claims)
        compiled = CompiledPage(frontmatter=fm, body=body, page_path=page_path, run_id=run_id)
        patch = compiled.compute_patch(run_id=run_id, source_id=source_id)
        if patch is not None:
            patches.append(patch)
        page_types.append("source")
        wiki_store.save(WikiPageState(
            page_path=str(page_path), run_id=run_id,
            frontmatter=fm.model_dump(), body=body,
        ))

    # Entity pages
    for entity in entities:
        efm, ebody, epath = compiler.compile_entity_page(entity, claims)
        ecompiled = CompiledPage(frontmatter=efm, body=ebody, page_path=epath, run_id=run_id)
        epatch = ecompiled.compute_patch(run_id=run_id, source_id=source_id)
        if epatch is not None:
            patches.append(epatch)
        page_types.append("entity")
        wiki_store.save(WikiPageState(
            page_path=str(epath), run_id=run_id,
            frontmatter=efm.model_dump(), body=ebody,
        ))

    # Concept pages
    concept_names: set[str] = set()
    for entity in entities:
        if entity.entity_type.value in ("concept", "topic", "theme"):
            concept_names.add(entity.canonical_name)
    for concept_name in concept_names:
        related_entities = [e for e in entities if e.canonical_name == concept_name]
        related_claims = [c for c in claims if concept_name in c.statement]
        cfm, cbody, cpath = compiler.compile_concept_page(
            concept_name=concept_name,
            source_ids=[source_id],
            related_claims=related_claims,
            related_entities=related_entities,
        )
        ccompiled = CompiledPage(frontmatter=cfm, body=cbody, page_path=cpath, run_id=run_id)
        cpatch = ccompiled.compute_patch(run_id=run_id, source_id=source_id)
        if cpatch is not None:
            patches.append(cpatch)
        page_types.append("concept")
        wiki_store.save(WikiPageState(
            page_path=str(cpath), run_id=run_id,
            frontmatter=cfm.model_dump(), body=cbody,
        ))

    # Save patch set
    ps = PatchSet.from_patches(run_id, source_id, patches)
    for p in patches:
        patch_store.save(p)
    patch_store.save_patch_set(ps)

    click.echo(json.dumps({
        "status": "compiled",
        "source_id": source_id,
        "run_id": run_id,
        "page_count": len(page_types),
        "page_types": page_types,
        "patch_count": len(patches),
    }))


@cli.command()
@click.option("--run-id", default=None, help="Run ID to lint")
def lint(run_id: str | None) -> None:
    """Run lint checks on wiki state."""
    from docos.lint.checker import WikiLinter

    base = Path(".")

    if run_id:
        from docos.lint.service import run_lint_for_run

        findings = run_lint_for_run(base, run_id)
    else:
        linter = WikiLinter()
        findings = linter.lint(pages=[], claims=[], entities=[])

    if findings:
        for f in findings:
            click.echo(f"[{f.severity.value}] {f.code}: {f.message}")
    else:
        click.echo(json.dumps({"status": "passed", "findings": 0}))


@cli.command("eval")
@click.option("--run-id", default=None, help="Run ID to evaluate")
def eval_cmd(run_id: str | None) -> None:
    """Run harness evaluation."""
    from docos.artifact_stores import ReportStore
    from docos.harness.service import run_eval_for_run

    base = Path(".")
    if run_id is None:
        click.echo(json.dumps({"error": "Please provide --run-id"}))
        raise SystemExit(1)

    report = run_eval_for_run(base, run_id)
    if report is None:
        click.echo(json.dumps({"error": f"Run not found: {run_id}"}))
        raise SystemExit(1)

    rs = ReportStore(base / "reports")
    rs.save(report)

    click.echo(json.dumps({
        "overall_passed": report.overall_passed,
        "release_decision": report.release_decision,
    }, indent=2))


# ---------------------------------------------------------------------------
# Review commands
# ---------------------------------------------------------------------------

@cli.group()
def review() -> None:
    """Review queue management."""


@review.command("list")
def review_list() -> None:
    """List pending review items."""
    from docos.review.queue import ReviewQueue

    base = Path(".")
    queue = ReviewQueue(base / "review")
    pending = queue.list_pending()
    if not pending:
        click.echo(json.dumps({"pending": []}))
    else:
        items = [{"review_id": r.review_id, "type": r.item_type.value, "reason": r.reason} for r in pending]
        click.echo(json.dumps({"pending": items}, indent=2))


@review.command("approve")
@click.argument("review_id")
@click.option("--reviewer", default="cli_user", help="Reviewer name")
@click.option("--reason", default="", help="Approval reason")
def review_approve(review_id: str, reviewer: str, reason: str) -> None:
    """Approve a review item."""
    from docos.review.queue import ReviewQueue

    base = Path(".")
    queue = ReviewQueue(base / "review")
    item = queue.resolve(review_id, action="approve", reviewer=reviewer, reason=reason)
    if item is None:
        click.echo(json.dumps({"error": f"Review item not found: {review_id}"}))
        raise SystemExit(1)
    click.echo(json.dumps({"review_id": review_id, "status": "approved", "reviewer": reviewer}))


@review.command("reject")
@click.argument("review_id")
@click.option("--reviewer", default="cli_user", help="Reviewer name")
@click.option("--reason", default="", help="Rejection reason")
def review_reject(review_id: str, reviewer: str, reason: str) -> None:
    """Reject a review item."""
    from docos.review.queue import ReviewQueue

    base = Path(".")
    queue = ReviewQueue(base / "review")
    item = queue.resolve(review_id, action="reject", reviewer=reviewer, reason=reason)
    if item is None:
        click.echo(json.dumps({"error": f"Review item not found: {review_id}"}))
        raise SystemExit(1)
    click.echo(json.dumps({"review_id": review_id, "status": "rejected", "reviewer": reviewer}))


# ---------------------------------------------------------------------------
# Report commands
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("run_id")
def report(run_id: str) -> None:
    """Show run report from persisted artifacts."""
    from docos.artifact_stores import PatchStore, ReportStore, WikiStore
    from docos.ir_store import IRStore
    from docos.knowledge_store import KnowledgeStore
    from docos.run_store import RunStore

    base = Path(".")
    run_store = RunStore(base)

    manifest = run_store.get(run_id)
    if manifest is None:
        click.echo(json.dumps({"error": f"Run not found: {run_id}"}))
        raise SystemExit(1)

    # Core run info
    result: dict[str, object] = {
        "run_id": run_id,
        "source_id": manifest.source_id,
        "status": manifest.status.value,
        "source_file_path": manifest.source_file_path,
        "started_at": manifest.started_at.isoformat() if manifest.started_at else None,
        "finished_at": manifest.finished_at.isoformat() if manifest.finished_at else None,
    }

    # Stages summary with duration, warnings, and error detail
    stages = [
        {
            "name": s.name,
            "status": s.status.value,
            "error": s.error_detail,
            "duration_seconds": s.duration_seconds,
            "warnings": s.warnings,
        }
        for s in manifest.stages
    ]
    result["stages"] = stages

    # Failed stage highlighting
    failed = [s for s in manifest.stages if s.status.value == "failed"]
    if failed:
        result["failed_stage"] = failed[0].name
        result["error_detail"] = failed[0].error_detail

    # Route decision — load persisted artifact for full route data
    route_data: dict[str, object] | None = None
    if manifest.route_artifact_path and Path(manifest.route_artifact_path).exists():
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())

    if route_data is not None:
        result["route"] = route_data
    else:
        result["route"] = "not-generated-yet"

    # Selected route — from manifest observability field or artifact
    if manifest.selected_route:
        result["selected_route"] = manifest.selected_route
    elif route_data is not None:
        result["selected_route"] = route_data.get("selected_route", "not-generated-yet")

    # Parser chain — keep dict format for backward compat, add list from manifest
    if isinstance(route_data, dict):
        result["parser_chain"] = {
            "primary": route_data.get("primary_parser"),
            "fallbacks": route_data.get("fallback_parsers"),
        }
    else:
        result["parser_chain"] = {}

    # Also store the ordered parser list from manifest (US-034)
    if manifest.parser_chain:
        result["parser_chain_list"] = manifest.parser_chain
        # Backfill parser_chain dict if empty
        if not result["parser_chain"] and manifest.parser_chain:
            result["parser_chain"] = {
                "primary": manifest.parser_chain[0] if manifest.parser_chain else None,
                "fallbacks": manifest.parser_chain[1:] if len(manifest.parser_chain) > 1 else [],
            }

    # Fallback used flag (US-034)
    result["fallback_used"] = manifest.fallback_used

    # IR artifact
    ir_store = IRStore(base / "ir")
    ir = ir_store.get(run_id)
    result["ir_artifact"] = str(manifest.ir_artifact_path) if manifest.ir_artifact_path else "not-generated-yet"
    result["ir_pages"] = ir.page_count if ir else None
    result["ir_blocks"] = len(ir.blocks) if ir else None

    # Knowledge artifact
    ks = KnowledgeStore(base / "knowledge")
    knowledge = ks.get(run_id)
    result["knowledge_artifact"] = str(manifest.knowledge_artifact_path) if manifest.knowledge_artifact_path else "not-generated-yet"
    if knowledge:
        result["entity_count"] = len(knowledge.entities)
        result["claim_count"] = len(knowledge.claims)
        result["relation_count"] = len(knowledge.relations)

    # Patch artifact
    result["patch_artifact"] = str(manifest.patch_artifact_path) if manifest.patch_artifact_path else "not-generated-yet"

    # Patch-set summary (US-017)
    patch_dir = base / "patches"
    patchset_path = patch_dir / f"patchset-{run_id}.json"
    if patchset_path.exists():
        ps_data = json.loads(patchset_path.read_text())
        summary = ps_data.get("summary", {})
        result["patch_set"] = {
            "total_patches": summary.get("total_patches", 0),
            "total_pages_changed": summary.get("total_pages_changed", 0),
            "create_page_count": summary.get("create_page_count", 0),
            "update_page_count": summary.get("update_page_count", 0),
            "delete_page_count": summary.get("delete_page_count", 0),
            "max_risk_score": summary.get("max_risk_score", 0.0),
        }

    # Compile summary (US-012)
    if manifest.compiled_page_count > 0:
        result["compile_summary"] = {
            "page_count": manifest.compiled_page_count,
            "page_types": manifest.compiled_page_types,
            "patch_count": manifest.compiled_patch_count,
            "created_count": manifest.compiled_created_count,
            "updated_count": manifest.compiled_updated_count,
            "deleted_count": manifest.compiled_deleted_count,
        }

    # Lint findings — prefer manifest summary, always include artifact path
    if manifest.lint_artifact_path and Path(manifest.lint_artifact_path).exists():
        lint_data = json.loads(Path(manifest.lint_artifact_path).read_text())
        result["lint_findings"] = len(lint_data)
        result["lint_artifact"] = manifest.lint_artifact_path
    elif manifest.lint_summary:
        result["lint_findings"] = sum(manifest.lint_summary.values())
    else:
        result["lint_findings"] = "not-generated-yet"

    if manifest.lint_summary:
        result["lint_summary"] = manifest.lint_summary

    if manifest.lint_artifact_path:
        result["lint_artifact"] = manifest.lint_artifact_path

    # Harness report — load from store for full data, use manifest summary for US-034
    rs = ReportStore(base / "reports")
    harness_report = rs.get(run_id)

    # Backward compat: harness_status and harness_passed
    result["harness_status"] = harness_report.release_decision if harness_report else "not-generated-yet"
    result["harness_passed"] = harness_report.overall_passed if harness_report else None

    # US-034: harness_summary from manifest (may not be populated for old runs)
    if manifest.harness_summary:
        result["harness_summary"] = manifest.harness_summary

    # Gate decision — prefer manifest field
    if manifest.gate_decision:
        result["gate_decision"] = manifest.gate_decision
    elif manifest.report_artifact_path:
        result["gate_decision"] = "passed" if result.get("harness_passed") else "blocked"

    # Review status — prefer manifest field, fall back to query
    if manifest.review_status:
        result["review_status"] = manifest.review_status
    else:
        from docos.review.queue import ReviewQueue
        rq = ReviewQueue(base / "review")
        pending = rq.list_pending()
        run_reviews = [r for r in pending if run_id in r.target_object_id or run_id in r.source_id]
        result["review_status"] = "pending" if run_reviews else "none"

    # Debug assets
    if manifest.debug_artifact_path:
        result["debug_assets"] = "available"
    else:
        debug_base = base / "debug" / manifest.source_id / run_id
        result["debug_assets"] = "available" if debug_base.exists() else "none"

    click.echo(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    cli()
