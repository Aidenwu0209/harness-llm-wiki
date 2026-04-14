"""Tests for US-008: Persist parser attempt logs and debug assets.

Acceptance criteria:
- Each parser attempt writes parser name, timestamps, status, and error reason when present
- Successful and failed attempts both write debug artifacts under a stable run-scoped path
- The RunManifest links to the persisted parser attempt records
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.debug_store import DebugAssetStore
from docos.models.run import RunManifest, StageStatus
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserBackend, ParserRegistry, ParseResult
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import RouteDecision
from docos.run_store import RunStore


def _write_text_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\n"
        b"endobj\n"
        b"4 0 obj\n"
        b"<< /Length 44 >>\n"
        b"stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


def _write_encrypted_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"/Encrypt\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


# ---------------------------------------------------------------------------
# AC1: Each parser attempt writes parser name, timestamps, status, error reason
# ---------------------------------------------------------------------------


class TestAttemptLogContents:
    """Each parser attempt writes parser name, timestamps, status, and error
    reason when present."""

    def test_successful_attempt_log_has_name_timestamp_status(
        self, tmp_path: Path
    ) -> None:
        """Successful attempt log contains parser name, status=True, timestamp."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_s1",
            source_id="src_s1",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assert result.parse_log_path is not None

        log_data = json.loads(Path(result.parse_log_path).read_text(encoding="utf-8"))
        assert log_data["parser_name"] == "stdlib_pdf"
        assert log_data["success"] is True
        assert "logged_at" in log_data
        assert "elapsed_seconds" in log_data

    def test_failed_attempt_log_has_name_status_error(
        self, tmp_path: Path
    ) -> None:
        """Failed attempt log contains parser name, status=False, error reason."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=["basic_text_fallback"],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_f1",
            source_id="src_f1",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success  # fallback succeeds
        assert len(result.failed_attempt_paths) >= 1

        fail_log = json.loads(
            Path(result.failed_attempt_paths[0]).read_text(encoding="utf-8")
        )
        assert fail_log["parser_name"] == "stdlib_pdf"
        assert fail_log["success"] is False
        assert fail_log["error"] is not None
        assert "logged_at" in fail_log
        assert "elapsed_seconds" in fail_log


# ---------------------------------------------------------------------------
# AC2: Successful and failed attempts both write debug artifacts
# ---------------------------------------------------------------------------


class TestBothSuccessAndFailureWriteAssets:
    """Successful and failed attempts both write debug artifacts under a
    stable run-scoped path."""

    def test_success_writes_debug_assets(self, tmp_path: Path) -> None:
        """Successful parse writes debug assets on disk."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_s2",
            source_id="src_s2",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assert result.debug_assets_dir is not None
        debug_dir = Path(result.debug_assets_dir)
        assert debug_dir.exists()

        # parse_log.json should exist under the run-scoped path
        assert (debug_dir / "parse_log.json").exists()

    def test_failure_writes_debug_assets(self, tmp_path: Path) -> None:
        """Failed parse also writes debug assets on disk."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())
        registry.register(BasicTextFallbackParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_encrypted_pdf(tmp_path / "enc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=["basic_text_fallback"],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_f2",
            source_id="src_f2",
            file_path=pdf_path,
            route_decision=decision,
        )

        # Failed attempt path should exist on disk
        assert len(result.failed_attempt_paths) >= 1
        for fpath in result.failed_attempt_paths:
            assert Path(fpath).exists()

    def test_stable_run_scoped_path_structure(self, tmp_path: Path) -> None:
        """Assets are stored under source_id/run_id/parser_name structure."""
        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id="run_stable",
            source_id="src_stable",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assert result.debug_assets_dir is not None
        path_str = result.debug_assets_dir
        assert "src_stable" in path_str
        assert "run_stable" in path_str
        assert "stdlib_pdf" in path_str


# ---------------------------------------------------------------------------
# AC3: RunManifest links to persisted parser attempt records
# ---------------------------------------------------------------------------


class TestRunManifestLinksToAttemptRecords:
    """The RunManifest links to the persisted parser attempt records."""

    def test_manifest_debug_artifact_path_set(self, tmp_path: Path) -> None:
        """After parse with debug_store, manifest.debug_artifact_path points to the debug dir."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_m1",
            source_hash="a" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id=manifest.run_id,
            source_id="src_m1",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        assert result.debug_assets_dir is not None

        # Simulate what PipelineRunner does: link manifest to debug dir
        manifest.debug_artifact_path = result.debug_assets_dir
        run_store.update(manifest)

        # Reload manifest and verify the link persists
        loaded = run_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.debug_artifact_path is not None
        assert Path(loaded.debug_artifact_path).exists()

    def test_manifest_survives_restart(self, tmp_path: Path) -> None:
        """A new RunStore instance can reload the manifest with debug asset links."""
        run_store = RunStore(tmp_path)
        manifest = run_store.create(
            source_id="src_m2",
            source_hash="b" * 64,
            source_file_path=str(tmp_path / "doc.pdf"),
        )

        registry = ParserRegistry()
        registry.register(StdlibPDFParser())

        debug_store = DebugAssetStore(tmp_path / "debug")
        orchestrator = PipelineOrchestrator(registry, debug_store=debug_store)

        pdf_path = _write_text_pdf(tmp_path / "doc.pdf")
        decision = RouteDecision(
            selected_route="test",
            primary_parser="stdlib_pdf",
            fallback_parsers=[],
            expected_risks=[],
            post_parse_repairs=[],
            review_policy="default",
        )

        result = orchestrator.execute(
            run_id=manifest.run_id,
            source_id="src_m2",
            file_path=pdf_path,
            route_decision=decision,
        )

        assert result.success
        manifest.debug_artifact_path = result.debug_assets_dir
        run_store.update(manifest)

        # Simulate new process — new RunStore
        new_store = RunStore(tmp_path)
        loaded = new_store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.debug_artifact_path is not None
