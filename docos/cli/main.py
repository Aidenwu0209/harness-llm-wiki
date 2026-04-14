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
    """Parse a source document."""
    from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    parser = StdlibPDFParser()
    file_path = Path(source.raw_storage_path or source.file_name)
    result = parser.parse(file_path)
    click.echo(json.dumps({
        "success": result.success,
        "parser": result.parser_name,
        "pages_parsed": result.pages_parsed,
        "blocks_extracted": result.blocks_extracted,
        "error": result.error,
    }, indent=2))


@cli.command()
@click.argument("source_id")
def normalize(source_id: str) -> None:
    """Normalize parsed output into canonical DocIR."""
    from docos.ir_store import IRStore
    from docos.pipeline.normalizer import PageLocalNormalizer
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    click.echo(json.dumps({"status": "normalized", "source_id": source_id}))


@cli.command()
@click.argument("source_id")
def extract(source_id: str) -> None:
    """Extract entities, claims, and relations."""
    from docos.ir_store import IRStore
    from docos.knowledge.extractor import KnowledgeExtractionPipeline
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    click.echo(json.dumps({"status": "extracted", "source_id": source_id}))


@cli.command("compile")
@click.argument("source_id")
def compile_cmd(source_id: str) -> None:
    """Compile wiki pages."""
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)
    source = registry.get(source_id)
    if source is None:
        click.echo(json.dumps({"error": f"Source not found: {source_id}"}))
        raise SystemExit(1)

    click.echo(json.dumps({"status": "compiled", "source_id": source_id}))


@cli.command()
@click.option("--run-id", default=None, help="Run ID to lint")
def lint(run_id: str | None) -> None:
    """Run lint checks on wiki state."""
    from docos.lint.checker import WikiLinter

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
    from docos.harness.runner import HarnessRunner
    from docos.run_store import RunStore

    base = Path(".")
    if run_id is None:
        click.echo(json.dumps({"error": "Please provide --run-id"}))
        raise SystemExit(1)

    run_store = RunStore(base)
    manifest = run_store.get(run_id)
    if manifest is None:
        click.echo(json.dumps({"error": f"Run not found: {run_id}"}))
        raise SystemExit(1)

    runner = HarnessRunner()
    report = runner.run(run_id=run_id, source_id=manifest.source_id)

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

    # Stages summary with error detail
    stages = [
        {"name": s.name, "status": s.status.value, "error": s.error_detail}
        for s in manifest.stages
    ]
    result["stages"] = stages

    # Failed stage highlighting
    failed = [s for s in manifest.stages if s.status.value == "failed"]
    if failed:
        result["failed_stage"] = failed[0].name
        result["error_detail"] = failed[0].error_detail

    # Route decision
    if manifest.route_artifact_path and Path(manifest.route_artifact_path).exists():
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())
        result["route"] = route_data
    else:
        result["route"] = "not-generated-yet"

    # Parser info (from route decision)
    if isinstance(result.get("route"), dict):
        route_info = result["route"]
        assert isinstance(route_info, dict)
        result["parser_chain"] = {
            "primary": route_info.get("primary_parser"),
            "fallbacks": route_info.get("fallback_parsers"),
        }

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

    # Lint findings
    if manifest.lint_artifact_path and Path(manifest.lint_artifact_path).exists():
        lint_data = json.loads(Path(manifest.lint_artifact_path).read_text())
        result["lint_findings"] = len(lint_data)
        result["lint_artifact"] = manifest.lint_artifact_path
    else:
        result["lint_findings"] = "not-generated-yet"

    # Harness report
    rs = ReportStore(base / "reports")
    harness_report = rs.get(run_id)
    result["harness_status"] = harness_report.release_decision if harness_report else "not-generated-yet"
    result["harness_passed"] = harness_report.overall_passed if harness_report else None

    # Gate decision — derived from lint + harness
    if manifest.report_artifact_path:
        result["gate_decision"] = "passed" if result.get("harness_passed") else "blocked"

    # Review status
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
