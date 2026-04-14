"""IR Store — persist and retrieve canonical DocIR artifacts.

Storage layout::

    <base_dir>/<run_id>.json   — one DocIR artifact per run
"""

from __future__ import annotations

import json
from pathlib import Path

from docos.models.docir import DocIR


class IRStore:
    """File-backed store for DocIR artifacts."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def _artifact_path(self, run_id: str) -> Path:
        return self._base / f"{run_id}.json"

    def save(self, docir: DocIR, run_id: str) -> Path:
        """Persist a DocIR artifact under the given run_id.

        The DocIR is written as JSON with run_id and source_id embedded
        as top-level metadata fields alongside the canonical DocIR payload.

        Args:
            docir: The canonical DocIR to persist.
            run_id: The run this artifact belongs to.

        Returns:
            Path to the written artifact file.
        """
        payload = json.loads(docir.model_dump_json())
        payload["_run_id"] = run_id
        path = self._artifact_path(run_id)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def get(self, run_id: str) -> DocIR | None:
        """Retrieve a persisted DocIR by run_id.

        Returns:
            The DocIR, or ``None`` if not found.
        """
        path = self._artifact_path(run_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        # Strip store-level metadata before validation
        data.pop("_run_id", None)
        return DocIR.model_validate(data)

    def exists(self, run_id: str) -> bool:
        """Check whether a DocIR artifact exists for the given run_id."""
        return self._artifact_path(run_id).exists()
