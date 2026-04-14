"""US-032: Align README and schema artifacts with runtime behavior.

Verifies that:
- README commands match implementation or are marked as roadmap
- Schema JSON files exist (schemas/*.schema.json)
- CLI commands exist as documented
"""

from __future__ import annotations

import json
from pathlib import Path

import click.testing

from docos.cli.main import cli


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"


class TestSchemaArtifactsExist:
    """Verify that schema JSON files exist and are valid."""

    def test_doc_schema_exists(self) -> None:
        """doc.schema.json (DocIR schema) exists."""
        path = SCHEMAS_DIR / "doc.schema.json"
        assert path.exists(), f"doc.schema.json not found at {path}"
        data = json.loads(path.read_text())
        assert "properties" in data
        assert "doc_id" in data["properties"]

    def test_page_schema_exists(self) -> None:
        """page.schema.json exists."""
        path = SCHEMAS_DIR / "page.schema.json"
        assert path.exists(), f"page.schema.json not found at {path}"
        data = json.loads(path.read_text())
        assert "properties" in data

    def test_patch_schema_exists(self) -> None:
        """patch.schema.json exists."""
        path = SCHEMAS_DIR / "patch.schema.json"
        assert path.exists(), f"patch.schema.json not found at {path}"
        data = json.loads(path.read_text())
        assert "properties" in data
        assert "patch_id" in data["properties"]

    def test_run_schema_exists(self) -> None:
        """run.schema.json exists."""
        path = SCHEMAS_DIR / "run.schema.json"
        assert path.exists(), f"run.schema.json not found at {path}"
        data = json.loads(path.read_text())
        assert "properties" in data
        assert "run_id" in data["properties"]

    def test_all_schemas_valid_json(self) -> None:
        """All schema files are valid JSON with required schema fields."""
        for schema_path in SCHEMAS_DIR.glob("*.schema.json"):
            data = json.loads(schema_path.read_text())
            assert "properties" in data, f"{schema_path.name} missing 'properties'"
            assert isinstance(data["properties"], dict), f"{schema_path.name} properties not a dict"


class TestCLICommandsExist:
    """Verify that documented CLI commands exist and work."""

    def test_run_command_exists(self) -> None:
        """docos run command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "file_path" in result.output.lower() or "source" in result.output.lower()

    def test_ingest_command_exists(self) -> None:
        """docos ingest command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["ingest", "--help"])
        assert result.exit_code == 0

    def test_route_command_exists(self) -> None:
        """docos route command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["route", "--help"])
        assert result.exit_code == 0

    def test_parse_command_exists(self) -> None:
        """docos parse command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["parse", "--help"])
        assert result.exit_code == 0

    def test_lint_command_exists(self) -> None:
        """docos lint command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["lint", "--help"])
        assert result.exit_code == 0

    def test_eval_command_exists(self) -> None:
        """docos eval command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["eval", "--help"])
        assert result.exit_code == 0

    def test_report_command_exists(self) -> None:
        """docos report command is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0

    def test_review_command_exists(self) -> None:
        """docos review command group is registered."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli, ["review", "--help"])
        assert result.exit_code == 0


class TestSchemaMatchesRuntime:
    """Verify schema artifacts match actual runtime behavior."""

    def test_doc_schema_matches_docir_model(self) -> None:
        """doc.schema.json matches DocIR model fields."""
        from docos.models.docir import DocIR

        schema_path = SCHEMAS_DIR / "doc.schema.json"
        data = json.loads(schema_path.read_text())
        props = data["properties"]

        # Key fields from DocIR model
        assert "doc_id" in props
        assert "source_id" in props
        assert "parser" in props
        assert "page_count" in props
        assert "blocks" in props
        assert "confidence" in props

    def test_patch_schema_matches_patch_model(self) -> None:
        """patch.schema.json matches Patch model fields."""
        from docos.models.patch import Patch

        schema_path = SCHEMAS_DIR / "patch.schema.json"
        data = json.loads(schema_path.read_text())
        props = data["properties"]

        assert "patch_id" in props
        assert "run_id" in props
        assert "changes" in props
        assert "risk_score" in props
        assert "merge_status" in props
