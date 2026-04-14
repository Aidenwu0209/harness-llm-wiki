"""Source Registry — tracks every imported document across runs and parsers.

Each source has a stable identity (source_id) that persists across
multiple ingest runs, parser versions, and wiki updates.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Source status
# ---------------------------------------------------------------------------

class SourceStatus(str, Enum):
    """Lifecycle status of a source record."""

    UPLOADED = "uploaded"
    ROUTING = "routing"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    EXTRACTING = "extracting"
    COMPILING = "compiling"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Ingest history entry
# ---------------------------------------------------------------------------

class IngestEntry(BaseModel):
    """A single ingest attempt record."""

    run_id: str
    ingested_at: datetime = Field(default_factory=datetime.now)
    parser: str = ""
    parser_version: str = ""
    schema_version: str = "1"
    status: Literal["success", "failed", "partial"] = "success"
    error_detail: str | None = None
    fallback_used: bool = False
    docir_id: str | None = None
    patch_id: str | None = None


# ---------------------------------------------------------------------------
# Source record
# ---------------------------------------------------------------------------

class SourceRecord(BaseModel):
    """A source registry record — one per unique document.

    Invariants:
    - source_id must be stable and unique across the system.
    - source_hash is used for duplicate detection.
    - ingest_history grows over time; never delete old entries.
    - raw source must be immutable once stored.
    """

    # Identity
    source_id: str = Field(description="Stable unique source identifier")
    source_hash: str = Field(description="SHA-256 hash of original file content")

    # File metadata
    file_name: str
    mime_type: str = "application/pdf"
    byte_size: int = Field(ge=0)

    # Temporal
    created_at: datetime = Field(default_factory=datetime.now)
    ingested_at: datetime | None = Field(default=None, description="Latest successful ingest time")

    # Ingest tracking
    ingest_count: int = Field(default=0, ge=0)
    ingest_history: list[IngestEntry] = Field(default_factory=list)

    # Classification
    language_hint: list[str] = Field(default_factory=list)
    origin: str = Field(default="", description="Where this source came from (upload, api, batch)")
    tags: list[str] = Field(default_factory=list)
    owner: str = Field(default="", description="Owner / responsible person")

    # Current state
    status: SourceStatus = SourceStatus.UPLOADED

    # Links
    latest_run_id: str | None = None
    latest_docir_id: str | None = None

    # Cross-references
    wiki_page_path: str | None = Field(
        default=None, description="Path to the generated source wiki page"
    )
    review_ids: list[str] = Field(
        default_factory=list, description="IDs of review items linked to this source"
    )

    # Raw storage
    raw_storage_path: str | None = Field(
        default=None, description="Path to immutable raw source copy"
    )

    def add_ingest(self, entry: IngestEntry) -> None:
        """Record a new ingest attempt."""
        self.ingest_history.append(entry)
        self.ingest_count = len(self.ingest_history)
        self.latest_run_id = entry.run_id
        if entry.status == "success" and entry.docir_id:
            self.latest_docir_id = entry.docir_id
            self.ingested_at = entry.ingested_at
            self.status = SourceStatus.COMPLETED
        elif entry.status == "failed":
            self.status = SourceStatus.FAILED
