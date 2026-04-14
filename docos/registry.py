"""Source Registry service — duplicate detection and ingest history management.

The registry is the single source of truth for "which documents have been
imported". It uses SHA-256 hashing for identity and tracks every ingest attempt.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.models.source import IngestEntry, SourceRecord, SourceStatus
from docos.source_store import RawStorage


class SourceRegistry:
    """Manages source records with hash-based duplicate detection.

    Storage layout:
        <base_dir>/index.json       — mapping of source_id → source_hash
        <base_dir>/records/<source_id>.json — full source records
    """

    def __init__(self, base_dir: Path, raw_storage: RawStorage) -> None:
        self._base = base_dir
        self._raw = raw_storage
        self._index_path = base_dir / "index.json"
        self._records_dir = base_dir / "records"
        self._records_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Index management (hash → source_id mapping)
    # ------------------------------------------------------------------

    def _load_index(self) -> dict[str, str]:
        """Load hash → source_id index."""
        if not self._index_path.exists():
            return {}
        return json.loads(self._index_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    def _save_index(self, index: dict[str, str]) -> None:
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Record persistence
    # ------------------------------------------------------------------

    def _record_path(self, source_id: str) -> Path:
        return self._records_dir / f"{source_id}.json"

    def _save_record(self, record: SourceRecord) -> None:
        path = self._record_path(record.source_id)
        path.write_text(
            record.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _load_record(self, source_id: str) -> SourceRecord | None:
        path = self._record_path(source_id)
        if not path.exists():
            return None
        return SourceRecord.model_validate_json(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_by_hash(self, file_hash: str) -> SourceRecord | None:
        """Find an existing source by its content hash."""
        index = self._load_index()
        source_id = index.get(file_hash)
        if source_id is None:
            return None
        return self._load_record(source_id)

    def register(
        self,
        source_file: Path,
        file_name: str | None = None,
        mime_type: str = "application/pdf",
        origin: str = "",
        tags: list[str] | None = None,
        owner: str = "",
    ) -> SourceRecord:
        """Register a new source or return existing if duplicate.

        Steps:
        1. Compute hash of file content.
        2. Check for existing source with same hash.
        3. If found, return existing record (this is a re-import).
        4. If new, create record and store immutable copy.

        Returns:
            The source record (new or existing).
        """
        file_hash = RawStorage.compute_hash(source_file)
        file_name = file_name or source_file.name

        # Duplicate check
        existing = self.find_by_hash(file_hash)
        if existing is not None:
            return existing

        # New source
        source_id = f"src_{file_hash[:12]}"
        byte_size = source_file.stat().st_size

        record = SourceRecord(
            source_id=source_id,
            source_hash=file_hash,
            file_name=file_name,
            mime_type=mime_type,
            byte_size=byte_size,
            origin=origin,
            tags=tags or [],
            owner=owner,
        )

        # Store immutable copy
        stored_path = self._raw.store(record, source_file)
        record.raw_storage_path = str(stored_path)

        # Persist record
        self._save_record(record)

        # Update index
        index = self._load_index()
        index[file_hash] = source_id
        self._save_index(index)

        return record

    def record_ingest(
        self,
        source_id: str,
        run_id: str,
        parser: str = "",
        parser_version: str = "",
        schema_version: str = "1",
        status: str = "success",
        error_detail: str | None = None,
        fallback_used: bool = False,
        docir_id: str | None = None,
        patch_id: str | None = None,
    ) -> SourceRecord:
        """Record an ingest attempt for a source.

        Returns:
            Updated source record.
        """
        record = self._load_record(source_id)
        if record is None:
            msg = f"Source not found: {source_id}"
            raise ValueError(msg)

        entry = IngestEntry(
            run_id=run_id,
            parser=parser,
            parser_version=parser_version,
            schema_version=schema_version,
            status=status,  # type: ignore[arg-type]
            error_detail=error_detail,
            fallback_used=fallback_used,
            docir_id=docir_id,
            patch_id=patch_id,
        )
        record.add_ingest(entry)
        self._save_record(record)
        return record

    def get(self, source_id: str) -> SourceRecord | None:
        """Get a source record by ID."""
        return self._load_record(source_id)

    def list_sources(self) -> list[SourceRecord]:
        """List all registered sources."""
        records: list[SourceRecord] = []
        for path in self._records_dir.glob("*.json"):
            record = SourceRecord.model_validate_json(path.read_text(encoding="utf-8"))
            records.append(record)
        return records
