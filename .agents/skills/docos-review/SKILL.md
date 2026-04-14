# Skill: docos-review
## Description
Route items (patches, lint violations, extraction conflicts, or flagged content) to a human or automated review queue, manage approval workflows, and track resolution status from submission to disposition.

## Input
- `review_item`: The item requiring review (patch, violation, conflict, or flagged content)
- `item_type`: Category of the review item (patch_approval, lint_violation, conflict_resolution, content_flag)
- `priority`: Optional priority level (critical | high | normal | low)
- `context`: Optional supplementary context or reasoning for the review request

## Output
- `review_id`: Unique identifier for the review ticket
- `queue`: Assigned review queue name
- `status`: Initial status (pending_review | auto_approved | rejected)
- `assigned_reviewer`: Reviewer or group assigned (may be a bot for auto-approved items)
- Review metadata: creation timestamp, item type, priority, source reference

## Invariants
- Every review item gets a unique, immutable `review_id`
- Review status transitions follow the state machine: pending_review -> in_review -> approved | rejected | deferred
- No review item is ever silently dropped: all items persist until terminal disposition
- Auto-approval rules are explicit, auditable, and configurable (not hardcoded)
- Review history is append-only: status changes are logged, never overwritten

## Fallback
- If the target review queue is unavailable, enqueue to a default catch-all queue and alert
- If auto-approval rules are ambiguous or contradictory, default to pending_review for human judgment
- If the item type is unrecognized, treat as a generic content_flag with normal priority

## Evaluation
- Every submitted item has exactly one review ticket with a trackable lifecycle
- Status transitions comply with the defined state machine; no invalid transitions
- Auto-approved items satisfy all published auto-approval criteria
- Review response time within SLA thresholds per priority level
