"""DocIR invariant validation — structural checks before extraction and compile.

Ensures downstream stages only consume consistent, well-formed DocIR.
All validation is deterministic and returns structured error messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docos.models.docir import DocIR


@dataclass
class InvariantError:
    """A single invariant violation."""

    code: str
    message: str
    page_no: int | None = None
    block_id: str | None = None


@dataclass
class InvariantReport:
    """Result of DocIR invariant validation."""

    errors: list[InvariantError] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def add(self, code: str, message: str, page_no: int | None = None, block_id: str | None = None) -> None:
        self.errors.append(InvariantError(code=code, message=message, page_no=page_no, block_id=block_id))


def validate_docir(docir: DocIR) -> InvariantReport:
    """Validate DocIR structural invariants.

    Checks:
    1. All block_ids are unique across the document.
    2. All page.blocks references point to existing blocks.
    3. Reading order values are unique within each page.
    4. Relation source/target blocks exist in the document.
    5. page_count matches the actual number of Page objects.

    Args:
        docir: The canonical DocIR to validate.

    Returns:
        InvariantReport with any violations found.
    """
    report = InvariantReport()

    block_ids = {b.block_id for b in docir.blocks}

    # 1. Duplicate block_ids
    seen_ids: dict[str, int] = {}
    for b in docir.blocks:
        if b.block_id in seen_ids:
            report.add(
                code="duplicate_block_id",
                message=f"Duplicate block_id '{b.block_id}' (first at page {seen_ids[b.block_id]}, duplicate at page {b.page_no})",
                page_no=b.page_no,
                block_id=b.block_id,
            )
        else:
            seen_ids[b.block_id] = b.page_no

    # 2. Invalid page-block references
    for page in docir.pages:
        for block_id in page.blocks:
            if block_id not in block_ids:
                report.add(
                    code="invalid_page_block_ref",
                    message=f"Page {page.page_no} references non-existent block_id '{block_id}'",
                    page_no=page.page_no,
                    block_id=block_id,
                )

    # 3. Duplicate reading order within a page
    for page in docir.pages:
        page_blocks = [b for b in docir.blocks if b.page_no == page.page_no]
        seen_order: set[int] = set()
        for b in page_blocks:
            if b.reading_order in seen_order:
                report.add(
                    code="duplicate_reading_order",
                    message=f"Duplicate reading_order {b.reading_order} on page {b.page_no} (block {b.block_id})",
                    page_no=b.page_no,
                    block_id=b.block_id,
                )
            else:
                seen_order.add(b.reading_order)

    # 4. Invalid relation block references
    for rel in docir.relations:
        if rel.source_block_id not in block_ids:
            report.add(
                code="invalid_relation_source",
                message=f"Relation '{rel.relation_id}' references non-existent source block '{rel.source_block_id}'",
                block_id=rel.source_block_id,
            )
        if rel.target_block_id not in block_ids:
            report.add(
                code="invalid_relation_target",
                message=f"Relation '{rel.relation_id}' references non-existent target block '{rel.target_block_id}'",
                block_id=rel.target_block_id,
            )

    # 5. Page count mismatch
    if docir.page_count != len(docir.pages):
        report.add(
            code="page_count_mismatch",
            message=f"page_count ({docir.page_count}) does not match actual pages ({len(docir.pages)})",
        )

    return report
