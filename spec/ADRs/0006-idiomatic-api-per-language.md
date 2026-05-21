# ADR 0006 — Idiomatic API per language, conceptual parity enforced by spec

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

VMx ships in C#, Python, and future TypeScript. Two naming/structure philosophies are possible.

## Options considered

1. **Literal mirror across languages.** Python `ComponentVM.Construct(...)` mirrors C# `ComponentVM.Construct(...)` exactly. Pro: identical docs for any flavor. Con: violates Python and TS conventions; Python developers expect `snake_case` member names.
1. **Idiomatic per language; conceptual parity only.** C# `PascalCase`, Python `snake_case`, TS `camelCase`. Same concepts and semantics, native-feeling surfaces. Cross-language conformance enforced by the conformance catalog rather than by name-matching.
1. **Idiomatic primary + thin alias layer for literal mirroring.** Provide both `component_vm.construct()` (idiomatic) and `componentVM.Construct()` (alias) in non-C# flavors. Doubles surface area.

## Decision

Option 2. Each language flavor follows its language's conventions for casing, fluent vs. factory style, async semantics, and idiom-specific patterns (e.g., Python `@dataclass(frozen=True)` builders, C# `record`-based messages). Semantic parity is the spec's responsibility, enforced by the conformance test catalog.

## Consequences

- Names differ across flavors but concepts do not. The spec describes concepts (`ComponentVM`, `Construct`) without prescribing casing.
- Each flavor's `README.md` documents its native idioms.
- Conformance tests share stable `XXX-NNN` identifiers but each language implements them in its native test framework.
- A divergence beyond casing/idiom (e.g., "Python has a `select_all` that C# does not") requires an ADR documenting the why.
