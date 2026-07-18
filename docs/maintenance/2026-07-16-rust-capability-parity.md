# 12. Rust Parity Status

Filed: **2026-07-16**. This record documents a set of parity breaks between the
Rust flavor and the four other flavors (C#, Python, TypeScript, Swift) —
capability-surface gaps (§3) and behavioural divergences (§4) — together with the
canonical-behaviour decision and a proposed fix for each. It is a tracked backlog
for a focused Rust follow-up, not a release note. The Rust flavor is a source-tree
flavor and has not been published to crates.io, so these corrections are
pre-publication and carry no released-API break.

Three behavioural divergences found alongside these were straightforward and fixed
in the maintenance run itself (not listed below): the Rust `FormVm` no longer
publishes an extra `PropertyChanged("is_valid")` onto the main hub;
`HierarchicalVm` no longer emits N spurious `PropertyChanged("parent")` messages on
first `children()` materialization; and `NotificationHub::resolve`/`dispose` now
emit the new `Pending` value before completing the awaitable (spec §2.2 order). The
items below need a signature change, a public-API reshape, a semantic decision on a
spec-underspecified edge, or a coordinated conformance-test strengthening, so they
are batched here for one reviewed change.

Revalidated **2026-07-18**. This is an active status ledger, not a claim that all
rows remain open. The current maintenance branch resolves §12.3.1 (baseline
lifecycle capability ownership), the trait-implementation portion of §12.3.6,
and the composite remove/current ordering item in §12.4.7. It also fixes Rust
inline-dispatch selection deadlock, idempotent lifecycle capability predicates,
and atomic container-admission races found after this ledger was filed. Sections
12.3.2–12.3.5, the constructor/disposal portion of §12.3.6, §12.3.7,
§12.4.1–12.4.6, and the remaining §12.4.7 bullets stay explicitly open.

## 12.1. Scope And Authority

`spec/14-capabilities.md` and the per-cluster ADRs (ADR-0010, ADR-0022,
ADR-0023, ADR-0057) are the authoritative capability contract. C#, Python,
TypeScript, and Swift implement that contract member-for-member up to documented
idiom; the Rust capability traits in `langs/rust/src/capabilities.rs` (and the
`ExpandableState` / `SearchableState` helpers) diverge in the ways listed below.
Each divergence was verified against the spec text, the four peer
implementations, and the Rust conformance suite. None is recorded as an
intentional divergence in ADR-0009, ADR-0059, ADR-0080, ADR-0081, ADR-0099, or
ADR-0103.

The Rust conformance markers for CAP-004, CAP-008, CAP-020, CAP-021, and CAP-022
are present, but each asserts the reduced Rust shape rather than the spec
contract, so a green Rust suite does not currently prove capability parity. Each
fix below therefore pairs a code change with a strengthened conformance test.

## 12.2. Canonical-Behavior Decision

The spec is canonical. Rust converges onto the spec surface that the other four
flavours already implement. No spec amendment is proposed: the gaps are Rust
under-implementations, not spec defects. Because the Rust traits are public and a
few changes add required members, this is a coordinated pre-publication reshape
best landed as one reviewed change with a Rust `CHANGELOG.md` entry and, where a
member is added to a public trait, a short ADR noting the parity correction.

### 12.2.1. Message Sender Identity Is An Accepted Idiom

Rust's `sender_id: usize` plus `sender_name: String` message fields are not an open parity gap. ADR-0120 records
it as the ownership-safe Rust expression of the canonical sender-identity
contract: the other four flavors retain runtime sender objects, while Rust
messages remain owned values that do not retain or borrow a VM. Identity
filtering behavior remains required across all five flavors.

## 12.3. Gaps And Proposed Fixes

### 12.3.1. Selection And Expansion Opt-In Inverted (CAP-020)

**Resolved on the current maintenance branch.** Rust previously blanket-
implemented the six opt-in selection and expansion traits on `ComponentVm`
while omitting the baseline `Constructable` / `Destructable` /
`Reconstructable` traits. The blanket opt-in implementations are now removed,
the lifecycle traits apply to every `VmNode`, and CAP-020 includes positive
lifecycle bounds plus a compile-negative `ComponentVm: Selectable` proof.

### 12.3.2. Filterable Has A Different Shape (CAP-021)

Rust's `Filterable<T>` exposes `filter_term() -> String`, `set_filter_term`, and
`accepts`. `spec/14-capabilities.md` and ADR-0022 define exactly two members: a
settable `filter: Predicate<T>?` (where clearing to `None` removes the filter)
and `can_filter() -> bool`. The four peers implement the predicate shape. Rust's
`Filterable` has no concrete implementor today (`FilteredCompositeVm` carries its
own inherent methods), so the reshape is contained.

Proposed fix: replace the term-based members with a predicate-based
`filter(&self) -> Option<Arc<dyn Fn(&T) -> bool>>`, `set_filter(&mut self, Option<…>)`, and `can_filter(&self) -> bool`; rewrite the CAP-021 test to the
spec Given/When/Then, including that `None` clears the filter.

### 12.3.3. Pageable Ships Three Of Eight Members (CAP-022)

Rust's `Pageable` exposes `page_index`, `page_count`, and `set_page_index`.
`spec/14-capabilities.md` §2.10 requires `page_size` (mutable),
`current_page_index` (mutable), `page_count`, `is_paging_enabled`, and the four
navigation verbs `move_to_first_page` / `move_to_previous_page` /
`move_to_next_page` / `move_to_last_page`, each a bounded no-op at its edge. C#'s
`IPageable` (verified) carries all eight. Rust's `PagedComposition` already has
`page_size` / `next_page` / `previous_page` but does not implement `Pageable`
and lacks first/last navigation and `is_paging_enabled`.

Proposed fix: extend `Pageable` to the full eight-member surface, implement it on
`PagedComposition` (the spec's canonical pageable helper), and bring the CAP-022
test up to the spec's clamping and edge no-op assertions.

### 12.3.4. Expandable Lacks is_expanded (CAP-004)

Rust's `Expandable` has `can_expand` and `expand` but not the `is_expanded` read
the contract requires; CAP-004 asserts `f.is_expanded == true` after `expand()`.
All four peers expose `is_expanded`. Rust's `walk_expanded` cannot gate on the
capability and instead reads a separate `TreeNode::is_expanded_for_walk`.

Proposed fix: add `fn is_expanded(&self) -> bool` to the trait, assert it in
CAP-004, and route `walk_expanded`'s gate through it.

### 12.3.5. Searchable Exposes The Term Read-Only (CAP-008)

Rust's `Searchable::search_term` is read-only; the spec and all four peers make
the term read/write and CAP-008 sets `f.search_term = "abc"`. `SearchableState`
already has a setter, but the capability trait does not expose it.

Proposed fix: add a `set_search_term` member (interior-mutable, matching
`SearchableState`) and drive CAP-008 through it.

### 12.3.6. ExpandableState Is Missing Members

Rust's `ExpandableState` lacks `can_toggle_expansion`, an `initially_expanded`
constructor knob, and `dispose`, and does not implement the
`Expandable` / `Collapsible` / `ExpansionTogglable` triple that
`spec/05-component-vm.md` declares for it. The four peers implement all of this
(for example C# `ExpandableState(bool initiallyExpanded = false)` with
`CanToggleExpansion()` and `Dispose()`).

Proposed fix: add `can_toggle_expansion() -> bool` (returns `true`, matching the
peers), an additive `new_expanded()` / `with_initial(bool)` constructor
(ADR-0099 §2.1 sets the additive-constructor precedent), a `dispose()` that
disposes the owned hub, and the three capability impls once §3.4's `is_expanded`
lands.

### 12.3.7. SearchableState Retains The Term After Disposal

Rust's `SearchableState::search_term` returns the retained last term after
`dispose()`; C#, Python, TypeScript, and Swift each return the empty string, with
explicit parity comments. The Rust setter already guards disposal; only the
getter diverges.

Proposed fix: return the empty string from `search_term()` when disposed, so the
read converges with the four peers.

## 12.4. Behavioral Divergences

These are Rust-only observable-behaviour differences (not capability-shape gaps)
where the other four flavours agree with each other and the spec. Each needs a
signature change, a decision on a spec-underspecified edge, or a strengthened
conformance test, so they are filed rather than fixed inline.

### 12.4.1. reparent_child Of A Detached Child Reports Added Instead Of Reparented

`langs/rust/src/hierarchical.rs` funnels `reparent_child` through `attach_child`,
which derives the change type from the prior parent only, so reparenting a
currently-detached child emits `Added` / `index = len`. C#/Python/TypeScript/Swift
carry an explicit-reparent flag (`explicitReparent: true`) so an explicit reparent
always reports `Reparented` / `index = -1`, even from detached. Spec §7/§8 and
ADR-0105 pin `AddChild`-of-detached to `Added` but are silent on
`reparent_child`-of-detached; the four-flavour consensus is `Reparented`.

Proposed fix: give Rust `attach_child(&self, child, explicit_reparent: bool)`,
with `reparent_child` passing `true`, so `reparented = explicit_reparent || old_parent.is_some()`. Alternatively record the unified choice in an ADR.

### 12.4.2. Remove Of A Non-Member Errors Instead Of No-Op

Rust returns `Err(VmxError::NonChild)` when removing a non-member; the other four
silently no-op. This is the same divergence in three places:
`hierarchical.rs` `remove_child`, `groups.rs` `remove` (`groups.rs:243`), and
`composites.rs` `remove` (`composites.rs:347`) — C#/Python/TypeScript/Swift all
no-op in every case (e.g. C# `CompositeVMBase.Remove`, `GroupVMBase`). Spec
chapters 06/07/18 do not specify remove-of-non-member.

Proposed fix: return `Ok(())` on a non-member across all three Rust removers
(match the peers), or record `NonChild` as an intentional Rust idiom in an ADR (as
was done for non-child selection). Fix all three together, not just hierarchical.

### 12.4.3. AggregateVmN::construct Interleaves Notify And Child Construct

Rust `AggregateVmN::construct` emits each `PropertyChanged("component_N")`
immediately before that slot's child `construct()`; C#/Python/TypeScript/Swift
emit all N slot-population messages first, then construct all children. This
differs on happy-path hub ordering and, more materially, on the child-construct
failure path: a failure in child 1 means Rust never emits `component_2`/`_3`,
whereas the peers have already emitted all N. Spec §2's "order … unspecified"
latitude covers slot order (still 1→N in Rust), not the notify-vs-construct
interleave or the failure-path emitted set.

Proposed fix: hoist all `notify_property_changed("component_N")` calls above the
child `construct()` calls in each `AggregateVmN::construct` (VM1–VM6), making the
emitted set and ordering identical to the peers on both paths.

### 12.4.4. FormVm Direct approve() Gates On Strict+Dirty

Rust's awaitable `approve()` gates on `can_approve()` (which includes the
strict-mode dirty check); the spec's direct `ApproveAsync` and all four peers gate
the direct path only on disposal + validity, keeping the strict/dirty gate solely
on `ApproveCommand.CanExecute` (spec §9). Consequently a strict + valid + clean
form persists via direct approve in the peers but returns `Err` in Rust.

Proposed fix: gate Rust's direct `approve()` on validity only (silent `Ok(())`
no-op when invalid, matching the peers), keeping strict/dirty on
`approve_command`'s `can_execute`. Add a Rust conformance assertion for the
strict-clean-valid direct-approve case.

### 12.4.5. Base ComponentVm Surface Is Narrower (Informational)

Rust's base `ComponentVm` omits `type`/`view_model_type`, the `can_*()` selection
gates, and four of the five built-in commands (only `select_command`), so the Rust
forwarder cannot forward them. This is a broader base-surface parity question, not
a forwarding defect; recorded here for a coordinated look during the follow-up.

### 12.4.6. DerivedProperty Does Not Subscribe To Sources Or Auto-Recompute

Rust's `DerivedProperty<T>` holds a value and exposes a manual `recompute(transform)`
that receives the current value. `spec/15-derived-properties.md` §1/§2/§4/§8 defines
a derived property as a value computed from one or more **source observables** with a
transform, subscribing to those sources **once** in its constructor and
auto-recomputing (distinct-until-changed) whenever a source emits, until `dispose()`.
C#/Python/TypeScript/Swift all take source streams (`from_one`..`from_five` /
`from_sources` / `fromOne`..; `CombineLatest`) and auto-recompute. The Rust DPROP
conformance tests assert only the reduced manual shape, so a green Rust suite does
not prove parity (the same "test asserts the reduced shape" pattern as the capability
gaps). Not sanctioned by any ADR (ADR-0009 covers only the distinct-emit equality
operator; ADR-0103's hot-stream facade exists, so this is an under-implementation).

Proposed fix: reshape Rust `DerivedProperty` to accept N source `Stream`/hot-facade
inputs plus a transform, subscribe internally, drive recompute off source emissions
(distinct-until-changed), and dispose the subscriptions; rewrite DPROP-002..005/012
to mutate real sources and assert auto-recompute.

### 12.4.7. Further Residual Divergences (Collections And Commands)

An adversarial residual sweep surfaced five more Rust-only divergences against the
four-flavour + spec consensus; each is verified in the current tree:

- **Resolved: composite remove/current ordering.** Rust previously published
  `CollectionChanged(Remove)` before clearing `current`, transiently violating
  spec/06 §3. `remove` and `remove_at` now clear selection before the observable
  removal publishes, matching the four peer flavors.
- **`collections.rs` `ObservableList::remove_at` silently returns `None` on an
  out-of-range index.** All four peers raise (`ArgumentOutOfRangeException` /
  `RangeError` / `IndexError` / trap), and Rust's own
  `ServicedObservableCollection::remove_at` returns `Err(InvalidArgument)`. Fix:
  return `VmxResult<T>` (or panic) on OOB.
- **`composites.rs` `FilteredCompositeVm` default cursor policy is `Clear`; the
  four peers default to `SnapToFirst`** (and the Rust enum also lacks the peers'
  `PreserveIfVisible` variant). Fix: default to `SnapToFirst`; add the variant.
- **`commands.rs` `ConfirmationDecoratorCommand` has no `dispose()` and no disposed
  guard**, so its `errors` channel never completes and post-dispose emission is
  unguarded — spec/04 §8.3.1 requires completion on dispose and a post-dispose
  no-op. Fix: add `dispose()` completing `errors` plus a guard on `execute_after`.
- **`commands.rs` `RelayCommand`/`RelayCommandOf::dispose` omit the final
  `can_execute_changed` notification the four peers emit** — spec/04 §5 makes this
  a MAY, so it is a soft parity gap, listed for completeness.

## 12.5. Related Spec-Wording Note (Not Rust-Specific)

`spec/02-lifecycle.md` §7 lists the parent's terminal disposal work as "…command
teardown, and stream completion," but all five flavours complete the streams
before tearing down the commands. The order in the sentence is editorial (no
conformance ID pins intra-parent order), so it is deferred rather than fixed in
this run — correcting a non-exempt `spec/` chapter requires a new ADR, which would
bump the ADR count and cascade into the count claims and generated diagrams,
disproportionate to a one-clause wording fix. Best folded into the next spec ADR.

## 12.6. Disposition

Partially resolved as recorded above and retained for a focused Rust-parity
follow-up. The other four flavours remain
member-identical to the spec and mutually consistent on behaviour; the source-tree
Rust flavour remains the sole documented outlier, and no correction here alters a
published artifact. Current public docs therefore use **catalog-complete** for
Rust: all 395 library IDs are represented, while capability-member and residual
behavior parity remain tracked here.
