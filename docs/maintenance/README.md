# Maintenance records

This directory holds maintainer records. They are not product documentation.
Use the specification, ADRs, and the documentation site for normative or
operational guidance.

## 1. Live ledgers

Maintainers keep these files current.

- [Maintenance contract ledger](2026-07-01-contract-ledger.md): external
  package, tool, CI, and publication contracts. `tools/check-workflow-pins.py`
  reads its action-pin inventory.
- [Rust parity status](2026-07-16-rust-capability-parity.md): Rust member
  evidence and the open items §12.4.7 and §12.7–§12.12. The documentation site publishes
  it as chapter 12.

## 2. Historical records

These files record point-in-time work. Their paths, versions, and conclusions
can be out of date.

- [Swift NotesShowcase test deadlock](2026-07-16-swift-notesshowcase-test-deadlock.md):
  resolved 2026-07-22.
- [React consumer pilots](2026-08-10-vmx-react-consumer-pilots.md): adapter
  migration pilots for issue 80.
- [TypeScript DevTools DayDreams pilot](2026-08-11-typescript-devtools-daydreams-pilot.md):
  DevTools validation for issue 96.
- [TypeScript testing utilities pilots](2026-08-11-typescript-testing-utilities-pilots.md):
  testing-utility validation for issue 84.
- [Concurrency test audit](2026-09-24-controlled-interleavings-audit.md):
  controlled-interleaving work for issue 348.
