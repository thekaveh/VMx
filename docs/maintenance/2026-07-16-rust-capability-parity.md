# 12. Rust Parity Status

Filed: **2026-07-16**. Closed: **2026-07-26**.

This record began as the evidence ledger for capability-surface and observable-
behavior differences between Rust and the four other flavors. The Rust 0.27.0
maintenance line has now resolved every actionable item originally recorded in
§12.3 and §12.4. Rust remains a source-tree flavor that has not been published
to crates.io, so the coordinated public-API corrections described here are
pre-publication changes.

The closure was revalidated against the current Rust implementation, its
conformance and regression tests, the canonical spec, and the four-flavor
consensus on **2026-07-26**. All five flavors cover all 403 library IDs. The
focused Rust tests cited below now assert the canonical member shape and edge
behavior rather than the earlier reduced Rust surface.

Three behavioral differences had already been corrected before this focused
follow-up: `FormVm` no longer publishes an extra
`PropertyChanged("is_valid")` onto the main hub; `HierarchicalVm` no longer
emits spurious `PropertyChanged("parent")` messages on first `children()`
materialization; and `NotificationHub::resolve` / `dispose` publish the pending
snapshot before completing the corresponding waiter. The maintenance branch
also completed baseline lifecycle capabilities and
full forwarding-component delegation. It also completed inline-dispatch
deadlock prevention, idempotent capability predicates, and atomic container
admission.

## 12.1. Scope And Authority

`spec/14-capabilities.md` and the per-cluster ADRs (ADR-0010, ADR-0022,
ADR-0023, ADR-0057) are the authoritative capability contract. The related
behavioral authority comes from the source chapters cited by each item below,
the accepted ADRs, and the four-flavor consensus where the spec deliberately
leaves an edge unspecified.

No spec change was needed for this closure. Rust converged on the existing
contract using idiomatic snake_case methods, `VmxResult<T>` for recoverable
failures, and VMx-owned reactive facades. No third-party reactive runtime was
introduced.

## 12.2. Canonical-Behavior Decision

The spec remains canonical. The completed work aligns Rust with the public
surface and behavior already implemented by the other four flavors. The
changes stay on the already-open Rust 0.27.0 / spec 3.23.0 source line; this
record does not introduce a package or spec version change.

### 12.2.1. Message Sender Identity Is An Accepted Idiom

Rust's `sender_id: usize` plus `sender_name: String` message fields are the one
intentional flavor-specific shape retained by this review. ADR-0120 records
them as the ownership-safe Rust expression of the canonical sender-identity
contract. The other four flavors retain runtime sender objects, while Rust
messages remain owned values that do not retain or borrow a VM. Identity
filtering behavior remains required across all five flavors.

## 12.3. Capability And Reusable-State Closure

### 12.3.1. Selection And Expansion Opt-In (CAP-020)

**Resolved.** Rust no longer blanket-implements the six opt-in selection and
expansion traits on `ComponentVm`. The baseline `Constructable`,
`Destructable`, and `Reconstructable` traits apply to every `VmNode`, while
selection and expansion remain explicit opt-ins.

Evidence: `capabilities.rs` contains the lifecycle blanket implementations and
the compile-fail opt-in guards; CAP-020 asserts the positive lifecycle bounds
and negative `ComponentVm: Selectable` surface.

### 12.3.2. Filterable Predicate Shape (CAP-021)

**Resolved.** `Filterable<T>` now stores an optional shared predicate and
exposes `filter`, `set_filter`, and `can_filter`. Clearing with `None` removes
the filter.

Evidence: CAP-021 exercises predicate replacement, evaluation, and clearing,
and retains the compile-negative proof that core VMs do not opt in
implicitly.

### 12.3.3. Pageable Complete Surface (CAP-022)

**Resolved.** `Pageable` now exposes page size, current page index, page count,
paging-enabled state, and bounded first/previous/next/last navigation.
`PagedComposition` implements the trait and clamps its current page after
source or page-size changes.

Evidence: CAP-022 drives the trait through `PagedComposition` and covers
clamping, pass-through mode, and navigation edge no-ops.

### 12.3.4. Expandable State Read (CAP-004)

**Resolved.** `Expandable` includes `is_expanded`, and expanded tree walking
uses the expansion capability instead of a separate reduced tree hook.

Evidence: CAP-004 asserts the state read before and after `expand`; HIER-012 and
the focused expandable-support tests verify lazy expanded-walk boundaries.

### 12.3.5. Searchable Term Mutation (CAP-008)

**Resolved.** `Searchable` exposes `set_search_term`, and `SearchableState`
implements the complete capability.

Evidence: CAP-008 performs the mutation through the trait and verifies the
filtered projection through the concrete reusable helper.

### 12.3.6. ExpandableState Construction And Disposal

**Resolved.** `ExpandableState` provides collapsed, explicitly initialized,
and initially-expanded construction. It implements `Expandable`,
`Collapsible`, and `ExpansionTogglable`; `dispose` completes the owned hub and
makes later mutation inert.

Evidence: the expandable-support suite covers construction variants,
capability dispatch, completion, idempotent disposal, and post-dispose no-op
behavior.

### 12.3.7. SearchableState Post-Dispose Read

**Resolved.** A disposed `SearchableState` reads as an empty term, keeps later
assignments inert, releases its source subscription, and does not own the
source.

Evidence: `disposed_searchable_state_reads_an_empty_term` and
`dispose_cancels_source_observation_without_owning_source` cover the corrected
contract.

## 12.4. Behavioral Closure

### 12.4.1. Explicit Reparent Of A Detached Child

