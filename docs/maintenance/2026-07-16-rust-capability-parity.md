# 12. Rust Parity Status

Filed: **2026-07-16**. Original scope closed: **2026-07-26**. Items found
after closure: §12.7 to §12.14, plus the "Still open" notes in §12.4.7.
§12.8, §12.10, §12.11 and §12.12 are now closed (ADR-0205, ADR-0197, ADR-0208
and ADR-0207, in that order). §12.9, §12.13 and the §12.4.7 notes are resolved
(ADR-0210, ADR-0226, and ADR-0207 with ADR-0210). §12.7 is a recorded
difference. §12.14 is closed (ADR-0228).

This record began as the evidence ledger for capability-surface and observable-
behavior differences between Rust and the four other flavors. The Rust 0.27.0
maintenance line has now resolved every actionable item originally recorded in
§12.3 and §12.4. Rust remains a source-tree flavor that has not been published
to crates.io, so the coordinated public-API corrections described here are
pre-publication changes.

The closure was revalidated against the current Rust implementation, its
conformance and regression tests, the canonical spec, and the four-flavor
consensus on **2026-07-26**. All five flavors cover every library ID. The
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

Rust's `sender_id: usize` plus `sender_name: String` message fields are an
intentional flavor-specific shape retained by this review. ADR-0120 records
them as the ownership-safe Rust expression of the canonical sender-identity
contract. The other four flavors retain runtime sender objects, while Rust
messages remain owned values that do not retain or borrow a VM. Identity
filtering behavior remains required across all five flavors.

### 12.2.2. HierarchicalVm Node Data Is An Accepted Idiom

