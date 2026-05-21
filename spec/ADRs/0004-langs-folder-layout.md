# ADR 0004 — `langs/<lang>/` repo layout

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

VMx is a single semantic library shipped in multiple language flavors. The repo must keep flavors isolated (no cross-language imports) while sharing the spec and CI.

## Options considered

1. **Top-level language folders** (`csharp/`, `python/`, …). Short paths; signals nothing about multi-language structure.
1. **`langs/<lang>/`** umbrella. Each flavor self-contained under `langs/`; root reserved for cross-cutting concerns (`spec/`, `docs/`, `examples/`, `tools/`, `.github/`).
1. **Per-package nesting** (`packages/csharp-vmx/`, `packages/csharp-vmx-rx/`, …). Scales if one flavor ships many sub-packages; over-engineered for our 1–2 packages per flavor.

## Decision

Option 2. `langs/<lang>/` makes the multi-language intent visible at the root and isolates each flavor's build/test/release artifacts. Adding a new language is purely additive: drop `langs/<lang>/` in with its own project file, no other directories need to change.

## Consequences

- All language-specific code, configuration, and tests live under `langs/<lang>/`.
- Cross-cutting concerns (`spec/`, `docs/`, `examples/`, `tools/`, `.github/`) live at the root.
- CI workflows trigger on path filters matching `langs/<lang>/**` and `spec/**`.
- Per-language `CHANGELOG.md` and `README.md` live alongside each `langs/<lang>/` to keep flavor-local context flavor-local.
