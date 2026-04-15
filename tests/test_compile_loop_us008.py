"""Tests for US-008: Refactor compile stage into a unified page loop."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docos.models.run import RunManifest, RunStatus, StageStatus
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


def _make_test_config(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = config_dir / "router.yaml"
    cfg_path.write_text(_TEST_CONFIG_YAML, encoding="utf-8")
    return cfg_path


def _ensure_fixtures() -> None:
    from tests.fixtures.build_fixtures import get_all_fixtures
    get_all_fixtures()


class TestUnifiedCompileLoop:
    """US-008: Compile stage uses unified page loop for all page types."""

    def test_compile_builds_compiled_pages_list(self, tmp_path: Path) -> None:
        """Compile stage builds a list of compiled pages (not source-only)."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_test_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        assert result.status == RunStatus.COMPLETED

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Should have at least source page
        assert manifest.compiled_page_count >= 1
        assert "source" in manifest.compiled_page_types

    def test_compile_computes_patches_per_page(self, tmp_path: Path) -> None:
        """Each compiled page generates a patch through the same loop."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_test_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        assert result.status == RunStatus.COMPLETED

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Patch count should match page count (or be close)
        assert manifest.compiled_patch_count >= 1
        assert manifest.compiled_patch_count <= manifest.compiled_page_count + 1  # allow margin

    def test_manifest_stores_compile_summary(self, tmp_path: Path) -> None:
        """RunManifest stores page count, page types, and patch count after compile."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_test_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        assert isinstance(manifest.compiled_page_count, int)
        assert manifest.compiled_page_count > 0
        assert isinstance(manifest.compiled_page_types, list)
        assert len(manifest.compiled_page_types) > 0
        assert isinstance(manifest.compiled_patch_count, int)
        assert manifest.compiled_patch_count >= 0
