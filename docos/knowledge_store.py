"""Knowledge Store — persist and retrieve extracted knowledge artifacts.

A knowledge artifact bundles entities, claims, and relations extracted during
a single pipeline run.

Storage layout::

    <base_dir>/<run_id>/
        entities.json       — list of EntityRecord
        claims.json         — list of ClaimRecord
        relations.json      — list of KnowledgeRelation
        meta.json           — run_id, source_id, timestamps
"""

from __future__ import annotations

import json
from pathlib import Path

from docos.models.knowledge import ClaimRecord, EntityRecord, KnowledgeRelation


class KnowledgeArtifact:
    """In-memory bundle of extracted knowledge for a single run."""

    def __init__(
        self,
        run_id: str,
        source_id: str,
        entities: list[EntityRecord] | None = None,
        claims: list[ClaimRecord] | None = None,
        relations: list[KnowledgeRelation] | None = None,
    ) -> None:
        self.run_id = run_id
        self.source_id = source_id
        self.entities = entities or []
        self.claims = claims or []
        self.relations = relations or []


class KnowledgeStore:
    """File-backed store for knowledge artifacts."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def _run_dir(self, run_id: str) -> Path:
        return self._base / run_id

    def save(self, artifact: KnowledgeArtifact) -> Path:
        """Persist a knowledge artifact to disk.

        Returns:
            Path to the artifact directory.
        """
        run_dir = self._run_dir(artifact.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # Entities
        entities_data = [json.loads(e.model_dump_json()) for e in artifact.entities]
        (run_dir / "entities.json").write_text(
            json.dumps(entities_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Claims
        claims_data = [json.loads(c.model_dump_json(by_alias=True)) for c in artifact.claims]
        (run_dir / "claims.json").write_text(
            json.dumps(claims_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Relations
        relations_data = [json.loads(r.model_dump_json()) for r in artifact.relations]
        (run_dir / "relations.json").write_text(
            json.dumps(relations_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Meta
        meta = {"run_id": artifact.run_id, "source_id": artifact.source_id}
        (run_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return run_dir

    def get(self, run_id: str) -> KnowledgeArtifact | None:
        """Load a knowledge artifact by run_id.

        Returns:
            The artifact, or ``None`` if not found.
        """
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return None

        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            return None

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        artifact = KnowledgeArtifact(
            run_id=meta["run_id"],
            source_id=meta["source_id"],
        )

        # Entities
        entities_path = run_dir / "entities.json"
        if entities_path.exists():
            raw = json.loads(entities_path.read_text(encoding="utf-8"))
            artifact.entities = [EntityRecord.model_validate(e) for e in raw]

        # Claims
        claims_path = run_dir / "claims.json"
        if claims_path.exists():
            raw = json.loads(claims_path.read_text(encoding="utf-8"))
            artifact.claims = [ClaimRecord.model_validate(c) for c in raw]

        # Relations
        relations_path = run_dir / "relations.json"
        if relations_path.exists():
            raw = json.loads(relations_path.read_text(encoding="utf-8"))
            artifact.relations = [KnowledgeRelation.model_validate(r) for r in raw]

        return artifact

    def exists(self, run_id: str) -> bool:
        """Check whether a knowledge artifact exists for the given run_id."""
        return self._run_dir(run_id).exists()
