# Skill: docos-parse
## Description
Parse a raw document into canonical DocIR (Document Intermediate Representation) using a primary parser selected by the route decision, with automatic fallback to alternative parsers on failure.

## Input
- `source_id`: Registered source identifier
- `route_decision`: Route decision object from docos-route (selected route, primary/fallback parsers, matched signals)
- `raw_content`: Raw document bytes or stream

## Output
- Canonical DocIR object conforming to `schemas/docir.schema.json`
- Parser metadata: parser name, version, parse duration, warnings

## Invariants
- Output always validates against the DocIR JSON Schema
- No information loss: all recoverable text, tables, images, and structural elements are preserved
- Deterministic: same input always produces structurally equivalent DocIR
- Parse errors never produce partial or malformed DocIR; failure must raise a documented exception

## Fallback
- If the primary parser fails or times out, retry with the first fallback parser from `route_decision`
- If all fallback parsers fail, attempt a generic plaintext extraction as last resort
- If plaintext extraction also fails, emit a structured error object with diagnostic info and halt

## Evaluation
- DocIR passes schema validation on every parse
- Round-trip fidelity: re-parsing the same document yields diff-free DocIR
- Fallback coverage: at least one parser succeeds for every supported MIME type
- Parse latency within configured SLA threshold per document class
