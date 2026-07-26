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

Evidence: `src/capabilities.rs` contains the lifecycle blanket implementations;
the `ComponentVm: Selectable` compile-fail guard is attached to `ComponentVm`
in `src/components.rs`. CAP-020 asserts the positive lifecycle bounds.

### 12.3.2. Filterable Predicate Shape (CAP-021)

**Resolved.** `Filterable<T>` now exposes the `filter`, `set_filter`, and
`can_filter` accessors for an optional shared predicate. Implementors own the
predicate storage; clearing with `None` removes the filter.

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
source. Explicit search after disposal is likewise inert: it returns an empty
projection without invoking the item provider or predicate.

Evidence: `disposed_searchable_state_reads_an_empty_term` and
`dispose_cancels_source_observation_without_owning_source` cover the ownership
contract. `search_after_disposal_is_inert_without_calling_user_code` uses side
effects at both user-code boundaries to prove neither is invoked.

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

Evidence: `removing_a_non_child_is_a_noop` covers hierarchy state and messages.
`membership_uses_node_identity_when_partial_eq_is_value_based` selects a real
composite member before removing an equal-valued foreign node, then proves the
member, `current`, and current flag remain stable; it also covers group
membership.

### 12.4.3. Aggregate Slot Notification Ordering

**Resolved.** `AggregateVm1` through `AggregateVm6` publish every populated slot
notification before constructing any child. The emitted notification set is
therefore complete even when the first child construction fails.

Evidence:
`all_slot_notifications_precede_first_child_failure_for_arities_one_through_six`
records every populated-slot notification followed by only the failing first
construction attempt for each arity. The companion success-path test records
all slot notifications before any construction.

### 12.4.4. FormVm Direct Approval

**Resolved.** Direct `approve()` gates only on disposal and validity. The
strict-mode dirty requirement remains solely on approve-command eligibility,
so a strict, valid, clean form may still be persisted explicitly.

Evidence: the form suite separates strict-clean direct approval from command
`can_execute` behavior and preserves invalid/disposed no-op coverage.

### 12.4.5. Base ComponentVm Type Surface

**Resolved.** Every canonical component VM family exposes
`view_model_type`: component and readonly variants, groups, composites and
their modeled/filtered/forwarding wrappers, aggregate arities one through six,
hierarchies, forms, and async-resource VMs. Builders/options preserve selected
component types, and forwarding wrappers delegate the wrapped family value.
The earlier selection-gate, built-in-command, and full forwarding-component
delegation work remains intact.

Evidence: CVM and builder tests compare default, overridden, and readonly type
values. `component_variants_expose_their_view_model_type` additionally proves
that the configured value delegates unchanged through two and three nested
`ForwardingComponentVm` layers.
`every_component_vm_family_exposes_its_canonical_view_model_type` enumerates
the complete family surface with literal expected discriminators.

### 12.4.6. DerivedProperty Source Ownership And Recompute

**Resolved.** `DerivedProperty` now provides one- through five-source
constructors over typed replaying `ValueStream` sources, owns exactly one
subscription per supplied source, recomputes automatically when any source
changes, suppresses equal outputs, and releases every owned subscription on
disposal. Concurrent source emissions carry monotonically admitted snapshot
revisions through one serialized result stream; a transform computed from an
older snapshot cannot overwrite or publish after the newer latest-at-emission
result.

Evidence: DPROP-002 through DPROP-005 mutate real sources; DPROP-012 executes
the shared scenarios; the crate-private
`owns_exactly_one_subscription_per_source_until_disposal` test directly counts
the owned registrations before and after disposal without adding a public
diagnostic API. Focused conformance tests cover distinct emission, value-stream
completion, post-dispose isolation, and a deterministically gated older
multi-source transform that resumes only after the newer result commits. The
unit-level `revisioned_commit_serializes_value_and_publication` regression gates
the old commit-before-notification window and verifies value and both
publication order surfaces remain `1, 2`.

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
`confirmation_error_value_precedes_disposal_completion` and
`relay_disposal_emits_one_final_can_execute_notification` observe terminal
callbacks directly and assert value-before-completion ordering.

### 12.4.8. Hot-Stream Completion And Notification Replay

**Resolved.** Rust now has a typed, replaying, completion-aware VMx-owned
`ValueStream<T>`. `MessageHub::subscribe_with_completion` reports terminal
completion, including immediately for late and null subscriptions.
`NotificationHub::pending_stream` replays its current snapshot, publishes each
committed update in order, and completes after the terminal empty snapshot.
`NullNotificationHub` replays empty and completes immediately.

Evidence: the value-stream suite covers initial/late replay, completion,
reentrancy, serialization, and panic isolation. It also drives two streams from
two drainer threads through opposing callbacks, proving cross-stream enqueue
does not create a wait cycle while the ordinary foreign-thread send/dispose
tests retain synchronous completion. HUB and null-service tests cover normal,
late, and immediate completion. NOTIF tests cover replay, publish-before-waiter
ordering, concurrent terminal delivery, and null-hub behavior.

### 12.4.9. Executor-Neutral Pending Async Operations

**Resolved.** `AsyncValue` provides executor-neutral `map` and `and_then`
continuations. `make_confirm` and `ConfirmationDecoratorCommand` no longer
retain one native worker thread per unresolved decision. Confirmation execution
returns the `Future`-compatible `ConfirmationExecution` handle while preserving
blocking `join()` and non-blocking `is_finished()` conveniences.

First-wins resolution, resolver-thread continuation execution, panic isolation,
post-dispose no-op behavior, synchronous completion, and preservation of the
original `Box<dyn Any + Send>` panic payload through `join()` are covered.
Resource-bound assertions use retained-continuation counts rather than timing
sleeps.

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
