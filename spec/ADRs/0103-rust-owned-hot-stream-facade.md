# ADR 0103 — Use the VMx-owned Rust hot-stream facade directly

**Status:** Accepted (2026-07-13)
**Spec version:** 3.20.0 (implementation-record correction; no API or behavior change)
**Related:** ADR-0002, ADR-0036, ADR-0080, ADR-0081, ADR-0101

## 1. Context

ADR-0080 selected a VMx-owned Rust facade and named `rxrust` as its initial
backing candidate. Later current-facing documentation described that candidate
as the implemented backend. Repository inspection shows that the Rust flavor
instead implements its hot streams directly behind VMx-owned types; no source
or test imports `rxrust`. Keeping the unused dependency makes package metadata,
minimum-toolchain analysis, security review, and architecture documentation
less accurate without contributing behavior.

The observable contract is the VMx facade: subscription, disposal, isolated
delivery, ordering, and hot-stream behavior. The private implementation is not
part of the cross-flavor API and conformance does not require a particular
third-party Rust crate.

## 2. Decision

### 2.1 Keep the VMx-owned facade as the reactive primitive

Rust continues to expose its existing VMx-owned hot-stream types. Their tested
semantics, not a private backend name, define parity with the reactive
boundaries used by the other four flavors.

### 2.2 Remove the unused rxrust dependency

The Rust manifest no longer declares `rxrust`. Current-facing architecture and
installation documentation describe a VMx-owned hot-stream facade without
claiming a third-party backend.

This decision refines ADR-0080's candidate language and supersedes only the
Rust-backend claims in ADR-0101. It does not replace ADR-0101's TC39 Signals
gates or change any public VMx behavior.

### 2.3 Require evidence before adopting another backend

A future backend proposal needs a new ADR and must demonstrate measurable
correctness, maintenance, performance, or interoperability benefit. It must
also preserve the public facade, all Rust conformance tests, disposal and
failure isolation, ordering, package MSRV, and consumer compatibility.

## 3. Consequences

- Rust package metadata reflects the code that is actually compiled.
- Removing an unused release-candidate dependency reduces the published
  dependency graph and makes MSRV and vulnerability checks more meaningful.
- No conformance ID, fixture, public API, spec version, or flavor package
  version changes because observable behavior is unchanged.
- Historical feasibility and planning documents remain historical evidence;
  current-facing documentation points to this decision.

## 4. Rejected alternatives

### 4.1 Reimplement the facade over rxrust solely to match stale prose

Rejected. It adds migration and compatibility risk without a demonstrated
behavioral benefit.

### 4.2 Keep the unused dependency as an architectural placeholder

Rejected. A manifest is an executable package contract, not a roadmap. Future
backend work can add a dependency when an accepted design actually uses it.
