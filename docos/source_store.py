"""Immutable raw source storage.

Raw source files are the ultimate ground truth. Once stored, they must
never be overwritten by any process — LLM, parser, repair, or human.

Storage layout:
    raw/<source_id>/original.<ext>
    raw/<source_id>/metadata.json
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.models.source import SourceRecord


class RawStorage:
    """Manages immutable raw source file storage.

    Design invariants:
    - Files are written once and never overwritten.
    - Each file is stored under raw/<source_id>/original.<ext>
    - Metadata linking the file to the source registry is stored alongside.
    - Write operations check for existing files before copying.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _source_dir(self, source_id: str) -> Path:
        return self._base / source_id

    def _original_path(self, source_id: str, file_name: str) -> Path:
        ext = Path(file_name).suffix or ".bin"
        return self._source_dir(source_id) / f"original{ext}"

    def _metadata_path(self, source_id: str) -> Path:
        return self._source_dir(source_id) / "metadata.json"

    def store(self, source: SourceRecord, source_file: Path) -> Path:
        """Persist an immutable copy of the source file.

        Args:
            source: The source registry record.
            source_file: Path to the file to store.

        Returns:
            Path to the stored file.

        Raises:
            FileExistsError: If a file is already stored for this source.
            FileNotFoundError: If source_file does not exist.
        """
        if not source_file.exists():
            msg = f"Source file not found: {source_file}"
            raise FileNotFoundError(msg)

        dest_dir = self._source_dir(source.source_id)
        dest_file = self._original_path(source.source_id, source.file_name)

        # Guard: never overwrite
        if dest_file.exists():
            msg = f"Raw source already exists for {source.source_id}: {dest_file}"
            raise FileExistsError(msg)

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy the file
        shutil.copy2(source_file, dest_file)

        # Verify hash matches
        stored_hash = self._compute_hash(dest_file)
        if stored_hash != source.source_hash:
            # Hash mismatch — clean up and raise
            dest_file.unlink()
            msg = f"Hash mismatch for {source.source_id}: expected {source.source_hash}, got {stored_hash}"
            raise ValueError(msg)

        # Write metadata
        metadata = {
            "source_id": source.source_id,
            "file_name": source.file_name,
            "mime_type": source.mime_type,
            "byte_size": source.byte_size,
            "source_hash": source.source_hash,
            "stored_at": datetime.now().isoformat(),
            "original_path": str(source_file),
        }
        self._metadata_path(source.source_id).write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return dest_file

    def read_metadata(self, source_id: str) -> dict[str, Any]:
        """Read stored metadata for a source."""
        meta_path = self._metadata_path(source_id)
        if not meta_path.exists():
            msg = f"No metadata found for source: {source_id}"
            raise FileNotFoundError(msg)
        return json.loads(meta_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    def get_path(self, source_id: str, file_name: str) -> Path:
        """Get the path to the stored raw source."""
        return self._original_path(source_id, file_name)

    def exists(self, source_id: str) -> bool:
        """Check if a raw source has been stored."""
        meta_path = self._metadata_path(source_id)
        return meta_path.exists()

    @staticmethod
    def _compute_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def compute_hash(file_path: Path) -> str:
        """Public API to compute SHA-256 hash of a file."""
        return RawStorage._compute_hash(file_path)
