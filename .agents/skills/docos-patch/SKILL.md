# Skill: docos-patch
## Description
Generate, validate, and manage patches that describe wiki state transitions. Each patch encodes the difference between the current wiki state and the proposed new state derived from extraction results.

## Input
- `extraction_result`: Entities, claims, and relations from docos-extract
- `current_wiki_state`: Snapshot of the current wiki knowledge graph or reference to it
- `patch_policy`: Optional policy governing merge strategy (overwrite, merge, append) and conflict resolution

## Output
- `patch_id`: Unique identifier for the generated patch
- `operations[]`: Ordered array of CRUD operations (add_entity, update_entity, add_relation, remove_claim, etc.)
- `conflict_report[]`: List of conflicts detected against current wiki state, with suggested resolutions
- Patch metadata: creation timestamp, source document reference, operation counts

## Invariants
- Patches are atomic: either all operations apply or none do
- Every operation references valid target IDs in the wiki state
- Patches are idempotent: applying the same patch twice yields the same result as applying it once
- Patch ordering is deterministic and conflict-free within a single patch
- Generated patches are serializable to disk for audit and replay

## Fallback
- If conflict detection finds unresolvable conflicts, generate the patch with conflicts flagged and defer to docos-review
- If patch generation fails mid-way, discard the partial patch and report the error
- If the current wiki state snapshot is stale, re-snapshot and regenerate

## Evaluation
- Generated patch applies cleanly against the current wiki state without errors
- No orphaned references in any operation
- Idempotency: double-application produces identical wiki state
- Patch size within configurable limits to prevent oversized transactions
