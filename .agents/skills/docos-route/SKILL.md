# Skill: docos-route
## Description
Route a document to the optimal parsing pipeline based on extracted signals.

## Input
- `source_id`: Registered source identifier

## Output
- Route decision with selected route, primary/fallback parsers, matched signals

## Invariants
- Route selection is config-driven, not hardcoded
- All decisions logged for audit
- Signals extracted deterministically

## Fallback
- Falls back to `fallback_safe_route` if no specific match

## Evaluation
- Same document always routes to same route
- Route log persisted to disk
