"""Tests for parser backend interface."""

import json
from pathlib import Path

import pytest

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.pipeline.parser import (
    DebugConfig,
    HealthStatus,
    ParserBackend,
    ParserCapability,
    ParserRegistry,
    ParseResult,
)


# ---------------------------------------------------------------------------
# Concrete test backend
# ---------------------------------------------------------------------------

class StubParser(ParserBackend):
    """Minimal parser backend for testing."""

    @property
    def name(self) -> str:
        return "stub_parser"

    @property
    def version(self) -> str:
        return "0.1.0"

    def capabilities(self) -> set[ParserCapability]:
        return {
            ParserCapability.TEXT_EXTRACTION,
            ParserCapability.LAYOUT_ANALYSIS,
            ParserCapability.TABLE_DETECTION,
        }

    def parse(self, file_path: Path) -> ParseResult:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            raw_output={"text": content, "pages": 1},
            pages_parsed=1,
            blocks_extracted=1,
        )

    def normalize(self, result: ParseResult) -> DocIR:
        text = result.raw_output.get("text", "")
        block = Block(
            block_id="b1",
            page_no=1,
            block_type=BlockType.PARAGRAPH,
            reading_order=0,
            bbox=(0, 0, 612, 792),
            text_plain=text[:200],
            source_parser=self.name,
            source_node_id="node_1",
        )
        page = Page(page_no=1, width=612, height=792, blocks=["b1"])
        return DocIR(
            doc_id="doc_stub",
            source_id="src_stub",
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            pages=[page],
            blocks=[block],
        )

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(healthy=True, parser_name=self.name, latency_ms=1.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParserBackend:
    def test_stub_parser_parse(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("Hello world")

        parser = StubParser()
        result = parser.parse(f)
        assert result.success is True
        assert result.parser_name == "stub_parser"
        assert result.pages_parsed == 1

    def test_stub_parser_normalize(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("Hello world")

        parser = StubParser()
        result = parser.parse(f)
        docir = parser.normalize(result)
        assert isinstance(docir, DocIR)
        assert len(docir.blocks) == 1
        assert docir.blocks[0].text_plain == "Hello world"

    def test_capabilities(self) -> None:
        parser = StubParser()
        caps = parser.capabilities()
        assert ParserCapability.TEXT_EXTRACTION in caps
        assert ParserCapability.OCR not in caps

    def test_healthcheck(self) -> None:
        parser = StubParser()
        status = parser.healthcheck()
        assert status.healthy is True
        assert status.parser_name == "stub_parser"

    def test_export_debug_assets(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("Hello world")

        parser = StubParser()
        result = parser.parse(f)

        config = DebugConfig(output_dir=tmp_path / "debug", save_raw_output=True)
        assets = parser.export_debug_assets(result, config)

        assert "raw_output" in assets
        raw_path = assets["raw_output"]
        assert raw_path.exists()
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        assert data["text"] == "Hello world"

    def test_export_debug_assets_disabled(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("Hello")

        parser = StubParser()
        result = parser.parse(f)

        config = DebugConfig(output_dir=tmp_path / "debug", save_raw_output=False)
        assets = parser.export_debug_assets(result, config)
        assert len(assets) == 0


class TestParserRegistry:
    def test_register_and_get(self) -> None:
        reg = ParserRegistry()
        parser = StubParser()
        reg.register(parser)

        assert reg.get("stub_parser") is parser
        assert reg.get("nonexistent") is None

    def test_list_parsers(self) -> None:
        reg = ParserRegistry()
        reg.register(StubParser())
        assert reg.list_parsers() == ["stub_parser"]

    def test_all_healthy(self) -> None:
        reg = ParserRegistry()
        reg.register(StubParser())
        health = reg.all_healthy()
        assert "stub_parser" in health
        assert health["stub_parser"].healthy is True


class TestAllCapabilities:
    def test_all_capability_values(self) -> None:
        for cap in ParserCapability:
            assert isinstance(cap.value, str)
