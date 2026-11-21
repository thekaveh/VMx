# ADR 0234 — Registered reactive state with tracked dependencies for view-models

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (decision record; chapter 05 §2.3 records the
  direction now; chapter 24 and the other chapter edits land with the
  implementations)
- **Supersedes:** [ADR-0040](0040-iproperty-not-adopted.md) §2, the
  INPC-pattern clause of §4 item 1, and §4 item 2, for the view-model state
  that a class registers
- **Amends:** [ADR-0083](0083-dual-channel-property-notification-helper.md)
  §4.1
- **Extends:** [ADR-0172](0172-one-wait-for-graph-per-flavor.md), with the
  wait of a foreign write for the reactive drain (§2.6 rule 4)
- **Related:** [ADR-0002](0002-rx-as-reactive-primitive.md),
  [ADR-0006](0006-idiomatic-api-per-language.md),
  [ADR-0009](0009-cross-flavor-divergence-catalogue.md),
  [ADR-0011](0011-derived-properties.md),
  [ADR-0039](0039-property-changing-not-supported.md),
  [ADR-0101](0101-hold-rx-and-gate-tc39-signals-interop.md),
  [ADR-0209](0209-rust-stream-and-recompute-waits-join-the-wait-for-graph.md),
  [ADR-0235](0235-commands-created-and-owned-with-tracked-predicates.md),
  [ADR-0236](0236-members-registered-with-an-owner-and-owner-scoped-injection.md),
  [ADR-0237](0237-construct-scoped-reactions.md),
  [ADR-0238](0238-owner-declared-keyed-resource-driver.md), the design
  proposal
  [`2026-11-15-registered-reactive-state.md`](../proposals/2026-11-15-registered-reactive-state.md),
  rows D21 and D22 of the
  [upstream-candidates plan](../proposals/2026-10-20-upstream-candidates-plan.md),
  #1997, #372, #1580, #1897, #100, #142, #78, #593.

## 1. Context

### 1.1 Properties today

A VMx view-model publishes its state through host-language properties and one
dual-channel helper (chapter 05 §2.3). The author owns the storage, the
equality guard and every announcement. A derived value has no node of its own.
Each change of an input must announce every name that depends on it, including
the names that other view-models compute from it, and an owner calls its
members so that they announce again. `DerivedProperty` does not close this gap:
it takes value streams, not view-model state, and it sends nothing on the hub
(ADR-0011 §4).

### 1.2 Evidence

The evidence comes from a production Vue client of the published TypeScript
package `@thekaveh/vmx` 3.30.0. It is the Vue consumer of the October plan
(`spec/proposals/2026-10-20-upstream-candidates-plan.md`). Its view-model layer
has 85 files and 12,701 code lines (non-blank, non-comment lines). A study
recorded 603 findings in that layer. It then rewrote the whole layer twice, as
type-checked prototypes, and no view needed a change:

| Rewrite | What the rewrite may use                                                                  | Code lines | Against today |
| ------- | ----------------------------------------------------------------------------------------- | ---------- | ------------- |
| Today   | `@thekaveh/vmx` 3.30.0                                                                    | 12,701     | —             |
| Tier A  | client changes only, on `@thekaveh/vmx` 3.30.0                                            | 9,199      | −27.6%        |
| Tier B  | tier A, the unreleased TypeScript 3.31.0 source and a prototype of the decisions recorded | 7,470      | −41.2%        |

The published TypeScript 3.30.0 implements spec 3.29.0. The TypeScript 3.31.0
source on `develop` is unreleased; tier B used its helpers, such as `ownMember`
and the child-transition helper. Tier A moved 1,282 lines into the client's
models layer. Without the moved lines, tier A removes 17.5% of the layer and
tier B 31.1%. The VMx changes alone take the layer from 9,199 to 7,470 lines
(−18.8%). Both rewrites type-check the
whole layer under the client's strict compiler settings. Independent reviewers
checked both rewrites for behavior parity, and a runtime smoke test ran tier B
through 12 scripted scenarios: all 105 expectations passed.

