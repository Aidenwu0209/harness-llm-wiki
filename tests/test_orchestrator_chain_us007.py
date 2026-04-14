"""Tests for US-007: Run parser chains through the orchestrator.

Acceptance criteria:
- The orchestrator executes the primary parser first and returns immediately on success
- If the primary parser fails, the orchestrator invokes the configured fallback parser sequence
- The final parse result records whether a fallback parser was used
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserBackend, ParserRegistry, ParseResult
from docos.pipeline.router import RouteDecision


# ---------------------------------------------------------------------------
# Test backends
# ---------------------------------------------------------------------------


class AlwaysSucceedParser(ParserBackend):
    """Parser that always succeeds."""

    @property
    def name(self) -> str:
        return "always_succeed"

    @property
    def version(self) -> str:
        return "1.0.0"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            pages_parsed=1,
            blocks_extracted=1,
            raw_output={"text": "primary output"},
        )

    def normalize(self, result: ParseResult) -> DocIR:
        block = Block(
            block_id="b1",
            page_no=1,
            block_type=BlockType.PARAGRAPH,
            reading_order=0,
            bbox=(0, 0, 100, 50),
            text_plain="primary output",
            source_parser=self.name,
            source_node_id="n1",
        )
        page = Page(page_no=1, width=612, height=792, blocks=["b1"])
        return DocIR(
            doc_id="doc_primary",
            source_id="src_primary",
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            pages=[page],
            blocks=[block],
        )

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus

        return HealthStatus(healthy=True, parser_name=self.name)


class AlwaysFailParser(ParserBackend):
    """Parser that always fails."""

    @property
    def name(self) -> str:
        return "always_fail"

    @property
    def version(self) -> str:
        return "1.0.0"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=False,
            error="Intentional failure for testing",
        )

    def normalize(self, result: ParseResult) -> DocIR:
        raise RuntimeError("Should not be called on failure")

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus

        return HealthStatus(healthy=True, parser_name=self.name)


class FallbackSucceedParser(ParserBackend):
    """Second parser that succeeds — used as fallback."""

    @property
    def name(self) -> str:
        return "fallback_succeed"

    @property
    def version(self) -> str:
        return "2.0.0"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            pages_parsed=1,
            blocks_extracted=1,
            raw_output={"text": "fallback output"},
        )

    def normalize(self, result: ParseResult) -> DocIR:
        block = Block(
            block_id="b2",
            page_no=1,
            block_type=BlockType.PARAGRAPH,
            reading_order=0,
            bbox=(0, 0, 100, 50),
            text_plain="fallback output",
            source_parser=self.name,
            source_node_id="n2",
        )
        page = Page(page_no=1, width=612, height=792, blocks=["b2"])
        return DocIR(
            doc_id="doc_fallback",
            source_id="src_fallback",
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            pages=[page],
            blocks=[block],
        )

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus

        return HealthStatus(healthy=True, parser_name=self.name)


class SecondFallbackParser(ParserBackend):
    """Third parser in the fallback chain."""

    @property
    def name(self) -> str:
        return "second_fallback"

    @property
    def version(self) -> str:
        return "3.0.0"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            pages_parsed=2,
            blocks_extracted=3,
            raw_output={"text": "second fallback output"},
        )

    def normalize(self, result: ParseResult) -> DocIR:
        block = Block(
            block_id="b3",
            page_no=1,
            block_type=BlockType.PARAGRAPH,
            reading_order=0,
            bbox=(0, 0, 100, 50),
            text_plain="second fallback output",
            source_parser=self.name,
            source_node_id="n3",
        )
        page = Page(page_no=1, width=612, height=792, blocks=["b3"])
        return DocIR(
            doc_id="doc_second_fallback",
            source_id="src_second_fallback",
            parser=self.name,
            parser_version=self.version,
            page_count=1,
            pages=[page],
            blocks=[block],
        )

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus

        return HealthStatus(healthy=True, parser_name=self.name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_registry() -> ParserRegistry:
    reg = ParserRegistry()
    reg.register(AlwaysSucceedParser())
    reg.register(AlwaysFailParser())
    reg.register(FallbackSucceedParser())
    reg.register(SecondFallbackParser())
    return reg


@pytest.fixture
def orchestrator(full_registry: ParserRegistry, tmp_path: Path) -> PipelineOrchestrator:
    return PipelineOrchestrator(full_registry, debug_dir=tmp_path / "debug")


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.pdf"
    f.write_bytes(b"Test content")
    return f


def _decision(primary: str, fallbacks: list[str] | None = None) -> RouteDecision:
    return RouteDecision(
        selected_route="test_route",
        primary_parser=primary,
        fallback_parsers=fallbacks or [],
        expected_risks=[],
        post_parse_repairs=[],
        review_policy="default",
    )


# ---------------------------------------------------------------------------
# AC1: Primary success returns immediately
# ---------------------------------------------------------------------------


class TestPrimarySuccessReturnsImmediately:
    """AC1: The orchestrator executes the primary parser first and returns
    immediately on success."""

    def test_primary_succeeds_no_fallback_tried(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """When primary succeeds, only one attempt is recorded."""
        decision = _decision("always_succeed", ["fallback_succeed"])
        result = orchestrator.execute("run_ac1", "src_ac1", sample_file, decision)

        assert result.success is True
        assert result.primary_succeeded is True
        assert result.fallback_used is False
        assert result.fallback_parser is None
        assert result.final_parser == "always_succeed"
        # Only primary was tried — no fallback attempts
        assert len(result.attempts) == 1
        assert result.attempts[0].parser_name == "always_succeed"

    def test_primary_succeeds_fallback_not_in_attempts(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """Fallback parser never runs when primary succeeds."""
        decision = _decision("always_succeed", ["always_fail", "fallback_succeed"])
        result = orchestrator.execute("run_ac1b", "src_ac1b", sample_file, decision)

        assert result.success is True
        # Only one attempt — the fallbacks were never invoked
        assert len(result.attempts) == 1
        assert result.attempts[0].success is True

    def test_primary_docir_returned_directly(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """The DocIR returned is from the primary parser, not a fallback."""
        decision = _decision("always_succeed")
        result = orchestrator.execute("run_ac1c", "src_ac1c", sample_file, decision)

        assert result.docir is not None
        assert result.docir.parser == "always_succeed"
        assert result.docir.blocks[0].text_plain == "primary output"


# ---------------------------------------------------------------------------
# AC2: Primary failure triggers fallback chain
# ---------------------------------------------------------------------------


class TestFallbackChainExecution:
    """AC2: If the primary parser fails, the orchestrator invokes the
    configured fallback parser sequence."""

    def test_single_fallback_used_on_primary_failure(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """Primary fails → first fallback succeeds."""
        decision = _decision("always_fail", ["fallback_succeed"])
        result = orchestrator.execute("run_ac2", "src_ac2", sample_file, decision)

        assert result.success is True
        assert result.primary_succeeded is False
        assert result.fallback_used is True
        assert result.fallback_parser == "fallback_succeed"
        assert result.final_parser == "fallback_succeed"
        assert len(result.attempts) == 2

    def test_multi_fallback_chain(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """Primary fails → first fallback fails → second fallback succeeds."""
        decision = _decision("always_fail", ["always_fail", "second_fallback"])
        result = orchestrator.execute("run_ac2b", "src_ac2b", sample_file, decision)

        assert result.success is True
        assert result.fallback_used is True
        assert result.fallback_parser == "second_fallback"
        assert result.final_parser == "second_fallback"
        # 3 attempts: primary + 2 fallbacks
        assert len(result.attempts) == 3

    def test_all_parsers_fail_returns_failure(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """When all parsers fail, result.success is False."""
        decision = _decision("always_fail", ["always_fail"])
        result = orchestrator.execute("run_ac2c", "src_ac2c", sample_file, decision)

        assert result.success is False
        assert result.fallback_used is False
        assert result.docir is None


# ---------------------------------------------------------------------------
# AC3: Final result records fallback usage
# ---------------------------------------------------------------------------


class TestResultRecordsFallback:
    """AC3: The final parse result records whether a fallback parser was used."""

    def test_primary_success_no_fallback_recorded(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """Primary success: fallback_used is False, fallback_parser is None."""
        decision = _decision("always_succeed")
        result = orchestrator.execute("run_ac3", "src_ac3", sample_file, decision)

        assert result.fallback_used is False
        assert result.fallback_parser is None
        assert result.primary_succeeded is True
        assert result.final_parser == "always_succeed"

    def test_fallback_success_records_fallback(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """Fallback used: fallback_used is True, fallback_parser is set."""
        decision = _decision("always_fail", ["fallback_succeed"])
        result = orchestrator.execute("run_ac3b", "src_ac3b", sample_file, decision)

        assert result.fallback_used is True
        assert result.fallback_parser == "fallback_succeed"
        assert result.primary_succeeded is False
        assert result.final_parser == "fallback_succeed"

    def test_fallback_docir_is_returned(
        self,
        orchestrator: PipelineOrchestrator,
        sample_file: Path,
    ) -> None:
        """When fallback succeeds, the DocIR comes from the fallback parser."""
        decision = _decision("always_fail", ["fallback_succeed"])
        result = orchestrator.execute("run_ac3c", "src_ac3c", sample_file, decision)

        assert result.docir is not None
        assert result.docir.parser == "fallback_succeed"
        assert result.docir.blocks[0].text_plain == "fallback output"
