"""US-035: Documentation alignment test.

Verifies that README-documented CLI commands, page types, and parser names
match the actual implementation. Also checks that schema JSON artifacts exist
and are valid JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import click.testing
import pytest

from docos.cli.main import cli
from docos.models.page import PAGE_CONTENT_MAP, PageType
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"

# ---------------------------------------------------------------------------
# Documented CLI commands that MUST exist
# ---------------------------------------------------------------------------

# These are the commands documented in README.md "CLI 使用" section.
DOCUMENTED_CLI_COMMANDS = [
    "run",
    "ingest",
    "route",
    "parse",
    "normalize",
    "extract",
    "compile",
    "lint",
    "eval",
    "report",
]

DOCUMENTED_REVIEW_SUBCOMMANDS = [
    "list",
    "approve",
    "reject",
]

# ---------------------------------------------------------------------------
# Documented page types (README: "8 page types")
# ---------------------------------------------------------------------------

DOCUMENTED_PAGE_TYPES = {
    "source",
    "entity",
    "concept",
    "parser",
    "benchmark",
    "failure",
    "comparison",
    "decision",
}

# ---------------------------------------------------------------------------
# Documented parsers (README: stdlib_pdf + basic_text fallback)
# ---------------------------------------------------------------------------

DOCUMENTED_PARSERS = {
    "stdlib_pdf",
    "basic_text_fallback",
}

# ---------------------------------------------------------------------------
# Schema artifacts that MUST exist
# ---------------------------------------------------------------------------

REQUIRED_SCHEMA_FILES = [
    "run.schema.json",
    "page.schema.json",
    "patch.schema.json",
]


# ===========================================================================
# Tests
# ===========================================================================


class TestCLICommandsDocumented:
    """Verify that every CLI command documented in the README is registered."""

    @pytest.fixture()
    def cli_runner(self) -> click.testing.CliRunner:
        return click.testing.CliRunner()

    def test_help_lists_all_documented_commands(self, cli_runner: click.testing.CliRunner) -> None:
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0, result.output

        for cmd in DOCUMENTED_CLI_COMMANDS:
            assert cmd in result.output, (
                f"Documented CLI command '{cmd}' not found in CLI help output"
            )

    def test_review_help_lists_subcommands(self, cli_runner: click.testing.CliRunner) -> None:
        result = cli_runner.invoke(cli, ["review", "--help"])
        assert result.exit_code == 0, result.output

        for sub in DOCUMENTED_REVIEW_SUBCOMMANDS:
            assert sub in result.output, (
                f"Documented review subcommand '{sub}' not found in 'review --help' output"
            )


class TestPageTypesDocumented:
    """Verify that documented page types exist in the code."""

    def test_documented_page_types_match_code(self) -> None:
        code_types = {pt.value for pt in PageType}
        assert DOCUMENTED_PAGE_TYPES == code_types, (
            f"Documented page types mismatch: documented={DOCUMENTED_PAGE_TYPES}, "
            f"code={code_types}"
        )

    def test_page_content_map_covers_all_types(self) -> None:
        """Each PageType should have a corresponding content model."""
        for pt in PageType:
            assert pt in PAGE_CONTENT_MAP, f"PageType {pt.value} has no content model"


class TestParsersDocumented:
    """Verify that documented parsers are registered and match."""

    def test_stdlib_pdf_parser_name(self) -> None:
        parser = StdlibPDFParser()
        assert parser.name == "stdlib_pdf"

    def test_basic_text_fallback_parser_name(self) -> None:
        parser = BasicTextFallbackParser()
        assert parser.name == "basic_text_fallback"

    def test_exactly_two_documented_parsers(self) -> None:
        """The README documents exactly these two parsers."""
        names = {StdlibPDFParser().name, BasicTextFallbackParser().name}
        assert names == DOCUMENTED_PARSERS


class TestSchemaArtifacts:
    """Verify that schema JSON files exist and are valid."""

    @pytest.mark.parametrize("filename", REQUIRED_SCHEMA_FILES)
    def test_schema_file_exists(self, filename: str) -> None:
        path = SCHEMAS_DIR / filename
        assert path.exists(), f"Schema file {filename} does not exist at {path}"

    @pytest.mark.parametrize("filename", REQUIRED_SCHEMA_FILES)
    def test_schema_file_is_valid_json(self, filename: str) -> None:
        path = SCHEMAS_DIR / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{filename} is not a JSON object"
        # JSON Schema must have a $defs or properties or type key
        assert "$defs" in data or "properties" in data or "type" in data, (
            f"{filename} does not look like a JSON Schema"
        )
