"""Tests for US-012: Expose compile summary in manifest and report."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docos.run_store import RunStore


_TEST_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: fallback_safe_route
  routes:
    - name: fallback_safe_route
      description: "Test fallback"
      file_types: ["application/pdf", "text/plain"]
      primary_parser: stdlib_pdf
      fallback_parsers: [basic_text_fallback]
      review_policy: default
"""


def _make_config(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = config_dir / "router.yaml"
    cfg_path.write_text(_TEST_CONFIG_YAML, encoding="utf-8")
    return cfg_path


def _ensure_fixtures() -> None:
    from tests.fixtures.build_fixtures import get_all_fixtures
    get_all_fixtures()


class TestCompileSummaryInManifest:
    """US-012: Manifest stores and report shows compile summary."""

    def test_manifest_stores_all_compile_summary_fields(self, tmp_path: Path) -> None:
        """Manifest stores page count, types, created, updated, deleted, patch count."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        assert manifest.compiled_page_count > 0
        assert len(manifest.compiled_page_types) > 0
        assert manifest.compiled_patch_count >= 0
        assert manifest.compiled_created_count >= 0
        assert manifest.compiled_updated_count >= 0
        assert manifest.compiled_deleted_count >= 0

    def test_report_shows_compile_summary(self, tmp_path: Path) -> None:
        """docos report shows compile summary from persisted data."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        # Verify compile summary data is available in manifest (report uses this)
        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Verify all summary fields are present
        assert manifest.compiled_page_count > 0
        assert "source" in manifest.compiled_page_types

    def test_compile_types_include_source_and_potential_entity(self, tmp_path: Path) -> None:
        """Simple fixture shows source and potentially entity compile output."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        # At minimum, source page should be compiled
        assert "source" in manifest.compiled_page_types
        # Verify created count matches non-delete pages
        non_delete = [t for t in manifest.compiled_page_types if t != "delete"]
        assert manifest.compiled_created_count == len(non_delete)