Rust has no subclassing, so `HierarchicalVm<M, N = ()>` takes a node-data type
`N` in place of the `TVM` subclass of the other flavors (ADR-0202, #1263).
`parent()`, `children()` and `path()` return `HierarchicalVm<M, N>`, and
`node_data()` returns the node's own `N`. A consumer keeps per-node state in
`N` and adds node methods through an extension trait. `TreeSelection<M, N>`
follows the same node type. The Rust `HIER-001` test builds a three-level tree
of a consumer node-data type and reads it from each accessor.

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
`HierarchicalVm::compose_expansion` composes an `ExpandableState` with a public
hierarchy node, and `TreeNode` lists type-erased `TreeNodeRef` children, so
`walk` and `walk_expanded` descend into composites, groups and aggregates
(ADR-0207, #1262).

Evidence: CAP-004 asserts the state read before and after `expand`. HIER-012
and EXP-005 compose `ExpandableState` with `HierarchicalVm` and verify the
expanded-walk boundaries. UTIL-001 to UTIL-003 walk the catalog `CompositeVm`
tree, a `GroupVm` and an `AggregateVm3`, and
`walk_expanded_descends_containers_and_stops_at_a_collapsed_node` mixes all
four container kinds.

### 12.3.5. Searchable Term Mutation (CAP-008)

**Resolved.** `Searchable` exposes `set_search_term`, and `SearchableState`
implements the complete capability.

Evidence: CAP-008 performs the mutation through the trait and verifies the
filtered projection through the concrete reusable helper.

### 12.3.6. ExpandableState Construction And Disposal

**Resolved.** `ExpandableState` provides collapsed, explicitly initialized,
and initially-expanded construction. It implements `Expandable`,
`Collapsible`, and `ExpansionTogglable`. Its typed `expansion_changes()`
stream sends the new value once per effective change and does not replay the
current value (spec/05 §8, ADR-0206, #1254). `dispose` completes the owned hub
and the typed stream and makes later mutation inert.

Evidence: the expandable-support suite covers construction variants,
capability dispatch, completion, idempotent disposal, and post-dispose no-op
behavior. EXP-002, EXP-003, `expansion_changes_does_not_replay_the_current_value`
and the dispose test in `expandable.rs` cover the typed stream.

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

Resolved (ADR-0207, #1259): `FilteredCompositeVm` now has a `changed()`
stream.

Resolved (ADR-0210, #1258): `ModeledCrudCommands::with_options` takes
optional async `confirm_update` and `confirm_delete` gates and an optional
`current_changed` trigger. A supplied gate wraps that command in a
`ConfirmationDecoratorCommand`, and the trigger also refreshes a gated
command. The synchronous `with_confirm_delete` is removed, and the Update and
Delete accessors return `Arc<dyn Command>`. `update_confirmation()` and
`delete_confirmation()` return a gated command with its concrete type, and
`dispose()` disposes every command the helper built. Evidence: the `COMP-024`
conformance test and the `modeled_crud` unit tests.

Selection follows the shared rules of spec/06 §4.3 (ADR-0173). `set_current`,
`select_component` and `deselect_component` open no membership transaction. A
selection from the `CollectionChanged` or current-change callbacks, or from
another thread, commits instead of returning `OwnershipTransactionInProgress`,
and the two `COMP-026` tests for these cases run again. A selection refused
inside the caller's own uncommitted add still returns
`OwnershipTransactionInProgress`. The construct walk's `Current(selector)`
assignment skips an unadmitted child and a disposing composite. A disposal from
a selection's callbacks, including the destruct clear's, is deferred through
the publication lease. A transfer commit clears `current` only while the moved
child is still current (spec/06 §3.2, ADR-0165).

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

ADR-0129 corrects the lifecycle wording to match the established five-flavor
order. The correction adds no behavior or conformance ID. It is not a Rust
behavior difference and does not reopen this ledger.

## 12.6. Disposition

**Closed on the Rust 0.27.0 / spec 3.23.0 source line.** Every actionable
capability, reusable-state, structural, command, reactive, and async item
recorded in §12.3 and §12.4 is resolved and backed by focused Rust tests. Rust
is both catalog-complete and aligned with the canonical public concepts and
observable behavior covered by this review.

The ADR-0120 sender representation in §12.2.1 and the ADR-0202 node-data
parameter in §12.2.2 are the intentional flavor-specific shapes in this
ledger. The §12.5 editorial note applies to all five flavors and is not a
parity backlog. §12.7 to §12.14 record the items and differences found
after closure; §12.8 to §12.13 are now closed or resolved, §12.7 is a
recorded difference, and §12.14 is closed (ADR-0228). Future differences still require
spec/ADR review. This record is evidence of the 0.27.0 convergence for the
original scope. It is not permission to add undocumented divergence.

## 12.7. Recorded Difference: Background Child Settle

Containers (`CompositeVm`, `GroupVm`, the modeled composite, and the fixed
aggregates) stay transient until background children settle (spec/02 §6,
LIFE-014). `HierarchicalVm` has no background option, so it never waits. The
fixed aggregates join a slot child that is already Constructing, as the
composite and group walks do (#1273). A node that does not forward
`VmNode::when_lifecycle_settled` is watched on the container's own hub when
the container started it and the hub delivered or queued its transient status. In every
other case, the container accepts the node while it is in flight, so the
container never waits without limit (spec/11 §4, ADR-0205, #1274).

A background child failure that rolls a container back is reported on the
container's `background_errors()` stream. This is a documented Rust container
surface (spec/11 §2, ADR-0149); the other flavors route the same failure
through their background-hook error path.

## 12.8. Closed: Forwarding Composite as a Child

`ForwardingCompositeVm` implements `VmNode`, `PartialEq`, and `Eq` by
forwarding to the wrapped composite, so a composite, group, or aggregate
accepts it as a child with one ownership identity (spec/09 §2, ADR-0205). It
forwards the rest of the `CompositeVm` surface: selection, expansion, the
commands, `on_current_changed`, `background_errors`, and the configuration
setters (#1271). It forwards the lifecycle hooks (ADR-0203).

## 12.9. Resolved: FormVm Approval Completion

**Resolved (ADR-0210, #1270).** `FormVm::subscribe_approved_with_completion`
takes an approval callback and a completion callback. Disposal calls the
completion once, after `errors_changed` and `approve_errors` complete, as the
other flavors complete `OnApproved` (spec/20 §10). A subscription on a
disposed form completes at once, and a detached one is not completed.
`subscribe_approved` keeps its signature. Evidence:
`tests/conformance/form_approval_completion.rs`.

## 12.10. Recorded Difference: Notification Hub Disposal Snapshot

**Resolved.** ADR-0197 removes the final snapshot in every flavor. Rust
dispose sends no value on `pending_stream()` and no `pending` message on
`pending_changed()` before completion, as C#, Python, TypeScript and Swift
already did. A `pending_stream()` subscription made after dispose completes at
once with no replay (NOTIF-017, NOTIF-020).
Waiters resolve to `Pending` in every flavor.

## 12.11. Closed: PagedComposition Notifications

**Closed (ADR-0208, #1269).** Rust `PagedComposition` raised no property
notifications. It now publishes the snake_case paging properties on its hub in
the Swift order, and `from_composite` follows a `CompositeVm` source, as C#,
Python, TypeScript, and Swift do (COL-031).

Evidence: the Rust `paged_composition_notifications` conformance tests.

## 12.12. Resolved: FilteredCompositeVm Initial Cursor Policy

**Resolved (ADR-0207, #1260).** Rust `FilteredCompositeVm::new` always
reconciled under `SnapToFirst`, so a `Clear` or `PreserveIfVisible` view
started on the first visible item. `with_cursor_policy` and
`scored_with_cursor_policy` now take the policy at construction, as C#, Python,
TypeScript, and Swift do, and such a view starts with no current item. `new`
and `scored` keep `SnapToFirst`.

Evidence: `constructor_cursor_policy_sets_the_initial_current_item` and
`scored_constructor_cursor_policy_sets_the_initial_current_item` in the Rust
`filtered_composite` conformance tests.

## 12.13. Resolved: Aggregate Preflight Candidate Cleanup

**Resolved (ADR-0226, #1324).** When a population fails before its commit,
C#, Python, TypeScript and Swift dispose the candidates that nobody owns
(ADR-0224). Rust `AggregateVm1` to `AggregateVm6` returned the
`validate_fixed_aggregate_candidate` error before they disposed any
candidate. A refused `construct()` or `reconstruct()` now disposes each fresh
lazy-slot candidate that nobody owns. The cleanup skips a candidate that has a
parent, that another ownership claim holds, or that is an owner on the
aggregate's ancestor chain. It disposes each identity once, and the preflight
error propagates. An eager slot keeps its existing value. `AGG-008` covers the
rule in all five flavors.

Evidence: the Rust `failed_population_cleanup` conformance tests cover
`construct()` and `reconstruct()`, arities two to six, a duplicate
candidate, a failed candidate disposal and a candidate that another
transaction holds. The existing cycle-preflight tests show that the aggregate
and its ancestors are not disposed.

## 12.14. Closed: Container Destruct Walk Join

Chapter 02 §6 says that a destruct walk joins a child whose destruct is in
flight, also one that another thread started after the walk read the status
(ADR-0218, #754, #1375). C#, Python and Swift join it. TypeScript has one
thread, so the case does not arise.

Rust containers did not join it. The `CompositeVm`, `GroupVm` and
`AggregateVm1` to `AggregateVm6` destruct walks call `transition_child` for
each child, and that call ran `destruct()` with no join. `destruct()` returned
`VmxError::InvalidLifecycleTransition` from `Destructing` while the child's
transition was in flight, so the container destruct failed. The `ComponentVm`
leaf walk used the same helper and had the same window. Only the aggregate
construct join was closed (§12.7).

ADR-0228 closes the item. The shared child-transition helper joins a destruct
that the child refuses because another starter began it. The regression tests
are `langs/rust/tests/conformance/destruct_start_race.rs`. #1569 tracks the
item. The C# sibling, #1375, closed on 2026-11-09 and is cited only as
history.
