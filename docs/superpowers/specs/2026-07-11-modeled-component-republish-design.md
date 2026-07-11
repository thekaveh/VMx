# Explicit Modeled-Component Republish Design

**Issue:** #89\
**Date:** 2026-07-11\
**Status:** Approved for implementation by the standing ordered-ticket goal

## Problem

Modeled components suppress an ordinary assignment when the candidate equals the
current model. That is the correct setter contract, but it leaves no intentional
way to announce that externally owned state reachable through the current model
reference changed in place.

DayDreams demonstrates the cost in `WorldVM.setHeightField`: the height field is
stored outside the cell model, yet renderer adapters deliberately repaint from the
cell's model notification. The consumer allocates `{ ...cellVm.model }` solely to
defeat TypeScript reference equality and obtain that notification. The audited
evidence is limited to this one site. `applyManifestDelta` creates genuinely
changed model content and remains an ordinary assignment.

The original ticket also proposed a `DerivedProperty` comparator. That is a
separate concept with no bearing on explicit modeled-component publication and is
out of scope.

## Chosen API

Add one dedicated operation to every modeled leaf component:

| Flavor     | API                 |
| ---------- | ------------------- |
| C#         | `RepublishModel()`  |
| Python     | `republish_model()` |
| TypeScript | `republishModel()`  |
| Swift      | `republishModel()`  |
| Rust       | `republish_model()` |

The operation is present on writable modeled components, read-only modeled
components, and modeled forwarding decorators. It is not a general-purpose
property notification escape hatch and does not accept a property name.

`FormVM` is not included. Form publication is a standalone edit transaction with
validation, dirty state, command invalidation, deny, and approval-reset boundaries.
Issue #89's evidence and refined acceptance criteria concern the `ComponentVM`
family, including read-only and forwarding forms. Adding a form-specific
republish transaction without consumer evidence would broaden the ticket.

## Semantics

For a non-disposed modeled component, one call:

1. retains the exact current model reference/value;
1. retains the cached modeled hint without invoking the modeled hinter;
1. does not evaluate model equality;
1. does not invoke `OnModelChanged` / `onModelChanged`;
1. invokes the established dual-channel notification helper exactly once with the
   flavor-idiomatic model property name; and
1. returns no value.

For an ordinary top-level call, the existing helper publishes exactly one hub
`PropertyChangedMessage` before exactly one local property notification. Both
observers read the unchanged current model and modeled hint. A null/default hub
keeps its null-object behavior while the local channel still emits once.

The helper's existing lifecycle admission is authoritative. A call that begins
after disposal is a complete no-op. A call admitted before re-entrant disposal
completes its pair under the chapter 05 notification-helper contract.

Re-entrant calls use the lossless hub queue. If a hub subscriber invokes republish
once during an outer publication, each call contributes exactly one hub/local
pair without recursive hub delivery or loss. As already documented in chapter 05
§2.3, the nested call can emit locally after enqueueing and before its queued hub
message is drained; the outer local emission occurs after the outer hub send and
its re-entrant queue finish. This feature does not invent a second ordering rule.

Read-only components may republish because read-only means VMx does not replace
the model reference; it does not make a referenced object deeply immutable. The
operation still does not provide a setter or recompute the construction-time
modeled hint. Forwarding decorators delegate to the wrapped component so sender
identity, hub, local stream, disposal, and overrides remain those of the target.

## Alternatives rejected

### Force option on assignment

A `force` option does not map to language property setters in C# or Swift without
adding a second setter-shaped method. It also makes callers reason about whether a
"forced set" installs the candidate, recomputes the hint, or fires callbacks. The
desired operation is publication without assignment, so its API should say that.

### Generic `touch(property)`

A string-based touch API would let callers claim arbitrary property changes,
including names the VM does not own. It would expose the subclass-author helper as
a public convention and weaken compile-time intent for the sole verified model use
case.

### Continue allocating equal copies

This keeps a silent, equality-dependent consumer idiom, needlessly allocates, and
can stop working when value equality or a comparator is introduced. It encodes
notification intent as fake replacement.

## Specification and versioning

Chapter 05 will add the operation to both modeled variants and define its exact
identity, hint, callback, disposal, null-hub, forwarding, and re-entrant behavior.
ADR-0093 records the public API decision. `CVM-010` is the single new normative
catalog case, implemented as real behavior coverage in all five full-parity
flavors.

This is an additive public feature. The spec and stable packages advance from
3.12.0 to 3.13.0; Rust advances from 0.12.0 to 0.13.0 and declares minimum spec
3.13.0. The library catalog advances from 341 to 342 IDs and the total including
five `THEME-00x` scenarios advances from 346 to 347.

## Conformance strategy

Each flavor's `CVM-010` coverage will prove:

- a writable component retains model identity/value and modeled hint;
- exactly one idiomatic hub/local model pair is emitted in top-level order;
- the modeled hinter and model-changed callback are not invoked;
- ordinary equal assignment remains silent and unequal assignment remains
  unchanged;
- a read-only component exposes republish without exposing model replacement;
- a forwarding component delegates publication to the wrapped sender and stream;
- null/default hub use remains safe and the local channel still emits;
- a disposed component emits neither channel; and
- one guarded re-entrant call yields two complete pairs through the existing queue.

Focused tests are followed by every flavor's full test/lint/type/build gates,
repository conformance coverage, version consistency, documentation generation,
link/drift checks, and pre-commit. Swift XCTest is authoritative on macOS CI when
the local CommandLineTools environment lacks the `XCTest` module.

## Documentation and consumer proof

The canonical component-family documentation will explain legitimate republish
use, show the five idiomatic spellings, state exact side effects, and warn that the
API must not conceal ordinary model mutation that should use assignment. Generated
in-repo documentation, the MkDocs `.io` site, and the native GitHub wiki will be
regenerated from that canonical source. No architecture diagram changes because
no component boundary or dependency changes.

A disposable, no-push DayDreams pilot will point its VMx vendor dependency at the
completed branch, replace only `cellVm.model = { ...cellVm.model }` with
`cellVm.republishModel()`, update the now-obsolete comment, and run the relevant
renderer trace plus workspace typecheck/test/build gates. The user's existing
DayDreams checkout and unrelated local files remain untouched.
