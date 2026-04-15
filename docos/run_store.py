"""Run Store — persist and retrieve run manifests.

Storage layout::

    <base_dir>/manifests/<run_id>.json   — one manifest file per run
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from docos.models.run import RunManifest, RunStatus


class RunNotFoundError(Exception):
    """Raised when a run manifest cannot be found by its run_id."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Run manifest not found: {run_id}")


class RunStore:
    """File-backed store for run manifests."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._manifests_dir = base_dir / "manifests"
        self._manifests_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _manifest_path(self, run_id: str) -> Path:
        return self._manifests_dir / f"{run_id}.json"

    @staticmethod
    def generate_run_id(source_hash: str, timestamp: datetime | None = None) -> str:
        """Generate a deterministic run ID from source hash and timestamp.

        Format: ``run_<hash_prefix>_<time_hex>``
        """
        ts = timestamp or datetime.now()
        ts_hex = hex(int(ts.timestamp() * 1000))[2:]
        return f"run_{source_hash[:8]}_{ts_hex}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        source_id: str,
        source_hash: str,
        source_file_path: str,
        artifact_root: str | None = None,
    ) -> RunManifest:
        """Create and persist a new run manifest.

        Args:
            source_id: Linked source identifier.
            source_hash: SHA-256 hash of the source file (used for run_id derivation).
            source_file_path: Original file path of the source.
            artifact_root: Optional artifact root override. Defaults to
                ``<base_dir>/artifacts/<run_id>``.

        Returns:
            The newly created and persisted run manifest.
        """
        run_id = self.generate_run_id(source_hash)
        if artifact_root is None:
            artifact_root = str(self._base / "artifacts" / run_id)

        manifest = RunManifest.create(
            run_id=run_id,
            source_id=source_id,
            source_file_path=source_file_path,
            artifact_root=artifact_root,
        )
        self._persist(manifest)
        return manifest

    def get(self, run_id: str) -> RunManifest | None:
        """Load a run manifest by run_id.

        Returns:
            The manifest, or ``None`` if not found.
        """
        path = self._manifest_path(run_id)
        if not path.exists():
            return None
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def get_or_raise(self, run_id: str) -> RunManifest:
        """Load a run manifest by run_id, raising a structured error if missing.

        Raises:
            RunNotFoundError: If no manifest exists for the given run_id.
        """
        manifest = self.get(run_id)
        if manifest is None:
            raise RunNotFoundError(run_id)
        return manifest

    def get_by_source_id(self, source_id: str) -> RunManifest | None:
        """Load a run manifest by source_id.

        Scans all stored manifests and returns the first match.

        Returns:
            The manifest, or ``None`` if no run is linked to the given source_id.
        """
        for manifest in self.list_runs():
            if manifest.source_id == source_id:
                return manifest
        return None

    def find_latest_run(self, source_id: str) -> str | None:
        """Find the most recent run_id for a given source_id.

        Scans all manifests, filters by source_id, and returns the run_id
        of the manifest with the latest ``started_at`` timestamp.

        Returns:
            The latest run_id, or ``None`` if no runs match.
        """
        candidates = [
            m for m in self.list_runs() if m.source_id == source_id
        ]
        if not candidates:
            return None
        # Sort by started_at descending; fall back to created_at
        candidates.sort(
            key=lambda m: m.started_at or m.created_at or datetime.min,
            reverse=True,
        )
        return candidates[0].run_id

    def update(self, manifest: RunManifest) -> None:
        """Persist an updated manifest."""
        self._persist(manifest)

    def list_runs(self) -> list[RunManifest]:
        """List all stored run manifests."""
        manifests: list[RunManifest] = []
        for path in self._manifests_dir.glob("*.json"):
            manifest = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
            manifests.append(manifest)
        return manifests

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, manifest: RunManifest) -> None:
        path = self._manifest_path(manifest.run_id)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