**Resolved.** `reparent_child` passes an explicit-reparent intent through the
attachment path. A detached child therefore reports `Reparented` with index
`-1`; ordinary add of a detached child remains `Added` with its inserted index.

Evidence: `explicit_reparent_of_detached_child_reports_reparented` verifies the
four-flavor consensus without changing ADR-0105's ordinary-add rule.

### 12.4.2. Remove Of A Non-Member

**Resolved.** Hierarchy, group, and composite removal now return a successful
no-op when the supplied child is not a member. No collection, selection,
parent, or message state changes.

Evidence: focused hierarchy, group, and composite tests exercise the absent
member path, including current-selection stability.

### 12.4.3. Aggregate Slot Notification Ordering

**Resolved.** `AggregateVm1` through `AggregateVm6` publish every populated slot
notification before constructing any child. The emitted notification set is
therefore complete even when the first child construction fails.

Evidence: the aggregate conformance suite records the cross-slot sequence and
the first-child failure path for all six arities.

### 12.4.4. FormVm Direct Approval

**Resolved.** Direct `approve()` gates only on disposal and validity. The
strict-mode dirty requirement remains solely on approve-command eligibility,
so a strict, valid, clean form may still be persisted explicitly.

Evidence: the form suite separates strict-clean direct approval from command
`can_execute` behavior and preserves invalid/disposed no-op coverage.

### 12.4.5. Base ComponentVm Type Surface

**Resolved.** The base component surface now exposes `view_model_type`, and
builders/options preserve the selected type through modeled, readonly, and
forwarding variants. The earlier selection-gate, built-in-command, and full
forwarding-component delegation work remains intact.

Evidence: CVM and builder tests compare default, overridden, readonly, and
nested forwarding type values.

### 12.4.6. DerivedProperty Source Ownership And Recompute

**Resolved.** `DerivedProperty` now provides one- through five-source
constructors over typed replaying `ValueStream` sources, subscribes once,
recomputes automatically when any source changes, suppresses equal outputs,
and releases owned subscriptions on disposal.

Evidence: DPROP-002 through DPROP-005 mutate real sources; DPROP-012 executes
the shared scenarios; focused tests cover distinct emission, source
subscription counts, value-stream completion, and post-dispose isolation.

### 12.4.7. Collections And Commands

**Resolved.** The complete residual set now matches the canonical behavior:

- composite selection clears before observable removal publication;
- `ObservableList::remove_at` returns `VmxError::InvalidArgument` for an
  out-of-range index;
- `FilteredCompositeVm` defaults to `SnapToFirst` and implements
  `PreserveIfVisible`;
- `ConfirmationDecoratorCommand::dispose` completes `errors`, and confirmed or
  post-dispose execution cannot emit afterward; and
- `RelayCommand` and `RelayCommandOf` emit the optional final
  `can_execute_changed` notification before completing their hubs.

Evidence: the collection, filtered-composite, confirmation-decorator, relay-
command, and composite suites contain focused assertions for each edge.

### 12.4.8. Hot-Stream Completion And Notification Replay

**Resolved.** Rust now has a typed, replaying, completion-aware VMx-owned
`ValueStream<T>`. `MessageHub::subscribe_with_completion` reports terminal
completion, including immediately for late and null subscriptions.
`NotificationHub::pending_stream` replays its current snapshot, publishes each
committed update in order, and completes after the terminal empty snapshot.
`NullNotificationHub` replays empty and completes immediately.

Evidence: the value-stream suite covers initial/late replay, completion,
reentrancy, serialization, and panic isolation. HUB and null-service tests
cover normal, late, and immediate completion. NOTIF tests cover replay,
publish-before-waiter ordering, concurrent terminal delivery, and null-hub
behavior.

### 12.4.9. Executor-Neutral Pending Async Operations

**Resolved.** `AsyncValue` provides executor-neutral `map` and `and_then`
continuations. `make_confirm` and `ConfirmationDecoratorCommand` no longer
retain one native worker thread per unresolved decision. Confirmation execution
returns the `Future`-compatible `ConfirmationExecution` handle while preserving
blocking `join()` and non-blocking `is_finished()` conveniences.

First-wins resolution, resolver-thread continuation execution, panic isolation,
post-dispose no-op behavior, and synchronous completion are covered. Resource-
bound assertions use retained-continuation counts rather than timing sleeps.

The pre-publication API correction is intentional: explicitly typed
`JoinHandle<()>` callers must migrate to `ConfirmationExecution`; inferred
`.join()` callers retain the same call shape. No published crates.io artifact
used the earlier return type.

## 12.5. Related Spec-Wording Note (Not Rust-Specific)

`spec/02-lifecycle.md` §7 lists the parent's terminal disposal work as
"…command teardown, and stream completion," but all five flavors complete the
streams before tearing down the commands. The sentence remains an editorial
ordering description: no conformance ID pins this intra-parent order.

This note is intentionally deferred to a future spec-editing change. Correcting
the non-exempt chapter requires its own ADR and associated documentation
updates. It is not a Rust behavior difference and does not reopen this ledger.

## 12.6. Disposition

**Closed on the Rust 0.27.0 / spec 3.23.0 source line.** Every actionable
capability, reusable-state, structural, command, reactive, and async item
recorded in §12.3 and §12.4 is resolved and backed by focused Rust tests. Rust
is both catalog-complete and aligned with the canonical public concepts and
observable behavior covered by this review.

The ADR-0120 sender representation in §12.2.1 remains the sole intentional
flavor-specific shape in this ledger. The §12.5 editorial note applies to all
five flavors and is not a parity backlog. Future differences still require
spec/ADR review; this completed record is evidence of the 0.27.0 convergence,
not permission to add undocumented divergence.
