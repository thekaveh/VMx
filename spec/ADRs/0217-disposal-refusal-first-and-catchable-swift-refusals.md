# ADR 0217 — The disposal refusal comes before the non-member refusal, and Swift reports three more refusals catchably

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 06 §3, §4.3 rule 3 and §9)
- **Extends:** [ADR-0173](0173-selection-commits-without-a-membership-transaction.md)
  §2 and [ADR-0107](0107-atomic-container-ownership-transfer.md). Related:
  [ADR-0009](0009-cross-flavor-divergence-catalogue.md),
  [ADR-0053](0053-swift-converge-illegal-transition-and-non-child-current-to-throw.md),
  #1423, #1349.

## 1. Context

Two Swift gaps remained after ADR-0188 and ADR-0189.

- **Refusal order (#1423).** Chapter 06 §4.3 rule 2 refuses a non-member, and
  rule 3 refuses a non-null selection while disposal of the composite is
  requested or deferred. The chapter did not say which refusal applies when
  both conditions are true. C#, Python, TypeScript and Rust check disposal
  first. Swift `_commitSelectionLocked` checked membership first, so
  `setCurrent(_:)` on a non-member threw `CompositeMembershipError` with the
  `.nonMember` reason during a pending disposal. After `Disposed`, Swift also
  threw `.nonMember` for a non-member. C# throws `ObjectDisposedException`,
  Python raises the disposal `RuntimeError`, and TypeScript throws its
  disposal error.
- **Swift traps (#1349).** Three Swift operations stopped the process on
  invalid input, where C#, Python and TypeScript raise a catchable error:
  `FilteredCompositeVM.setCurrent(_:)` on an item that is not visible,
  `removeAt(_:)` on `CompositeVM` and `GroupVM` with an index outside
  `[0, count)`, and `DerivedProperty.fromSources` with no sources. Each is a
  non-throwing public method. Adding `throws` to one breaks every Swift caller
  and conformer. ADR-0107 keeps the `Void` mutators of `VMCollection` and adds
  `Result` companions such as `insertResult` and `replaceResult`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: every flavor follows the
same rule, and the simplest rule wins.

### 2.1. Rule 3 applies before rule 2

For a non-null selection, the disposal refusal (rule 3) applies before the
non-member refusal (rule 2). Rule 4, the caller's own uncommitted
transaction, still applies first. Chapter 06 §3 and §4.3 rule 3 state the
order.

- **Swift.** `_commitSelectionLocked` returns `.refused(.disposing)` for a
  non-member while disposal is requested or deferred, and for a `Disposed`
  child in the same window. `canSetCurrent(_:)` returns `false` for both.
  With no pending disposal, a non-member keeps `.nonMember` (`COMP-009`).
- **After `Disposed` in Swift.** A non-member selection throws the
  `.disposing` refusal, as in the other four flavors. A member selection
  after `Disposed` stays an inert no-op (chapter 01 §4,
  `testSelectionAfterDisposedInsideTheCompositesOwnHookIsInert`).
- **C#, Python, TypeScript and Rust** already follow this order and do not
  change.

### 2.2. Catchable Swift forms

Each Swift operation gains a `Result` companion in the ADR-0107 pattern. The
existing method keeps its signature, so no caller breaks.

| Operation                            | Catchable form                                                                                     | Failure                                               | Existing method                          |
| ------------------------------------ | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------- |
| `FilteredCompositeVM.setCurrent(_:)` | `setCurrentResult(_:) -> Result<Void, CompositeMembershipError>`                                   | an error with the internal reason `.notVisible`       | traps, as the `current` setter does      |
| `CompositeVM.removeAt(_:)`           | `removeAtResult(_:) -> Result<Void, ContainerOwnershipError>`                                      | `.attachmentFailed(VMCollectionIndexError)`           | discards the failure and changes nothing |
| `GroupVM.removeAt(_:)`               | `removeAtResult(_:)`                                                                               | the same                                              | the same                                 |
| `ForwardingCompositeVM.removeAt(_:)` | `removeAtResult(_:)`, forwarded to the wrapped composite                                           | the wrapped composite's failure                       | the same                                 |
| `DerivedProperty.fromSources`        | `fromSourcesResult(_:_:canSet:setAction:) -> Result<DerivedProperty, DerivedPropertySourcesError>` | `.noSources` of the new `DerivedPropertySourcesError` | traps                                    |

- **Removal discards, as `insert` and `replace` do.** The `Void` `insert` and
  `replace(at:with:)` of `CompositeVM` and `GroupVM` already discard their
  `Result` failure, and `removeAt(_:)` already returned silently when the
  membership transaction was refused. An out-of-range index now does the
  same, so `removeAt(_:)` no longer traps. The index failure reuses
  `.attachmentFailed(VMCollectionIndexError)`, the shape that `insertResult`
  and `replaceResult` return, so `ContainerOwnershipError` gains no case.
- **Selection and the factory keep their trap.** The `current` setter of
  `CompositeVM` traps on a refusal (ADR-0053 §2.3), and
  `FilteredCompositeVM` matches it. A silent `setCurrent(_:)` would hide a
  programmer error that every other flavor raises. `fromSources` returns a
  property and has no result to discard.
- **Rust.** Rust `from_sources` keeps its documented panic on an empty source
  list. The Rust backlog in
  `docs/maintenance/2026-07-16-rust-capability-parity.md` owns any Rust
  change.

The ADR-0009 section "Swift traps that remain" lists the Swift traps that
remain and the catchable form of each.

## 3. Consequences

- A Swift consumer that matched `.nonMember` for a non-member selection
  during a pending disposal, or after `Disposed`, now receives `.disposing`.
  The reason is internal, so only `description` text changes for consumers
  outside the module.
- `swift test` covers the order in
  `CompositeSelectionWithoutTransactionTests.testDeferredDisposalReportsTheDisposalRefusalForANonMember`
  and the companions in `CatchableRefusalTests`.
- `fromSourcesResult` fails with the new `DerivedPropertySourcesError` type,
  not with a new case of `DerivedPropertyError`. A consumer `switch` over
  `DerivedPropertyError` keeps compiling, so the change is source compatible
  and ships in a minor version.
- No conformance ID changes. `COMP-009` keeps its non-member refusal when no
  disposal is pending.
