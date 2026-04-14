# Skill: docos-extract
## Description
Extract structured knowledge elements -- entities, claims, and relations -- from a canonical DocIR object, producing an enriched knowledge graph fragment ready for wiki integration.

## Input
- `docir`: Canonical DocIR object from docos-parse
- `extraction_config`: Optional config specifying entity types, relation schemas, and confidence thresholds

## Output
- `entities[]`: Array of extracted entities with `id`, `type`, `name`, `attributes`, `confidence`
- `claims[]`: Array of extracted claims with `id`, `text`, `source_span`, `confidence`
- `relations[]`: Array of extracted relations with `id`, `subject_id`, `predicate`, `object_id`, `confidence`
- Extraction metadata: extractor name, version, entity/claim/relation counts, processing duration

## Invariants
- Every extracted element must reference a valid source span in the originating DocIR
- Entity IDs are deterministically derived from entity name + type to ensure deduplication
- Confidence scores are normalized to [0.0, 1.0] range
- No orphaned relations: every `subject_id` and `object_id` resolves to an entity in the output set

## Fallback
- If full extraction fails, attempt entity-only extraction (skip claims and relations)
- If entity extraction also fails, return an empty extraction result with a structured error diagnostic
- Confidence fallback: elements below the configured threshold are flagged but still included for review

## Evaluation
- All extracted entities and relations pass referential integrity checks
- No duplicate entities with the same deterministic ID
- Extraction recall above minimum threshold on benchmark corpus
- Source span references are verifiable against the input DocIR
