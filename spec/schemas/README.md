# Supporting schemas

Files in this directory are versioned machine-readable supporting contracts.
They are not normative VMx behavior chapters unless a chapter explicitly says
otherwise.

- `consumer-conformance-v1.schema.json` — non-normative operation/assertion
  adapter suites for consumer-owned fixtures and factories. See ADR-0102.
  Case IDs are unique within a suite. JSON Schema cannot express that rule, so
  a runner MUST reject a duplicate case `id` (ADR-0102 §2.1, ADR-0243).

- `fixtures/` — one non-normative JSON Schema (draft 2020-12) for each file in
  `spec/fixtures/`, for `$schema-version` `1.0.0`:

  - `command-truthtable-v1.schema.json`
  - `derived-properties-v1.schema.json`
  - `lifecycle-transitions-v1.schema.json`
  - `message-ordering-v1.schema.json`

  `tools/check-fixture-contracts.py` validates each fixture against its schema
  in CI, and keeps the inventory and cross-field rules that a schema cannot
  express. The schemas stay in this subdirectory. The TypeScript package copies
  only the top-level `*.json` files, so the package does not change (ADR-0243).
