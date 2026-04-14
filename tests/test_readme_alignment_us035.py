"""Tests for US-035: Align README and schema artifacts with implemented behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
SCHEMAS_DIR = REPO_ROOT / "schemas"


class TestReadmeAlignment:
    """Verify README matches current implementation."""

    def test_readme_exists(self) -> None:
        """README.md exists in the repo root."""
        assert README_PATH.exists(), "README.md not found"

    def test_readme_mentions_pipeline_stages(self) -> None:
        """README describes the pipeline stages."""
        content = README_PATH.read_text(encoding="utf-8")
        # Check key pipeline stages are mentioned
        expected_mentions = ["ingest", "route", "parse", "normalize", "extract", "compile", "patch", "lint", "harness", "gate"]
        for stage in expected_mentions:
            assert stage.lower() in content.lower(), f"README does not mention '{stage}'"

    def test_readme_mentions_page_types(self) -> None:
        """README mentions all page types."""
        content = README_PATH.read_text(encoding="utf-8")
        page_types = ["source", "entity", "concept", "parser", "benchmark", "failure", "comparison", "decision"]
        for pt in page_types:
            assert pt.lower() in content.lower(), f"README does not mention page type '{pt}'"

    def test_readme_mentions_parsers(self) -> None:
        """README mentions the available parsers."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "stdlib_pdf" in content or "stdlib" in content, "README should mention stdlib_pdf parser"

    def test_readme_cli_commands_exist(self) -> None:
        """CLI commands documented in README actually exist."""
        from click.testing import CliRunner
        from docos.cli.main import cli

        content = README_PATH.read_text(encoding="utf-8")

        # Extract CLI commands from README (look for 'docos <command>' patterns)
        cli_runner = CliRunner()
        help_result = cli_runner.invoke(cli, ["--help"])
        assert help_result.exit_code == 0

        # Verify each top-level command documented in README is registered
        documented_commands = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("docos ") and not line.startswith("docos --"):
                parts = line.split()
                if len(parts) >= 2:
                    cmd = parts[1]
                    # Skip flags and arguments
                    if not cmd.startswith("-") and not cmd.startswith("<"):
                        documented_commands.append(cmd)

        # Get registered commands
        registered = {cmd.name for cmd in cli.commands.values() if cmd.name}
        # Add subgroup commands
        for cmd_obj in cli.commands.values():
            if hasattr(cmd_obj, "commands"):
                for subcmd in cmd_obj.commands.values():
                    if subcmd.name:
                        registered.add(subcmd.name)

        for cmd in documented_commands:
            assert cmd in registered, (
                f"README documents 'docos {cmd}' but it's not a registered CLI command. "
                f"Registered: {sorted(registered)}"
            )

    def test_readme_mentions_docir(self) -> None:
        """README mentions DocIR (canonical document IR)."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "DocIR" in content, "README should mention DocIR"

    def test_readme_mentions_patch_flow(self) -> None:
        """README mentions the patch flow (lint → review → merge)."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "patch" in content.lower(), "README should mention patches"
        assert "lint" in content.lower(), "README should mention lint"

    def test_readme_mentions_evidence_anchors(self) -> None:
        """README mentions evidence anchors or evidence-backed claims."""
        content = README_PATH.read_text(encoding="utf-8")
        assert "evidence" in content.lower() or "anchor" in content.lower(), (
            "README should mention evidence anchors"
        )


class TestSchemaArtifacts:
    """Verify schema artifacts exist and match implementation."""

    def test_schemas_directory_exists(self) -> None:
        """schemas/ directory exists in the repo."""
        assert SCHEMAS_DIR.exists()
        assert SCHEMAS_DIR.is_dir()

    def test_run_schema_exists(self) -> None:
        """run.schema.json exists."""
        schema_path = SCHEMAS_DIR / "run.schema.json"
        assert schema_path.exists(), "run.schema.json not found"

    def test_page_schema_exists(self) -> None:
        """page.schema.json exists."""
        schema_path = SCHEMAS_DIR / "page.schema.json"
        assert schema_path.exists(), "page.schema.json not found"

    def test_patch_schema_exists(self) -> None:
        """patch.schema.json exists."""
        schema_path = SCHEMAS_DIR / "patch.schema.json"
        assert schema_path.exists(), "patch.schema.json not found"

    def test_schemas_are_valid_json(self) -> None:
        """All schema files are valid JSON."""
        for schema_path in SCHEMAS_DIR.glob("*.schema.json"):
            data = json.loads(schema_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict), f"{schema_path.name} is not a JSON object"
            # JSON Schema should have a properties field
            assert "properties" in data or "$defs" in data, (
                f"{schema_path.name} does not look like a valid JSON Schema"
            )

    def test_run_schema_matches_model(self) -> None:
        """run.schema.json matches the current RunManifest model."""
        from docos.models.run import RunManifest

        schema_path = SCHEMAS_DIR / "run.schema.json"
        if not schema_path.exists():
            pytest.skip("run.schema.json not found")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        model_schema = RunManifest.model_json_schema()

        # The schema should have the same title
        assert schema.get("title") == model_schema.get("title")

        # Key properties should be present
        props = schema.get("properties", {})
        assert "run_id" in props
        assert "source_id" in props
        assert "stages" in props

    def test_patch_schema_matches_model(self) -> None:
        """patch.schema.json matches the current Patch model."""
        from docos.models.patch import Patch

        schema_path = SCHEMAS_DIR / "patch.schema.json"
        if not schema_path.exists():
            pytest.skip("patch.schema.json not found")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        model_schema = Patch.model_json_schema()

        assert schema.get("title") == model_schema.get("title")

        props = schema.get("properties", {})
        assert "patch_id" in props
        assert "changes" in props

    def test_page_schema_matches_model(self) -> None:
        """page.schema.json matches the current Frontmatter model."""
        from docos.models.page import Frontmatter

        schema_path = SCHEMAS_DIR / "page.schema.json"
        if not schema_path.exists():
            pytest.skip("page.schema.json not found")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        model_schema = Frontmatter.model_json_schema()

        assert schema.get("title") == model_schema.get("title")

        props = schema.get("properties", {})
        assert "id" in props
        assert "type" in props
        assert "title" in props

    def test_generate_schemas_script_exists(self) -> None:
        """Schema generation script exists."""
        script = SCHEMAS_DIR / "generate_schemas.py"
        assert script.exists(), "generate_schemas.py not found in schemas/"
