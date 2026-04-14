# Skill: docos-lint
## Description
Run a suite of lint checks on the wiki knowledge graph to enforce structural integrity, schema conformance, consistency rules, and data quality standards. Reports violations and suggested fixes.

## Input
- `wiki_state`: Current wiki knowledge graph snapshot
- `lint_profile`: Optional profile specifying which rule sets to activate (schema, referential, semantic, freshness)

## Output
- `violations[]`: Array of violation objects with `rule_id`, `severity` (error|warning|info), `description`, `location`, `suggested_fix`
- `summary`: Aggregate counts by severity and rule category
- Lint metadata: lint profile used, wiki state version, execution duration

## Invariants
- Lint checks are read-only: they never modify wiki state
- Every violation references a specific location in the wiki graph (entity ID, relation ID, or global scope)
- Severity levels follow strict ordering: error > warning > info
- Rule definitions are externalized and version-controlled, not hardcoded
- Lint execution is deterministic: same wiki state and profile always produce the same violations

## Fallback
- If a custom rule fails to execute, log the failure as a warning and continue with remaining rules
- If the wiki state snapshot is incomplete, run schema-level checks only and flag missing data
- If no lint profile is specified, use the default profile with all rule sets enabled

## Evaluation
- Zero false-positive errors on a known-clean wiki state
- Known violations are always detected (no false negatives on test corpus)
- Lint completes within the configured time budget
- Summary counts match the actual violation array length
