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

@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--origin", default="cli", help="Source origin")
@click.option("--tags", default="", help="Comma-separated tags")
def ingest(file_path: str, origin: str, tags: str) -> None:
    """Ingest a document into the system."""
    from docos.registry import SourceRegistry
    from docos.source_store import RawStorage

    base = Path(".")
    raw = RawStorage(base / "raw")
    registry = SourceRegistry(base / "registry", raw)

    source = registry.register(
        source_file=Path(file_path),
        origin=origin,
        tags=tags.split(",") if tags else [],
    )
    click.echo(json.dumps({"source_id": source.source_id, "status": source.status.value}, indent=2))


@cli.command()
@click.argument("source_id")
def route(source_id: str) -> None:
    """Route a source to the best parser."""
    import yaml  # type: ignore[import-untyped]
    from docos.models.config import AppConfig
    from docos.pipeline.router import DocumentSignals, ParserRouter

    config_path = Path("configs/router.yaml")
    with open(config_path) as f:
        config = AppConfig.model_validate(yaml.safe_load(f))

    router = ParserRouter(config)
    from docos.models.source import SourceRecord
    source = SourceRecord(source_id=source_id, source_hash="", file_name="", byte_size=0)
    signals = DocumentSignals(file_type="application/pdf")
    decision = router.route(source, signals)
    click.echo(json.dumps({
        "selected_route": decision.selected_route,
        "primary_parser": decision.primary_parser,
        "fallback_parsers": decision.fallback_parsers,
        "review_policy": decision.review_policy,
    }, indent=2))


@cli.command()
@click.argument("source_id")
def parse(source_id: str) -> None:
    """Parse a source document."""
    click.echo(f"Parse not yet connected for {source_id}")


@cli.command()
@click.argument("source_id")
def normalize(source_id: str) -> None:
    """Normalize parsed output into canonical DocIR."""
    click.echo(f"Normalize not yet connected for {source_id}")


@cli.command()
@click.argument("source_id")
def extract(source_id: str) -> None:
    """Extract entities, claims, and relations."""
    click.echo(f"Extract not yet connected for {source_id}")


@cli.command("compile")
@click.argument("source_id")
def compile_cmd(source_id: str) -> None:
    """Compile wiki pages."""
    click.echo(f"Compile not yet connected for {source_id}")


@cli.command()
def lint() -> None:
    """Run lint checks on wiki state."""
    click.echo("Lint checks: no wiki state found")


@cli.command("eval")
def eval_cmd() -> None:
    """Run harness evaluation."""
    click.echo("Harness evaluation: no runs to evaluate")


# ---------------------------------------------------------------------------
# Review commands
# ---------------------------------------------------------------------------

@cli.group()
def review() -> None:
    """Review queue management."""


@review.command("list")
def review_list() -> None:
    """List pending review items."""
    click.echo("No pending review items")


@review.command("approve")
@click.argument("review_id")
@click.option("--reviewer", default="cli_user", help="Reviewer name")
@click.option("--reason", default="", help="Approval reason")
def review_approve(review_id: str, reviewer: str, reason: str) -> None:
    """Approve a review item."""
    click.echo(f"Approved {review_id} by {reviewer}")


@review.command("reject")
@click.argument("review_id")
@click.option("--reviewer", default="cli_user", help="Reviewer name")
@click.option("--reason", default="", help="Rejection reason")
def review_reject(review_id: str, reviewer: str, reason: str) -> None:
    """Reject a review item."""
    click.echo(f"Rejected {review_id} by {reviewer}")


# ---------------------------------------------------------------------------
# Report commands
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("run_id")
def report(run_id: str) -> None:
    """Show ingest report for a run."""
    click.echo(f"No report found for run {run_id}")


if __name__ == "__main__":
    cli()
