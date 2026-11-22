# ADR 0242 — SelectCommand and DeselectCommand re-raise CanExecuteChanged on their selection inputs

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapter 05 §5, §6.1 and §9, `CVM-011`)
- **Extends:** [ADR-0049](0049-v3-command-semantics.md) with the trigger rule of the
  built-in component commands. Related: #1755, [ADR-0086](0086-imperative-command-requery.md),
  [ADR-0174](0174-formvm-queues-updates-during-approval-publication.md),
  [ADR-0188](0188-silent-selection-refusals-for-child-select-and-destructing.md),
  [ADR-0189](0189-disposed-children-leave-current-and-container-walks.md).

## 1. Context

Chapter 05 §5 fixes one trigger, "derived from `Status`", for all five built-in
component commands. Chapter 05 §6 defines the two selection predicates over `Parent`,
`Parent.Current` and `Status`. In every flavor, a successful `select()` changes both
predicates and sends no `CanExecuteChanged`. The same holds when `Current` moves to a
sibling, and when a container adds or removes a `Constructed` child. A bound control
therefore keeps a stale `CanExecute` until the next lifecycle transition.

ADR-0049 fixed the same defect for `ModeledCrudCommands` (chapter 04 §4.2). It did not
reach the built-in component commands. This ADR does.

## 2. Decision

### 2.1 The trigger inputs of the selection predicates

`SelectCommand` and `DeselectCommand` re-raise `CanExecuteChanged` when one of these
three inputs changes. Each row names the reason the input is needed.

| Input                                          | Read by                                                    | Change that re-raises                                                                                          | Why it is needed                                                                                                                                                                             |
| ---------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Status`                                       | both predicates (`Constructed`, `!= Disposed`)             | the existing status publication                                                                                | Unchanged. The status trigger already covers it.                                                                                                                                             |
| `IsCurrent` (mirrors `Parent.Current == this`) | `can_select` (`Parent.Current != this`) and `can_deselect` | the `IsCurrent` publication, after the flag commit                                                             | A select, a deselect or a move of `Current` changes this flag. No other input of the child changes.                                                                                          |
| `Parent` link                                  | both predicates (`Parent is not null`)                     | a container writes the link: set on add, index replacement or population, cleared on remove, clear or transfer | An add or a remove changes both predicates with no status change and no property change. Chapter 05 §6.1 says the link emits no `PropertyChangedMessage`, so the link needs its own trigger. |

The parent's selection support (`Parent.SupportsChildSelection`) is not an input. It is a
fixed property of the parent's type (`CompositeVM` true, `GroupVM` false). It changes only
with the link, which is already an input. Chapter 04 §4.2 requires a trigger for each
mutable input of a predicate, and this set meets that rule.

### 2.2 Which commands take which triggers

- `SelectCommand` and `DeselectCommand` take the status trigger and the selection trigger.
- `SelectNextCommand`, `SelectPreviousCommand` and `ReconstructCommand` take the status
  trigger only, as before. Their predicates read only `Status` or a constant.

The same rule applies in all five flavors, because chapter 05 §5 states one trigger rule for
the five built-in commands.

### 2.3 When the selection trigger fires

- It fires once per committed change of the `IsCurrent` flag. The publication of that
  change is the source. A commit that changes nothing does not fire.
- It fires once per write of the `Parent` link that changes the link. A write that names the
  same container does not fire.
- It is queued in the selection-input scope of §2.4 when the change happens inside a
  container membership change (a membership transaction or a membership gate section) or
  inside an aggregate slot replacement. The outermost scope on the thread emits every queued
  notification when it closes. A close runs after the container has released its membership
  gate and ended its transaction, so no `CanExecuteChanged` subscriber runs under a container
  lock or inside an open membership change (chapter 06 §4.3). A change made outside every
  scope emits at once, after the child's own state guard and link lock are released
  (chapter 02 §2.4).
- It does not fire once the child's teardown has begun. C#, Python and TypeScript check the
  same teardown flag that the status trigger checks. Swift checks its teardown flags and that
  `Status` is not `Disposed`. Rust checks that `Status` is not `Disposed`. Every flavor
  completes the subject at teardown and never disposes it (§2.4).
- The notification reaches subscribers through the existing `CanExecuteChanged` channel. It
  adds no `PropertyChangedMessage` and no `ConstructionStatusChangedMessage`.

### 2.4 How each flavor carries the trigger

Each flavor has two parts: a private selection subject per VM, and a selection-input scope
that holds the notification back while a container change is open.

- The subject. C#, Python and TypeScript keep a private selection subject beside the status
  subject, and both commands take it as a second trigger. C# checks the disposal flag under the
  lifecycle gate and emits outside it. Swift keeps a private `VMxConcurrentSubject` beside the
  status subject (ADR-0174), because a composite thread sends it. Rust keeps a private
  `MessageHub` in each component core, which carries a `Message::Custom` named
  `selection_inputs`. The public hub is not used, and `Message` gets no new variant. It is
  public and has no `#[non_exhaustive]` attribute, so a new variant would be a breaking change.
  Containers build their select and deselect commands through
  `ComponentCommands::with_liveness`, so containers take the same trigger.
