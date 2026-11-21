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
- It fires after the child's own state guard, and after its link lock, are released
  (chapter 02 §2.4). No consumer callback runs under those locks.
- It does not fire once the child's teardown has begun. C#, Python and TypeScript check the
  same teardown flag that the status trigger checks. Swift checks its teardown flags and that
  `Status` is not `Disposed`. Rust checks that `Status` is not `Disposed`. The subject is
  completed at teardown.
- The notification reaches subscribers through the existing `CanExecuteChanged` channel. It
  adds no `PropertyChangedMessage` and no `ConstructionStatusChangedMessage`.

### 2.4 How each flavor carries the trigger

- C#, Python and TypeScript keep a private selection subject beside the status subject. Both
  commands take it as a second trigger. C# checks the disposal flag under the lifecycle gate
  and emits outside it. The subject is completed at teardown and never disposed, so an
  emission that races teardown is a silent no-op, not a fault on a disposed subject.
- Swift keeps a private `VMxConcurrentSubject` beside the status subject (ADR-0174). A
  composite thread sends it, and `PassthroughSubject` is not designed for concurrent sends.
  The two commands take it as a second trigger.
- Rust keeps a private `MessageHub` in each component core. It carries a `Message::Custom`
  named `selection_inputs`. The public hub is not used, and `Message` gets no new variant.
  `Message` is public and has no `#[non_exhaustive]` attribute, so a new variant would be a
  breaking change. Containers build their select and deselect commands through
  `ComponentCommands::with_liveness`, so containers take the same trigger.

### 2.5 Conformance

`CVM-011` (chapter 12 §7) pins four cases on a composite with two constructed children:

1. `a.select()` notifies both `a.SelectCommand` and `a.DeselectCommand`, and each subscriber
   reads the new `CanExecute`.
1. Moving `Current` to the sibling `b` notifies `a.DeselectCommand`.
1. Adding a constructed child `c` notifies `c.SelectCommand`.
1. Removing `c` notifies `c.SelectCommand` again.

Each flavor carries a marker for `CVM-011`. Each subscriber reads `CanExecute` inside its
notification handler.

## 3. Consequences

- A bound control of `SelectCommand` or `DeselectCommand` now refreshes after a selection
  change, a move of `Current`, and a container add or remove. Only the notifications are new.
  The predicate values are unchanged. The status-driven notifications of all five commands
  are unchanged.
- The public API does not change. Each flavor adds only private members.
- A container writes the `Parent` link inside its own membership section. That section is
  the container's gate in C# and Python, and the composite's membership lock in the other
  flavors. So the link notification can run while that container section is still held, and
  a consumer's `CanExecuteChanged` handler can run there. The container's own
  `CollectionChanged` publication still runs after the section. Chapter 06 §4.3 rule 1
  covers the selection paths, not the link write. Removing this residual means moving the
  link notification to each container's publication step, which touches about forty write
  sites per flavor. That change is not made here.

## 4. Rejected alternatives

- Emit from each container's publication step. That needs a call on every add, remove,
  transfer, clear and population path in each flavor. A missed path would keep the stale
  state silently, and each path would need its own test.
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
