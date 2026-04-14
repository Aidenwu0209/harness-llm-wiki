"""Debug asset store — persists parser outputs, logs, and overlays.

Every parse run produces debug assets that must survive normalization
and repair steps. This store ensures assets are linked to source and
run records and remain available for review and comparison.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.pipeline.parser import ParseResult


class DebugAssetStore:
    """Manages debug assets for parser runs.

    Storage layout:
        <base_dir>/<source_id>/<run_id>/<parser_name>/
            raw_output.json       — original parser output
            parse_log.json        — timing, warnings, errors
            page_images/          — rendered page images (if available)
            overlays/             — bbox / reading order overlays
            assets_index.json     — manifest of all stored assets
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _run_dir(self, source_id: str, run_id: str, parser_name: str) -> Path:
        return self._base / source_id / run_id / parser_name

    def persist_raw_output(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
        raw_output: dict[str, Any],
    ) -> Path:
        """Persist the raw parser output as JSON."""
        run_dir = self._run_dir(source_id, run_id, parser_name)
        run_dir.mkdir(parents=True, exist_ok=True)

        path = run_dir / "raw_output.json"
        path.write_text(
            json.dumps(raw_output, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def persist_parse_log(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
        result: ParseResult,
    ) -> Path:
        """Persist parse execution log."""
        run_dir = self._run_dir(source_id, run_id, parser_name)
        run_dir.mkdir(parents=True, exist_ok=True)

        log_data = {
            "parser_name": result.parser_name,
            "parser_version": result.parser_version,
            "success": result.success,
            "error": result.error,
            "elapsed_seconds": result.elapsed_seconds,
            "pages_parsed": result.pages_parsed,
            "blocks_extracted": result.blocks_extracted,
            "warnings": result.warnings,
            "logged_at": datetime.now().isoformat(),
        }
        path = run_dir / "parse_log.json"
        path.write_text(
            json.dumps(log_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def persist_rendered_pages(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
        page_images: dict[int, Path],
    ) -> list[Path]:
        """Persist rendered page images.

        Args:
            page_images: Mapping of page_no → source image path.

        Returns:
            List of stored image paths.
        """
        run_dir = self._run_dir(source_id, run_id, parser_name)
        img_dir = run_dir / "page_images"
        img_dir.mkdir(parents=True, exist_ok=True)

        stored: list[Path] = []
        for page_no, src_path in sorted(page_images.items()):
            if not src_path.exists():
                continue
            dest = img_dir / f"page_{page_no:04d}{src_path.suffix}"
            shutil.copy2(src_path, dest)
            stored.append(dest)

        return stored

    def persist_overlay(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
        overlay_name: str,
        overlay_data: dict[str, Any],
    ) -> Path:
        """Persist an overlay (bbox, reading order, etc.)."""
        run_dir = self._run_dir(source_id, run_id, parser_name)
        overlay_dir = run_dir / "overlays"
        overlay_dir.mkdir(parents=True, exist_ok=True)

        path = overlay_dir / f"{overlay_name}.json"
        path.write_text(
            json.dumps(overlay_data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def persist_run_result(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
        result: ParseResult,
    ) -> dict[str, Path]:
        """Convenience: persist all debug assets from a ParseResult.

        Returns:
            Mapping of asset name → stored path.
        """
        assets: dict[str, Path] = {}

        # Raw output
        if result.raw_output:
            assets["raw_output"] = self.persist_raw_output(
                source_id, run_id, parser_name, result.raw_output
            )

        # Parse log
        assets["parse_log"] = self.persist_parse_log(
            source_id, run_id, parser_name, result
        )

        # Pre-existing debug assets from parser
        for name, path in result.debug_assets.items():
            if path.exists():
                run_dir = self._run_dir(source_id, run_id, parser_name)
                run_dir.mkdir(parents=True, exist_ok=True)
                dest = run_dir / path.name
                shutil.copy2(path, dest)
                assets[name] = dest

        # Write manifest
        self._write_manifest(source_id, run_id, parser_name, assets)

        return assets

    def _write_manifest(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
        assets: dict[str, Path],
    ) -> None:
        """Write an index of all stored assets for this run."""
        run_dir = self._run_dir(source_id, run_id, parser_name)
        manifest = {
            "source_id": source_id,
            "run_id": run_id,
            "parser_name": parser_name,
            "assets": {name: str(path) for name, path in assets.items()},
            "written_at": datetime.now().isoformat(),
        }
        manifest_path = run_dir / "assets_index.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_assets(
        self,
        source_id: str,
        run_id: str,
        parser_name: str,
    ) -> dict[str, str]:
        """Read the assets manifest for a run."""
        manifest_path = self._run_dir(source_id, run_id, parser_name) / "assets_index.json"
        if not manifest_path.exists():
            return {}
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return data.get("assets", {})  # type: ignore[no-any-return]

    def assets_exist(self, source_id: str, run_id: str, parser_name: str) -> bool:
        """Check if debug assets exist for a run."""
        manifest = self._run_dir(source_id, run_id, parser_name) / "assets_index.json"
        return manifest.exists()
