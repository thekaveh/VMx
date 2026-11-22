# ADR 0241 — Derived-property fixture scenarios record their ValueChanged emissions

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapter 15 §6 and §7, `DPROP-012`)
- **Extends:** [ADR-0011](0011-derived-properties.md) with an emission field in
  the §7 fixture format. Related: #374, #1785, #1788, #1835.

## 1. Context

`spec/fixtures/derived-properties.json` is loaded by the `DPROP-012` test of
all five flavors. Its `distinct-until-changed` scenario started at `[5, 5]` and
applied `[0, 3]` and `[1, 7]`, so the recomputes gave 10, 8 and 10. No recompute
equalled the value before it, so the scenario never exercised the equality gate
of chapter 15 §6.

`DPROP-012` compared only the `Value` reads, one per step. An equal recompute
leaves `Value` unchanged with or without the gate, so those reads could not
detect a missing gate. A `DerivedProperty` that published `ValueChanged` on
every recompute passed `DPROP-012` in C#, Python, TypeScript, Swift and Rust.
Only the per-flavor `DPROP-010` test caught it, so the shared fixture gave no
cross-flavor check for the rule its name states.

Chapter 15 §7 listed four scenario fields and none for emissions.
`tools/check-fixture-contracts.py` requires the exact set of scenario fields,
so a new field also needed a checker change.

## 2. Decision

1. Each scenario in `spec/fixtures/derived-properties.json` carries
   `expected_emissions`: the values published on `ValueChanged` after
   construction, in order. An equal recompute publishes nothing and adds no
   entry. Chapter 15 §7 defines the field.
1. The `distinct-until-changed` scenario gets a third mutation, `[0, 3]`, whose
   recompute gives 10 again. Its values are `[10, 8, 10, 10]` and its emissions
   are `[8, 10]`. Chapter 15 §7 requires at least one scenario with an equal
   recompute, so a `DerivedProperty` without the §6 gate fails `DPROP-012`.
   The other scenarios have `expected_emissions` `[]`, `[20]`, `[7, 12]`,
   `[42]` and `["ac"]`.
1. `DPROP-012` subscribes to `ValueChanged` before the first mutation, collects
   the values, and compares them with `expected_emissions`. The test runs in all
   five flavors. Only the subscription call is idiomatic to each flavor.
1. `tools/check-fixture-contracts.py` adds `expected_emissions` to the exact
   scenario field set and requires it to be a list.
1. The Rust, Swift and Python fixture copies are byte-identical to the spec
   fixture. The TypeScript copy comes from `npm run sync-fixtures`.

Choices the issue left open, each made because it is uniform across the five
flavors:

- **Shape.** One flat list of emitted values per scenario, not one list per
  mutation. A flat list states the emitted values directly. A per-mutation list
  would need an empty entry for each suppressed step, which records the gate's
  result rather than the emission stream.
- **Identifier.** `DPROP-012` keeps its ID and gains a clause. A new ID would
  need markers in all five flavors for the same fixture check, and the ID
  already names the fixture test.
- **Equality policy.** Unchanged. #374 owns it.
- **Version.** `spec/VERSION` stays at 3.30.0. No `spec-v3.30.0` tag exists, so
  the spec and package versions do not move, as for ADR-0214 to ADR-0240. No
  public API changes.
- **Changelog.** No entry. The change is in tests, fixtures and spec text, and
  no library behavior changed.
- **Fixture version.** `$schema-version` stays `1.0.0`. The checker accepts only
  that value, and every fixture copy changes in the same pull request.

## 3. Consequences

- A flavor that drops its equality gate now fails `DPROP-012` in its own suite,
  independent of its `DPROP-010` test.
- Every scenario added to the fixture needs `expected_emissions`, and the
  checker enforces it. The fixture schema that #1788 publishes must include the
  field. If #1788 merges first, its schema adds `expected_emissions`.
- The library is unchanged, so the public API, the packages and the changelogs
  are unchanged.

## 4. Rejected alternatives

- **A separate emissions fixture file.** Each flavor would need a second loader,
  and one scenario would be split across two files. One file keeps one test
  ID and one data source.
- **A new `DPROP` ID for emissions.** Catalog IDs are stable keys. The check
  belongs to `DPROP-012`, which already names the fixture test.
- **Relying on `DPROP-010` alone.** That test is per flavor, so a shared fixture
  gives no cross-flavor check for the equality rule.