- The scope. It is a per-thread depth count and a queue of pending notifications. The
  thread-local state is
  `[ThreadStatic]` in `SelectionInputScope` (C#), `threading.local()` in `components/base.py`
  (Python), module state in `components/selectionInputScope.ts` (TypeScript, which runs on one
  thread), a thread-dictionary entry in `Lifecycle/SelectionInputScope.swift` (Swift) and
  `thread_local!` in `selection_inputs.rs` (Rust). A child whose inputs changed queues its
  emission while the depth is above zero, and emits at once when it is zero.
- Where a scope opens and closes. A container membership transaction opens a scope when it
  begins, and a join of an open transaction opens one too (Python and Swift). The scope closes
  when the transaction ends, after the membership gate is released. Rust opens the scope in
  `begin_membership_transaction` and closes it when the transaction finishes. Each container
  gate section (`membership_section`, which replaces `lock(&membership_gate)` in the composite
  and group files) also opens a scope, and it closes when the gate guard drops. An aggregate
  slot replacement opens a scope around its slot lock: C# in each `OnConstruct`, Python in
  `_replace_slots`, TypeScript in `replaceAggregateSlots`, and Swift in
  `AggregateParent.withTransaction`. In Rust the aggregate reaches the scope through its
  transaction.
- Why the outermost close emits. The scope is per thread and counts nesting. A notification
  queued by an inner container change therefore runs only when the outermost change on the
  thread has ended, so it never runs under any container's gate, including a gate held by an
  enclosing call.
- Teardown. Each flavor completes its selection subject at teardown and never disposes it. The
  Python flavor disposed the subject before this ADR, so a racing emission could raise
  `DisposedException`. It now completes the subject, as the other flavors do, and a racing
  emission on a completed subject is a silent no-op.

### 2.5 Conformance

`CVM-011` (chapter 12 §7) pins four cases on a composite with two constructed children:

1. `a.select()` notifies both `a.SelectCommand` and `a.DeselectCommand`, and each subscriber
   reads the new `CanExecute`.
1. Moving `Current` to the sibling `b` notifies `a.DeselectCommand`.
1. Adding a constructed child `c` notifies `c.SelectCommand`.
1. Removing `c` notifies `c.SelectCommand` again.

It pins a fifth property for the notifications of cases 3 and 4: the subscriber runs with no
container membership change open. C#, Python and Swift read the composite's count from a second
thread while the subscriber runs, and the read completes. Rust starts a membership change of
the composite from a second thread, and it is admitted. TypeScript starts a second `add` from
the subscriber, and it is admitted. A notification that ran under the gate would block the
read, or refuse the change.

Each flavor carries a marker for `CVM-011`. Each subscriber reads `CanExecute` inside its
notification handler.

## 3. Consequences

- A bound control of `SelectCommand` or `DeselectCommand` now refreshes after a selection
  change, a move of `Current`, and a container add or remove. Only the notifications are new.
  The predicate values are unchanged. The status-driven notifications of all five commands
  are unchanged.
- The public API does not change. Each flavor adds only private members.
- A notification of a container change runs when that change has ended, before the mutating
  call returns. It does not run inside the change, so a subscriber sees the committed
  membership, and no container lock is held while it runs. The cost is one scope count per
  membership transaction or gate section, and one queue entry per changed child.
- A subscriber that throws no longer rolls back the change it was notified of. The notification
  runs after the change has committed, so the exception reaches the caller of the mutating call
  with the change in place. The first version of this ADR notified inside the change, so the
  same exception was handled by its rollback. The deferred form is the one that is kept.
- Every `Parent` write of a container is inside a scope. The write sites are the membership
  transactions, the Rust membership sections, the aggregate slot replacements, and the link
  writes of the transfer commit and rollback. The container needs no publication step per write
  site, so the earlier residual, which needed about forty such steps per flavor, is gone. A link
  write made outside every scope emits at once. The `CVM-011` probes catch a write that emits
  under a gate.

## 4. Rejected alternatives

- Emit from each container's publication step. That needs a call on every add, remove,
  transfer, clear and population path in each flavor. A missed path would keep the stale
  state silently, and each path would need its own test. The scope of §2.4 opens once per
  membership change instead, so no call is needed per path.
- Emit at the link write, under the membership gate. This was the first version of this ADR. A
  subscriber then ran under the gate, and another thread's read of the container waited for it.
  In Rust the gate is a non-reentrant mutex, which chapter 06 §4.3 forbids consumer code to
  hold, so a subscriber that reached a gate section on the same thread would block.
- Queue per container and flush at that container's own end. A flush of one container can run
  inside another container's section, so a subscriber could run under the outer gate. A
  per-thread outermost close runs only after every section on the thread has ended.
- Dispatch the notification through the dispatcher. A subscriber would run after the membership
  call returned, and `CVM-011` requires the notification before the call returns.
- Add a `Message` variant for the selection inputs in Rust. `Message` is public and has no
  `#[non_exhaustive]`, so the variant would break the public API.
- Subscribe the commands to the parent's `OnCurrentChanged` stream. That stream does not cover
  a link write, and the subscription would have to outlive the link.
- Make the `Parent` link observable through `PropertyChangedMessage`. Chapter 05 §6.1 forbids
  it, and it would add hub traffic to every link write.
- Raise `CanExecuteChanged` with the imperative call of chapter 04 §4.3 at each link write
  and each `IsCurrent` publication. That works, but chapter 04 §4.2 prefers a trigger when the
  change has an observable source, and `IsCurrent` has one. A single trigger wiring in all
  five flavors is simpler to audit.
- Give all five built-in commands the selection trigger. The other three predicates do not read
  the selection inputs, and the issue requires their notifications to stay as they are.