| Measure in the view-model layer                            | Today   | Tier B  |
| ---------------------------------------------------------- | ------- | ------- |
| `_notifyPropertyChanged(` calls                            | 283     | 4       |
| Getters / setters                                          | 553 / 3 | 317 / 1 |
| Push calls between view-models (`x.refresh()` and similar) | 69      | 0       |
| Command builder chains                                     | 117     | 0       |
| `.triggers(` / `raiseCanExecuteChanged()` calls            | 39 / 13 | 0 / 0   |
| `hub:` arguments passed to members                         | 139     | 8       |
| Overrides of lifecycle hooks                               | 83      | 5       |

Of the 603 findings, 229 depend on a VMx change. They form 28 themes worth
about 2,650 removable lines. Five themes share one mechanism, registered
reactive state, and hold 66% of those lines. Tier B uses 67 computed
registrations, 21 state writers, 60 members, 57 reactions, 8 keyed resources or
drivers and 88 helper commands.

VMx's own code shows the same gap. The Python and TypeScript flagships hold 13
subjects that feed derived values (#1997). Library and flagship code
repeats single-name helper calls up to 13 times in a row (#1897).

A TypeScript prototype implements the design on the unchanged TypeScript
package 3.30.0. It
passes 282 tests in two identical runs. They include 69 and 57 tests from two
adversarial rounds, whose authors were told to break the design. A randomized
run of 300 seeds of 600 operations, with writes and disposals made by
observers, holds. In Node production mode, with 70 view-models of 10 computed
properties each, one write that 350 computed properties read re-evaluates and
announces them in 0.43 ms. A write to the own state of one view-model, which
two of its computed properties read, takes 4.4 µs. The proposal (§8) gives the
method and the limits of these measurements.

### 1.3 The decisions in the way

ADR-0040 §2: "VMx does not adopt `IProperty<T>` as a first-class reactive
backing-field type. Plain fields plus the host language's INPC convention
remain the property idiom." ADR-0040 §3 gives four reasons. Each flavor has "a
one-line idiom" for a field with a change notification. `DerivedProperty`
already handles a value with several sources. Implicit conversion "is exactly
the magic ADR-0018 cited as a clarity regression". Last, "Two-class-of-property
forces a per-site choice."

ADR-0039 §4: "This ADR may be reconsidered if (a) a `THEME-NNN` scenario
requires transactional changing→changed observation, or (b) ADR-0040
(`IProperty<T>`) is reopened — the two are conceptually paired."

ADR-0083 §4.1: "Rejected by ADR-0040 and still unnecessary. It would own storage
and introduce a second property idiom when only notification composition is
missing." ADR-0083 §4.4: "Rejected. Value equality, derived-change detection,
and storage are property-specific and language-specific. Keeping them at the
mutation or refresh site preserves transparent host-language semantics and
keeps the helper single-purpose."

Chapter 05 §2.3, last paragraph: "This is the only property-authoring
convenience added by VMx. Per ADR-0040, VMx does not provide `IProperty`
wrappers, decorators, implicit accessors, mutation history, or automatic
equality/old-value tracking."

Plan D21 (`declare<T>` and `derive<T>`), disposition "Decline": "Spec 05 §2.3,
ADR-0040, ADR-0083 §4.1 and §4.4, #78, #100, #593. "Announce once for two
causes" contradicts lossless hub deferral (spec 03 §3.3)." Plan D22 (a variadic
`_notifyPropertyChanged`), disposition "Defer": "Low value for a five-flavor
change to a pinned contract (CVM-007)." Chapter 03 §3.3: "The contract is
**lossless deferral**, not message coalescing", and its first rule says "No
message is merged, replaced, or dropped."

The scope of #372 says: "Add no global hub subscription and no inferred closure
dependencies." #1580 asks "Which trigger sources the factory accepts: a
view-model, a container, a stream." Both sketches list the sources by hand:
#1580's sketch lists them as `watch: [this, this.notes]`, and #1997's sketch
passes `[this, this.notes]` to `derived`.

ADR-0011 §4 calls the derived property "a self-contained primitive" that "works
with any `IObservable` source", and it says: "This ADR does not modify the
message hub." The 2026-07-10 review that closed #100 says: "Adding a second
"derived" type would split documentation and parity without new semantics."

ADR-0101 §2.1: "VMx will not replace its Rx/Combine/reactivex or VMx-owned Rust
hot-stream internals while TC39 Signals remains Stage 1. VMx will not add
`signal-polyfill`, a `toSignal` helper, or a supported Signal package subpath
under this decision."

### 1.4 What the evidence and the design answer

| Decision and its reason                                                         | Answer                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ADR-0040: language features cover the use case                                  | The measured gap is derived values and their propagation, not setter syntax: 283 hand-written announcements and 69 push calls. The idioms that ADR-0040 §1 names do not occur in the library sources or in the flagship view-models: no `[CallerMemberName]`, no Python descriptors, no TypeScript `accessor` fields, and `@Published` only in the SwiftUI adapter classes of the Swift flagship. |
| ADR-0040: `DerivedProperty` handles several sources                             | It takes value streams and publishes nothing on the hub, so each use needs a hand-fed stream and a bridge back to the helper (#1997).                                                                                                                                                                                                                                                             |
| ADR-0040: implicit conversion is magic                                          | Nothing converts. The public type of a property is its value type.                                                                                                                                                                                                                                                                                                                                |
| ADR-0040: two classes of property force a per-site choice                       | One idiom per class: registered state plus ordinary getters, with the computed ones named once.                                                                                                                                                                                                                                                                                                   |
| ADR-0083 §4.1: only notification composition is missing                         | The client has the helper and still writes storage, guards and derived announcements by hand. The missing piece is the propagation of changes across view-models, which one helper call cannot provide.                                                                                                                                                                                           |
| ADR-0083 §4.4: the helper must not compare or assign                            | Kept. Equality lives in each registered node and is property-specific and language-specific, as §4.4 asks.                                                                                                                                                                                                                                                                                        |
| Plan D21: "Announce once for two causes" breaks lossless deferral               | Each accepted write is one cause and settles alone. Two writes announce twice, and nothing is merged across writes.                                                                                                                                                                                                                                                                               |
| #78 and #593: a one-line property and a compare-and-assign `_set` were declined | #78 was resolved by the helper alone, and #593 dropped `_set` under ADR-0083 §4.4. Registered state keeps the helper single-purpose: the comparison and the assignment live in the graph node (§2.3 rule 1).                                                                                                                                                                                      |
| ADR-0040 §4: revisit for transactional changing→changed observation             | Not the ground here. The supersession rests on the measured propagation gap. ADR-0039 is reconsidered in the same change and kept (§2.2 rule 3).                                                                                                                                                                                                                                                  |
| #372: no inferred closure dependencies                                          | Source lists do not scale: 16 of the client's triggers re-check a gate on every property change of a whole view-model, and predicates read callback options and other view-models' state that a list must name one by one. Tracking needs no hub subscription.                                                                                                                                    |
| ADR-0011 and #100: no second derived type                                       | A registered computed is no second `DerivedProperty`. It derives from view-model state and publishes on the hub, which ADR-0011 §4 keeps out of `DerivedProperty`.                                                                                                                                                                                                                                |
| ADR-0101: hold Rx, gate Signals                                                 | The tracker is VMx-owned in all five flavors and depends on no Signals proposal and no signal library.                                                                                                                                                                                                                                                                                            |

## 2. Decision

### 2.1 Adoption

1. VMx adopts registered reactive state for view-models, in all five flavors.
   A view-model declares its observable state once. It registers the computed
   properties whose dependencies VMx tracks through any call chain. Private
   reactive values (`signal` and `memo` in TypeScript) belong to the same
   dependency graph.
1. Tracked (inferred) dependencies are in scope. The scope line of #372, "no
   inferred closure dependencies", is lifted. Tracking replaces the explicit
   source lists of #1580 and #1997. Explicit triggers remain only for inputs
   outside the graph (ADR-0235).
1. Registration is explicit. A view-model publishes exactly the state and the
   computed properties that it registers. Registrations belong in
   constructors and field initializers; a later registration is allowed (the
   proposal R3.7). A class that registers nothing keeps plain fields and the
   helper, and both forms work together.
1. ADR-0235 to ADR-0238 record the parts that build on the graph: commands with
   tracked predicates, members and owner-scoped injection, construct-scoped
   reactions, and a keyed resource driver.
1. The design proposal `spec/proposals/2026-11-15-registered-reactive-state.md`
   holds the complete rules (§3), the API of each flavor (§4), the conformance
   plan (§5), the decided open questions (§6), the implementation plan (§7) and
   the evidence (§8). A new chapter 24, "Registered reactive state", will hold
   the normative rules under the `RSTATE` prefix when the flavors implement
   them.

### 2.2 The public surface

1. Views read plain values through host-language properties: the public type
   of a registered property is its value type. No view-model member exposes a
   wrapper, an `IProperty<T>`, an implicit conversion or a mutation history.
   The node types of rule 4 (`State<T>`, `Computed<T>`, `Signal`, `Memo`, the
   Swift `@Observed` and `@Computed` wrappers, the Rust handles) are public
   VMx types that a class keeps in private storage only.
1. For the state that a class registers, registered state replaces the idiom
   of ADR-0040 §2 ("Plain fields plus the host language's INPC convention
   remain the property idiom"); the class's other properties may keep plain
   fields and the helper. The rest of ADR-0040 stays, except the INPC-pattern
   clause of its §4 item 1 and its §4 item 2 (§2.8 rule 1).
1. ADR-0039 stands. VMx announces changed values only and adds no "changing"
   notification. This ADR reconsidered ADR-0039 under its §4 clause (b) and
   keeps it.
1. The declaration syntax follows ADR-0006. TypeScript declares public state
   with `declare readonly x: T` (or `declare x: T` for state that callers may
   assign), registers it with `observable({...})`, and registers ordinary
   getters with `computed(...)`. C# reads `State<T>` and `Computed<T>` fields
   through properties, because C# cannot wrap an existing getter, and it names
   the state helper `ObservableState`, because a base member named
   `Observable` would hide the Rx `Observable` class. Python
   installs descriptors over `@property` getters at the first registration.
   Swift uses the VMx property wrappers `@Observed` and `@Computed`; a
   `@Computed` wrapper takes a key path to a private getter (the proposal
   §4.5). Rust closures capture `State<T>` and `Computed<T>` handles and
   never `self`. Sugar beyond these members (decorators, source generators,
   macros) is optional per flavor. A generator stays behind the gates of #399
   and #400. The implementation of each flavor adds its rows for these
   differences beyond casing to the divergence table of ADR-0009.

TypeScript, as the proposal (§4) defines it (not shipped):

```ts
export class SectionVM extends ComponentVM {
  declare readonly isEmpty: boolean;
  declare readonly title: string;
  readonly #expansion = this.own(new ExpandableState(false));
  readonly toggleCommand = this.relayCommand(
    () => this.#expansion.toggleExpansion(),
    () => !this.isEmpty,
  );
  readonly #set;

  constructor(o: SectionVMOptions) {
    super({ name: `section:${o.key}`, hub: o.hub, dispatcher: o.dispatcher });
    this.#set = this.observable({ isEmpty: o.isEmpty, title: o.title });
    this.computed("collapsed", "toggleText");
  }

  get collapsed(): boolean {
    return this.isEmpty || !this.#expansion.isExpanded;
  }

  get toggleText(): string {
    return this.collapsed ? "Show" : "Hide";
  }

  update(isEmpty: boolean, title: string): void {
    this.#set({ isEmpty, title }); // one write, one settle
  }
}
```

A view reads `vm.collapsed` as a `boolean`. One `update()` call announces
`isEmpty`, `title`, `collapsed` and `toggleText`, each only when it changed.
`toggleCommand` raises `CanExecuteChanged` only when `isEmpty` changed.

### 2.3 Writes and settles

1. Every registered node has an equality. It is the flavor's default equality
   unless the registration names one: `Object.is` in TypeScript,
   `EqualityComparer<T>.Default` in C#, `==` in Python and Swift, and
   `PartialEq` in Rust. A write is accepted only when a value differs by that
   equality. The node decides acceptance before it commits. The helper still
   compares nothing and assigns nothing (ADR-0083 §4.4). An equality runs as
   an evaluation that records no dependency and cannot write. An equality that
   throws counts as "not equal", and the throw is reported.
1. Each of these is one write (the proposal R6.1 lists every kind): an
   assignment to one registered property; one call of a state writer, for
   every key of its patch; an assignment to a private signal; one
   `invalidate(...)` call; the native commits of one library mutation; each
   status transition of a lifecycle operation, so a `construct()` makes two
   writes; and the exit of an outermost `change(fn)` scope. The `execute` of a
   command is no write; the writes of its task are. A write after the owning
   view-model published `Disposed` is ignored.
1. An accepted write settles before it returns. The settle brings each
   affected computed property up to date at most once, in dependency order. A
   value that is equal to its previous value stops the propagation there. The
   settle then announces each published value that changed exactly once,
   through one call of the unchanged dual-channel helper: the hub message
   first, then the VM-local name (chapter 05 §2.3). A diamond A → B, A → C,
   B + C → D announces D at most once per write.
1. One write is one cause. Two writes are two settles, and they announce a
   value twice when it changed twice. Nothing is merged across writes, and
   nothing waits for a microtask, a debounce or a hub transaction. The lossless
   deferral of chapter 03 §3.3 holds, which answers plan D21.
1. A multi-key patch and a `change(fn)` scope are single changes that the
   author declares, as today's hand-written methods assign several fields and
   then notify once. Inside a scope, writes commit without settling, and reads
   are fresh. Nested scopes flatten. The outermost exit settles once, also when
   `fn` throws, and the error of `fn` takes precedence over an error of the
   drain. A value that changed and changed back inside one scope is not
   announced; each node decides this by its own equality.
1. A change scope never opens or closes a hub transaction, and a hub
   transaction opens no change scope. Inside `hub.batch`, the hub holds the
   messages of the graph like any other send, and the VM-local names are
   emitted at once, as chapter 05 §2.3 already allows.

### 2.4 Order, the drain and re-entrancy

1. One FIFO drain per process holds the announcements, the command raises of
   ADR-0235 and the reaction runs of ADR-0237. Within one settle, the
   announcements go by dependency height and then by registration order, the
   command raises follow, and the reaction runs come last. Entries of
   different settles keep their queue order, except that the producer flush
   of rule 3 delivers queued announcements ahead of earlier command raises and
   reaction runs (the proposal §6, question 4).
1. A write made while the drain runs, by a hub or local observer, a
   `CanExecuteChanged` handler or a reaction, settles at once and appends its
   entries. Delivery never recurses on the call stack, and the outermost write
   returns with an empty queue (chapter 03 §3.3). Rule 3's flush is the one
   bounded exception.
1. Producer order (chapter 03 §3.2). Before a view-model sends outside the
   graph, for example by a hand-written helper call, by the local-only raise,
   by a status transition or by a model assignment, the drain delivers that
   view-model's queued announcements. Its messages therefore reach the hub in
   the order in which they were caused.
1. State first (chapter 03 §3.6). A library publication commits the library
   state that it publishes before it delivers anything, and it holds the drain
   until it returns. An observer of the library's own message therefore reads a
   computed property over that state fresh, and the dependents are announced
   after the library's own messages. A library mutation that changes several
   library properties, such as a selection move, is one write.
1. Delivery is lossless. A name that an outer settle and a nested settle both
   change is announced by both. Before a view-model publishes `Disposed`, the
   announcements of the writes that it accepted are delivered. The one
   exception is a view-model disposed inside an open change scope in which it
   wrote, because that scope has not settled yet.
1. Development builds bound one drain as a cycle detector. When one entry
   repeats more than 10,000 times in one drain, the drain throws
   `ReactiveOverflowError` (Swift reports it to the hub's development
   diagnostic handler, as the hub's own bound does), which names the repeating
   entries, and abandons the rest of the queue. Production builds have no bound
   (chapter 03 §3.3), unless the process-wide test override of the proposal
   (R19.13) turns the diagnostics on. The override can turn the bound on or
   off in any build configuration, so the reactive bound is gated at run time
   and is not compiled out.

### 2.5 Activation and tracking

1. A registered computed property acts as a plain getter until its view-model
   activates. Activation happens at the first of these: the start of the first
   construct, after `Constructing` is published and before `_onConstruct`; the
   first subscription to the VM-local property-change surface; registration as
   a member of an activated owner, or addition to an activated container; the
   activation of its owner or container; in C#, Python, TypeScript and Swift,
   a subscription to a VMx hub helper that names the view-model as the sender
   (Rust hosts call `activate`, the proposal R4.2); and an explicit
   `activate(vm)`.
   Activation takes silent baselines and announces nothing. A baseline is
   never taken in a constructor, because a base-class constructor would
   evaluate subclass overrides before the subclass fields exist.
1. A read inside an evaluation records a dependency at read time, and each
   evaluation replaces its earlier dependencies. Tracking follows any call
   chain: plain getters, methods, callback options and the accessors of other
   view-models are transparent. A read of an activated computed property
   records that property, not its sources. `untracked(fn)` and `peek()` record
   nothing.
1. Library operations run untracked: lifecycle calls, member and container
   changes, model assignments, command executions and resource loads. Inside an
   evaluation they throw before they change anything. Deliveries also run
   untracked (a hub send, a VM-local emission, a raise), so an observer never
   records into the evaluation that caused the delivery.
1. Every library property that announces a change is tracked natively, for
   example `status`, `isConstructed`, `isCurrent`, `model`,
   `AsyncResourceVM.state`, `ExpandableState.isExpanded`, the `current` and the
   children of a container, `AsyncRelayCommand.isExecuting`, and the result of
   `canExecute()`. The proposal (§3) lists them. `read(source, name)` is the
   migration bridge: it tracks a property of a view-model that still announces
   by hand.
1. Sender identity stays normative (plan D33). Each view-model announces only
   its own names. A computed property of one view-model that reads another
   view-model is re-evaluated and announced by its own view-model.

### 2.6 Errors, disposal and threads

1. Evaluations, such as a computed property, a memo, a predicate, a select and
   an equality, cannot write or register. A write, a registration or a library
   operation inside an evaluation throws `ReactiveWriteError` (the flavor's
   idiom), also in production builds, and changes nothing.
1. A computed property that throws during a settle enters an error state. The
   error is never memoized. A change from a value to an error, from an error to
   a value, or to a different error is a change, and it is announced. Each
   change into an error, or to a different error, is reported once on the
   stream-fed route (chapter 03 §3.6). A throw on a direct read goes to the
   reader. A node read during its own evaluation throws `ReactiveCycleError`,
   and catching that error does not hide the cycle.
1. Disposal removes every dependency to and from the nodes of the view-model.
   A dependent in another view-model keeps its value and loses the dependency.
   A read of a disposed view-model's computed property returns its last value.
   Nothing in the graph keeps a disposed view-model reachable.
1. C#, Python, Swift and Rust have one reactive drain per process. A write
   from another thread waits for the drain, and that wait is a new row of the
   wait-for graph of chapter 03 §4.1: when the wait would close a cycle, it is
   refused, and the write commits and leaves its settle to the drainer. No VMx
   lock is held while consumer code runs. A thread that does not hold the drain
   evaluates a dirty node without storing the result (the rule of ADR-0209).
   Announcements and reaction runs happen on the drainer thread, under the
   foreground rules of chapter 11. TypeScript is single-threaded and needs
   none of this rule.

### 2.7 Development diagnostics and decided questions

1. Apart from the drain bound of §2.4 rule 6, development diagnostics change
   no synchronous behavior. Diagnostics that evaluate user code run on a later
   task. Each report is made once per kind, class and name, and production
   builds report nothing. The diagnostics report a computed property that
   changed without a tracked dependency, a public getter that reads tracked
   state but is not registered, a hand-written helper call for a registered
   name, and the usage mistakes that the proposal lists. `explain(vm, name)`
   lists what a computed property read in its last evaluation.
1. The check for unpublished getters exempts a getter that reads only
   immutable state, such as the model of a read-only component. Such a getter
   never needs an announcement.
1. Retained destructed view-models keep computing. Registered computed
   properties stay current and are announced in every status except
   `Disposed`. VMx documents this and adds no option to pause them now. Work
   that must wait for the next construct belongs in a construct-scoped
   reaction (ADR-0237).
1. The other open questions of the prototype are decided with their
   recommended option. The proposal (§6) states each decision.
1. The proposal (§6, rows 16 to 19) also decides where the prototype's design
   was silent or did not fit every flavor: frames and change scopes are per
   thread (R18.7), Swift recovers from cycles without trapping where a last
   value exists (R16.8), library commands keep today's raises (ADR-0235 §2.2
   rule 2), and a process-wide diagnostics scheduler and test override exist
   in every flavor (R19.12, R19.13).

### 2.8 Earlier decisions

1. ADR-0040 §2, the INPC-pattern clause of its §4 item 1, and its §4 item 2
   no longer hold for the view-model state that a class registers (§2.2 rule
   2): a registered computed property is a first-class derived value beside
   `DerivedProperty`, and private nodes back registered properties. ADR-0040
   still holds for the public surface: no `IProperty<T>`, no wrapper type on
   a view-model's public surface, no implicit conversion and no mutation
   history.
1. ADR-0083 §4.1 is amended to read: a public `IProperty` wrapper and an
   implicit conversion stay rejected; registered state may install the
   accessors of its properties (TypeScript and Python), Swift declares them
   with the VMx property wrappers `@Observed` and `@Computed`, and C# and Rust
   read private node fields through properties and accessor methods; further
   decorators, generators and macros are optional sugar per flavor (§2.2 rule
   4). The missing piece is the
   propagation of changes across view-models, not notification composition,
   and registered state provides it. ADR-0083 §4.4 stands: the helper performs
   no equality and no assignment, and equality lives in the graph.
1. The last paragraph of chapter 05 §2.3 changes now and records this
   direction. Chapter 24 replaces it with normative rules when the flavors
   implement them. The rest of chapter 05 §2.3 holds: the graph is a caller
   that decides acceptance before it calls the helper, and each announcement is
   one helper call.
1. ADR-0011 and #100. `DerivedProperty` stays the stream-composition primitive
   over explicit reactive sources, and it still sends nothing on the hub by
   itself. A registered computed property derives from view-model state and
   publishes on the hub through its view-model. They are different primitives,
   so the objection of #100 to a second derived type does not apply. A
   computed property can read the value of a `DerivedProperty`, which is
   tracked natively.
1. ADR-0101 holds. The dependency tracker is VMx-owned in all five flavors,
   and it is no Signals interop. VMx adds no dependency on TC39 Signals, no
   polyfill and no signal library, and Rx stays the reactive primitive
   (ADR-0002). The graph publishes only through the existing hub and VM-local
   surfaces. The gates of ADR-0101 still apply to any Signals interop.
   ADR-0101 §2.2 keeps TC39 Signal graphs out of the normative surface. The
   graph of this ADR is VMx's own dependency graph, specified and tested in
   all five flavors, and it publishes only through the seams that ADR-0101
   §2.2 lists. The TypeScript `Signal` type is unrelated to TC39 Signals (§3).
1. Plan D21 (`declare<T>` and `derive<T>`, #1997) is reopened and decided:
   adopt, in the form of this ADR. Plan D22 (a several-name helper, #1897)
   stays deferred: it is moot for a class that registers its state.
1. The questions of #1997 are answered here. A base member is needed:
   `observable` and `computed` (§2.2 rule 4). The path accepts every graph
   node that an evaluation reads, through any view-model or container (§2.5);
   a stream outside the graph reaches it through a `DerivedProperty`, whose
   value is a native node, or through a signal that a subscription writes.
   Activation takes silent baselines, so nothing is announced at creation, and
   before activation a registered computed reads as a plain getter, so its
   first value is readable at once. #142, a pull recompute on
   `DerivedProperty`, stays a separate question; `invalidate()` recomputes a
   registered computed over inputs outside the graph. In Rust, a computed
   reads `State<T>` and `Computed<T>` handles and the native nodes, so it needs
   no value stream. Chapter 05 §2.3 changes (rule 3).

### 2.9 Evidence bar and delivery

1. Plan §1.8.3 takes ADR-0090's pilot, a measured diff with green tests, as
   the bar. ADR-0101 §2.3 asks two independent consumers to pilot an interop
   seam. The owner proceeds on one consumer's full rewrite and the tested
   prototype. A pilot in a second consumer is a recommended validation step.
   It is tracked as a follow-up, not as a gate.
1. Chapter 24 and its conformance IDs land with the implementations. Each ID
   needs a passing test in all five flavors (`tools/check-conformance-execution.py`).
   The proposal (§7) orders the phases and their dependencies.
1. The implementations release as a spec minor version. A flavor whose
   additions break existing code, such as new base members that collide with a
   subclass member or Rust's new `VmxError` variants, takes the version that
   README §6.1 gives it.

## 3. Consequences

- The Status of ADR-0040 and its registry cell name this ADR for §2, the
  INPC-pattern clause of §4 item 1, and §4 item 2. The Status of ADR-0083 and
  its registry cell name this ADR for §4.1. The Status of ADR-0172 and its
  registry cell name this ADR as an extension: the wait of a foreign write
  for the reactive drain is a new row of the wait-for graph of chapter 03
  §4.1.
- The last paragraph of chapter 05 §2.3 changes with this record. No other
  chapter changes now, and no conformance ID is added. With the
  implementations, chapter 24 is added, and these chapters change: 02 (the
  construct, destruct and dispose sequences), 03 (the wait-for row of the
  reactive drain), 04 (tracked predicates), 05 (§2.2 and §2.3), 06, 07, 08 and
  18 (containers refuse a view-model that has an owner, ADR-0236), 11 (the
  drain thread), 13 (walks that visit members) and 23 (the keyed driver), with
  notes in 01 (§2, the VMx-owned tracker) and 15 (the distinction from
  `DerivedProperty`). An optional fixture can encode the ordering scenarios.
- Existing code keeps working: hand-written properties, the helper,
  `DerivedProperty`, triggers and hand-built commands. A class can migrate one
  property at a time, and `read()` reaches the view-models that still announce
  by hand. In development builds, a hand-written helper call for a registered
  name is reported, because the graph already announces that name.
- The component base gains members, protected where the flavor has protected
  members: `observable`, `signal`, `computed`, `memo`, `invalidate` and
  `change` here, and the members of ADR-0235 to ADR-0238. A TypeScript subclass
  that already declares one of these names with another type no longer
  compiles (§2.9 rule 3).
- The cost is a graph engine and native tracking in five flavors, and the
  drain with its wait-for row in four. The prototype has 17 source files and
  3,567 code lines. Its import-time wrappers of VMx methods (`library.ts`, 296
  lines) and its command wrappers are not needed inside VMx.
- The TypeScript box for private state keeps the prototype's name, `Signal`.
  It is a VMx type and is unrelated to TC39 Signals.
- The design proposal keeps the TypeScript prototype as reference code. The
  prototype is not shipped, and CI does not build it.

## 4. Rejected alternatives

- **Keep plain fields and the helper only.** The measured cost stays: hand
  propagation, push calls between view-models, stream adapters around
  `DerivedProperty`, and announcements that a missed call leaves stale.
- **A public wrapper type such as `IProperty<T>`.** The objections of ADR-0040
  hold for a public wrapper: reads through `.Value` or an implicit conversion,
  wrapper identity, and two kinds of property at each site. Boxes stay
  private.
- **Explicit dependency lists**, such as the source lists of #1580 (`watch:`)
  and #1997 or a `derive<T>(sources, fn)` helper. A whole view-model as a
  source re-checks on every property change, and a list must name every
  view-model that a callback reaches. A list also drifts when the code
  changes.
- **A `DerivedProperty` factory over view-model state.** It still needs value
  streams and a separate announcement, and it tracks nothing that a callback or
  another view-model reads.
- **Coalescing announcements across writes**, by a microtask, a debounce or an
  implicit hub transaction. That is the objection of plan D21: it contradicts
  lossless deferral, and it delays values that a test or an adapter reads at
  once.
- **TC39 Signals, a polyfill or a signal library as the engine.** ADR-0101
  §2.1 and §4.2 rule this out. It would make TypeScript exceptional, and
  AGENTS.md rules out another reactive library.
- **Baselines in constructors, or activation at the first write.** A base-class
  constructor would evaluate subclass overrides before the subclass fields
  exist, and the stale baseline would stay memoized.
- **One queue for direct sends and graph announcements.** A status transition
  must change the status synchronously, and deferring hand-written helper
  calls would change the behavior of code that does not migrate. Producer order
  (§2.4 rule 3) gives the order without deferring them.
- **A several-name helper (plan D22) as the fix.** It shortens the hand
  propagation and keeps it.
- **An option that pauses computing while a view-model is destructed.** No
  site needs it yet, and construct-scoped reactions already wait for the next
  construct.
