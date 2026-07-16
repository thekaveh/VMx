# 2026-07 Rust Capability Parity Gaps

Filed: **2026-07-16**. This record documents a set of capability-surface parity
breaks between the Rust flavor and the four other flavors (C#, Python,
TypeScript, Swift), together with the canonical-behaviour decision and a proposed
fix for each. It is a tracked backlog for a focused Rust follow-up, not a release
note. The Rust flavor is a source-tree flavor and has not been published to
crates.io, so these corrections are pre-publication and carry no released-API
break.

## 1. Scope and authority

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

## 2. Canonical-behaviour decision

The spec is canonical. Rust converges onto the spec surface that the other four
flavours already implement. No spec amendment is proposed: the gaps are Rust
under-implementations, not spec defects. Because the Rust traits are public and a
few changes add required members, this is a coordinated pre-publication reshape
best landed as one reviewed change with a Rust `CHANGELOG.md` entry and, where a
member is added to a public trait, a short ADR noting the parity correction.

## 3. Gaps and proposed fixes

### 3.1. Selection and expansion opt-in inverted (CAP-020)

`ComponentVm` blanket-implements `Selectable`, `Deselectable`,
`SelectionTogglable`, `Expandable`, `Collapsible`, and `ExpansionTogglable`
(`capabilities.rs`), and no Rust type implements the baseline `Constructable` /
`Destructable` / `Reconstructable` triple. `spec/14-capabilities.md` §Rule 2 and
`spec/05-component-vm.md` state the opposite: a core VM auto-satisfies only the
lifecycle triple and opts into every other capability explicitly. Swift codifies
this exact rule in ADR-0059 (the base type carries the methods but does not
declare the capability). No Rust code depends on the `ComponentVm: Selectable` /
`Expandable` bounds, so the blast radius is limited to the trait impls and the
CAP-020 test.

Proposed fix: remove the six blanket capability impls for `ComponentVm` (retain
the inherent `select` / `expand` / … methods), add `Constructable` /
`Destructable` / `Reconstructable` impls for the core VM types, and rewrite the
CAP-020 test to assert trait satisfaction through generic bounds (matching the
`is` / `isinstance` / `hasCapability` / `as?` checks of the other four suites).

### 3.2. Filterable has a different shape (CAP-021)

Rust's `Filterable<T>` exposes `filter_term() -> String`, `set_filter_term`, and
`accepts`. `spec/14-capabilities.md` and ADR-0022 define exactly two members: a
settable `filter: Predicate<T>?` (where clearing to `None` removes the filter)
and `can_filter() -> bool`. The four peers implement the predicate shape. Rust's
`Filterable` has no concrete implementor today (`FilteredCompositeVm` carries its
own inherent methods), so the reshape is contained.

Proposed fix: replace the term-based members with a predicate-based
`filter(&self) -> Option<Arc<dyn Fn(&T) -> bool>>`, `set_filter(&mut self, Option<…>)`, and `can_filter(&self) -> bool`; rewrite the CAP-021 test to the
spec Given/When/Then, including that `None` clears the filter.

### 3.3. Pageable ships three of eight members (CAP-022)

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

### 3.4. Expandable lacks is_expanded (CAP-004)

Rust's `Expandable` has `can_expand` and `expand` but not the `is_expanded` read
the contract requires; CAP-004 asserts `f.is_expanded == true` after `expand()`.
All four peers expose `is_expanded`. Rust's `walk_expanded` cannot gate on the
capability and instead reads a separate `TreeNode::is_expanded_for_walk`.

Proposed fix: add `fn is_expanded(&self) -> bool` to the trait, assert it in
CAP-004, and route `walk_expanded`'s gate through it.

### 3.5. Searchable exposes the term read-only (CAP-008)

Rust's `Searchable::search_term` is read-only; the spec and all four peers make
the term read/write and CAP-008 sets `f.search_term = "abc"`. `SearchableState`
already has a setter, but the capability trait does not expose it.

Proposed fix: add a `set_search_term` member (interior-mutable, matching
`SearchableState`) and drive CAP-008 through it.

### 3.6. ExpandableState is missing members

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

### 3.7. SearchableState retains the term after disposal

Rust's `SearchableState::search_term` returns the retained last term after
`dispose()`; C#, Python, TypeScript, and Swift each return the empty string, with
explicit parity comments. The Rust setter already guards disposal; only the
getter diverges.

Proposed fix: return the empty string from `search_term()` when disposed, so the
read converges with the four peers.

## 4. Disposition

Filed for a focused Rust capability-parity follow-up. The other four flavours
remain member-identical to the spec; the source-tree Rust flavour is the sole
outlier, and no correction here alters a published artifact. Until the follow-up
lands, `compatibility-matrix.md`'s full-parity claim for Rust should be read as
"conformance-ID coverage present; capability-member parity tracked here".
