# 12 — Conformance test catalog

This document enumerates every stable conformance test identifier in the form
`XXX-NNN`. Every language flavor MUST implement a passing test for each ID in its
`langs/<lang>/tests/conformance/` directory before it can be marked stable. CI
verifies this via `tools/check-conformance-coverage.py`.

## 1. Identifier prefixes

| Prefix      | Area                                                 | File                                          |
| ----------- | ---------------------------------------------------- | --------------------------------------------- |
| `LIFE-NNN`  | Lifecycle state machine                              | `02-lifecycle.md`                             |
| `DISP-NNN`  | Cross-cutting disposal invariant                     | `01-concepts.md`                              |
| `HUB-NNN`   | Message hub                                          | `03-messages.md`                              |
| `PROP-NNN`  | Property change notifications                        | `03-messages.md`                              |
| `CMD-NNN`   | Commands                                             | `04-commands.md`                              |
| `CVM-NNN`   | ComponentVM (incl. modeled, readonly)                | `05-component-vm.md`                          |
| `COMP-NNN`  | CompositeVM                                          | `06-composite-vm.md`                          |
| `GRP-NNN`   | GroupVM                                              | `07-group-vm.md`                              |
| `AGG-NNN`   | AggregateVM                                          | `08-aggregate-vm.md`                          |
| `FWD-NNN`   | Forwarding decorators                                | `09-forwarding.md`                            |
| `BLD-NNN`   | Builders                                             | `10-builders.md`                              |
| `THR-NNN`   | Threading & schedulers                               | `11-threading.md`                             |
| `UTIL-NNN`  | Tree utilities (spec v1.1)                           | `13-tree-utilities.md`                        |
| `CAP-NNN`   | Capability micro-interfaces                          | `14-capabilities.md`                          |
| `NULL-NNN`  | Null-object service variants                         | `03-messages.md` + `11-threading.md`          |
| `DPROP-NNN` | Derived properties                                   | `15-derived-properties.md`                    |
| `CMDD-NNN`  | Command decorators (spec v2.0)                       | `04-commands.md`                              |
| `NOTIF-NNN` | Notification sub-package (hub v2.0; render VMs v2.1) | `16-notifications.md`                         |
| `EXP-NNN`   | Expand / collapse state                              | `05-component-vm.md` + `13-tree-utilities.md` |
| `LOC-NNN`   | Localization hooks                                   | `17-localization.md`                          |
| `COL-NNN`   | Collection primitives (spec v2.1)                    | `21-collections.md`                           |
| `AGCH-NNN`  | Dynamic aggregate change stream (spec v3.18)         | `21-collections.md`                           |
| `SRCH-NNN`  | SearchableState source reactivity (spec v3.19)       | `06-composite-vm.md`                          |
| `HIER-NNN`  | HierarchicalVM (recursive tree VM, spec v2.1)        | `18-hierarchical-vm.md`                       |
| `DIA-NNN`   | IDialogService (host modal interactions, v2.1)       | `19-dialogs.md`                               |
| `FORM-NNN`  | FormVM (snapshot/revert lifecycle, v2.1)             | `20-form-vm.md`                               |
| `DISC-NNN`  | DiscriminatorVM (single active-key coordinator)      | `22-discriminator-vm.md`                      |
| `ARES-NNN`  | AsyncResourceVM (single async value, spec v3.20)     | `23-async-resource-vm.md`                     |
| `THEME-NNN` | Theme as a VM concern (scenario contract, v2.4)      | `proposals/2026-06-02-theme-vm-scenario.md`   |

Each source spec file (e.g., `02-lifecycle.md`) carries a `## Conformance` section
listing its applicable ID range. When adding a new ID, update both the catalog (here)
and the source spec's `## Conformance` section.

## 2. Reading entries

Each entry below follows Given/When/Then. Implementers map Given to test setup, When
to the operation under test, and Then to assertions.

### 2.1 Notation conventions

Within Given/When/Then prose:

- `Status == Constructed` is a state assertion (equality).
- `Status = Constructed` (single `=`) appears only as the *value* of a
  `ConstructionStatusChangedMessage` — i.e., shorthand for "the message whose `Status`
  field equals `Constructed`".

Type and method names follow the spec convention (PascalCase for types/properties/builder
methods; lowercase for primitive operations like `construct()` / `select()`). Each
language flavor adapts to its native conventions per ADR-0006.

Where pseudo-lambdas appear in Given/When/Then (e.g., `m => …`), they are illustrative —
each language flavor uses its native syntax.

______________________________________________________________________

## 3. Lifecycle (`LIFE-NNN`)

### LIFE-001 — construct from Destructed transitions through Constructing to Constructed

**Given** a freshly built VM in state `Destructed`
**And** a subscriber to the hub filtered on `ConstructionStatusChangedMessage`
**When** `construct()` is called
**Then** the subscriber observes exactly two messages, with `Status` values
`Constructing` then `Constructed` in that order
**And** `vm.IsConstructed` is true after `construct()` returns

### LIFE-002 — destruct from Constructed transitions through Destructing to Destructed

**Given** a VM in state `Constructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `destruct()` is called
**Then** the subscriber observes exactly two messages with `Status` values
`Destructing` then `Destructed`
**And** `vm.IsConstructed` is false after `destruct()` returns

### LIFE-003 — reconstruct emits the full Destruct then Construct sequence

**Given** a VM in state `Constructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `reconstruct()` is called
**Then** the subscriber observes exactly four messages with `Status` values
`Destructing`, `Destructed`, `Constructing`, `Constructed`, in that order

### LIFE-004 — dispose transitions to Disposed from any state

**Given** a VM in any state ∈ `{Destructed, Constructing, Constructed, Destructing}`
**When** `dispose()` is called
**Then** `vm.Status` equals `Disposed`
**And** a `ConstructionStatusChangedMessage` with `Status = Disposed` is observed
on the hub

### LIFE-005 — construct from Disposed raises

**Given** a VM in state `Disposed`
**When** `construct()` is called
**Then** a `StatusTransitionError` / `StatusTransitionException` is raised
**And** the exception message contains the current state ("Disposed") and the
attempted operation ("construct")

### LIFE-006 — destruct from Disposed raises

**Given** a VM in state `Disposed`
**When** `destruct()` is called
**Then** a `StatusTransitionError` / `StatusTransitionException` is raised
**And** the exception message contains the current state ("Disposed") and the
attempted operation ("destruct")

### LIFE-007 — IsConstructed equals Status == Constructed

**Given** a VM in any state
**When** `vm.IsConstructed` is read
**Then** the value equals `(vm.Status == Constructed)`

### LIFE-008 — Concurrent operation while transitioning raises

**Given** a VM whose `construct()` or `destruct()` is in progress (state `Constructing` or
`Destructing`, has not yet reached the corresponding terminal state)
**When** the same operation is invoked again concurrently
**Then** the second call raises `StatusTransitionError` / `StatusTransitionException`

### LIFE-009 — construct from Constructed is idempotent (no-op)

**Given** a VM in state `Constructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `construct()` is called
**Then** the subscriber observes NO new messages
**And** `vm.Status` remains `Constructed`

### LIFE-010 — destruct from Destructed is idempotent (no-op)

**Given** a VM in state `Destructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `destruct()` is called
**Then** the subscriber observes NO new messages
**And** `vm.Status` remains `Destructed`

### LIFE-011 — Lifecycle transition table matches fixture

**Given** the JSON fixture `spec/fixtures/lifecycle-transitions.json`
**When** each row is exercised against a freshly-built VM, where rows with `from == Constructing`
or `from == Destructing` are reached by starting an asynchronous `construct()` or `destruct()`
and pausing the dispatcher mid-transition (e.g., via a test scheduler or controllable hook)
**Then** rows with `legal: true` complete with the expected `to_final` state
**And** rows with `legal: false` raise `StatusTransitionError` / `StatusTransitionException`
**And** the fixture's `to_intermediate` field captures only the first transient state of
non-trivial transitions; the full `reconstruct` sequence is normatively defined in
`02-lifecycle.md` and tested by LIFE-003

### LIFE-012 — dispose from Disposed emits no message

**Given** a VM in state `Disposed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `dispose()` is called
**Then** the subscriber observes NO new messages
**And** `vm.Status` remains `Disposed`

### LIFE-013 — dispose on a parent disposes every child depth-first

**Given** a container VM (`CompositeVM<VM>`, `GroupVM<VM>`, or `AggregateVMN<…>`)
in `Constructed` state with all children/component slots themselves `Constructed`,
each child itself a container with grand-children all `Constructed`
**When** `parent.dispose()` is called
**Then** when it returns, every child and every grand-child has `Status == Disposed`
**And** the disposal order is depth-first (grand-children before children before parent)
**And** if one child or parent disposal hook fails, all later siblings and the
parent's mandatory teardown still complete before the first failure is
propagated in flavors with a throwing/result-based disposal surface

### LIFE-014 — A throwing construct/destruct hook rolls Status back (transactional)

**Given** a VM whose `OnConstruct` (`_on_construct` / `_onConstruct`) hook raises
**When** `construct()` is called
**Then** the call propagates the hook's exception
**And** `vm.Status` is `Destructed` (rolled back from the transient `Constructing`),
not `Constructing`
**And** the VM is recoverable: a subsequent `construct()` with a non-throwing hook
reaches `Constructed`
**And** symmetrically, for a VM in `Constructed` whose `OnDestruct` hook raises,
`destruct()` propagates the exception, `vm.Status` rolls back to `Constructed`
(not `Destructing`), and a subsequent `destruct()` with a non-throwing hook reaches
`Destructed`

> Normatively defined in `02-lifecycle.md §2.5`.

______________________________________________________________________

## 4. Message hub (`HUB-NNN`)

### HUB-001 — Send delivers to current subscribers

**Given** an `IMessageHub` with one subscriber to `hub.Messages`
**When** `hub.Send(message)` is called
**Then** the subscriber receives `message` synchronously before `Send` returns

### HUB-002 — Late subscribers do not see prior messages

**Given** an `IMessageHub`
**When** `hub.Send(messageA)` is called
**And** a subscriber subscribes to `hub.Messages`
**And** `hub.Send(messageB)` is called
**Then** the subscriber observes only `messageB`

### HUB-003 — Single-producer FIFO order

**Given** an `IMessageHub` with one subscriber
**When** the producer calls `hub.Send(A)`, `hub.Send(B)`, `hub.Send(C)` from the
same thread in that order
**Then** the subscriber observes `A`, `B`, `C` in that order

### HUB-004 — Subscriber dispose during emit does not crash

**Given** an `IMessageHub` with one subscriber whose handler disposes the
subscription on the first message
**When** `hub.Send(A)` then `hub.Send(B)`
**Then** the subscriber observes only `A`
**And** no exception is raised by the hub

### HUB-005 — Multiple subscribers each observe every post-subscribe message

**Given** an `IMessageHub` with N subscribers (N ≥ 2)
**When** the producer calls `hub.Send(message)` once
**Then** every subscriber observes `message` exactly once

### HUB-006 — Hub matches message-ordering fixture

**Given** the JSON fixture `spec/fixtures/message-ordering.json`
**When** every scenario in the fixture is exercised against a fresh hub
**Then** the observed messages match each scenario's expected-output field:

- single-subscriber scenarios use `expected_observed` (a list of message identifiers)
- the `multiple-subscribers-same-message` scenario uses `expected_observed_per_subscriber`
  (each of the `subscriber_count` subscribers observes that same list)
- the `unsubscribe-during-emit` scenario uses `expected_observed` (the surviving
  subscription's observed list)

### HUB-007 — Subscriber handler that raises does not break the hub

**Given** an `IMessageHub` with subscriber A whose handler raises on every message
**And** subscriber B whose handler records every message
**When** `hub.Send(message1)` then `hub.Send(message2)` is called
**Then** subscriber B observes both `message1` and `message2`
**And** no exception propagates to the caller of `Send`

### HUB-008 — Nested transactions defer and preserve every message

**Given** a hub with a current subscriber
**When** an outer transaction sends `A`, an inner transaction sends `B`, and the
outer transaction then sends `C`
**Then** the subscriber observes nothing until the outer transaction exits
**And** it then observes `A`, `B`, `C`, each exactly once

### HUB-009 — Transaction error drains then rethrows the original error

**Given** a hub with a current subscriber
**When** a transaction sends `A` and then raises a sentinel error
**Then** the subscriber observes `A` before control returns to the caller
**And** the same sentinel error is rethrown

### HUB-010 — Re-entrant send joins the iterative FIFO drain

**Given** two current subscribers and subscriber A sends `B` while handling `A`
**When** the producer sends `A`
**Then** both subscribers observe `A` before either observes `B`
**And** the outer send returns only after both have observed `B`
**And** delivery uses an iterative queue rather than recursive dispatch

### HUB-011 — Subscriber failure does not abort a transaction drain

**Given** subscriber A raises for every message and subscriber B records messages
**When** a transaction sends `A` and `B`
**Then** subscriber B observes both messages in order
**And** no subscriber error escapes the transaction

### HUB-012 — Disposing during a transaction drops queued messages

**Given** a hub with a current subscriber
**When** a transaction sends `A`, disposes the hub, and sends `B`
**Then** neither queued message is delivered
**And** the stream completes and future sends remain no-ops

### HUB-013 — Ordinary sends remain synchronous outside transactions

**Given** a hub with a current subscriber and no active transaction
**When** the producer calls `Send(A)`
**Then** the subscriber observes `A` before `Send` returns
**And** no transaction callback or explicit flush is required

______________________________________________________________________

## 5. Property change and selected-state subscription (`PROP-NNN`, `SUBV-NNN`)

### PROP-001 — Setting a property to a different value publishes PropertyChangedMessage

**Given** a modeled `ComponentVM<M>` with `Model = m1`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2` where `m2 != m1`
**Then** the subscriber observes exactly one `PropertyChangedMessage` with
`PropertyName = "Model"` and `Sender = vm`

### PROP-002 — Setting a property to the same value does NOT publish

**Given** a modeled `ComponentVM<M>` with `Model = m1`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m1` (same instance)
**Then** the subscriber observes zero `PropertyChangedMessage` emissions

### PROP-003 — Sender identity equals the VM instance

**Given** a modeled `ComponentVM<M>` named "vm1"
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2`
**Then** the observed message's `Sender` is identical to (referentially equal to)
the `vm` instance

### PROP-004 — PropertyName equals the property's name

**Given** a modeled `ComponentVM<M>` with `Name = "n1"`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2`
**Then** the observed message's `PropertyName` is exactly `"Model"`
**And** the message's `SenderName` is `"n1"`

### SUBV-001 — Fixed-source selection uses initial/current/previous values and default equality

**Given** one source VM and another sender share a message hub
**And** `subscribeValue` selects an initial value from the source with immediate
delivery enabled
**When** the hub delivers non-property messages, property messages from the other
sender, and property messages from the source whose selected values are unchanged
and then changed twice
**Then** the initial callback receives `(initial, initial)` before attachment
**And** messages outside the fixed source's property-message channel do not
evaluate the selector
**And** default equality suppresses the unchanged selected value
**And** the changed callbacks receive `(first, initial)` and `(second, first)` in
order

### SUBV-002 — Custom equality evaluates selector and comparator exactly once per matching message

**Given** a `subscribeValue` bridge with a custom equality function
**When** the source publishes matching property messages whose selected values
are custom-equal and then custom-unequal to the retained value
**Then** the selector is evaluated exactly once per matching message
**And** custom equality is evaluated exactly once per successfully selected value
**And** only the custom-unequal value invokes the callback
**And** the custom-comparator shape does not require the selected type to support
the flavor's default equality

### SUBV-003 — Re-entrant delivery, batch suppression, and disposal are deterministic

**Given** a `subscribeValue` callback that changes its fixed source re-entrantly
**When** a source property message invokes that callback
**Then** the re-entrant message is delivered later in the hub's iterative FIFO
drain and compares against the baseline updated before the callback
**And** a lossless hub batch whose messages all observe one final selected value
invokes the callback once and equality-suppresses the remaining deliveries
**And** disposing the returned handle prevents all later selector, equality, and
callback work
**And** disposal during a callback allows that callback to finish but prevents
subsequent queued or re-entrant delivery to the bridge

### SUBV-004 — Setup failures propagate and delivery failures remain subscriber-isolated

**Given** a `subscribeValue` bridge whose selector, equality function, or callback
can fail
**When** the initial selector or immediate callback fails during setup
**Then** that failure propagates synchronously and no subscription is attached
**When** selector, equality, or callback work fails during message delivery
**Then** the existing `HUB-007` subscriber-error route isolates the failure from
the hub and other subscribers
**And** a delivery callback failure retains the already-updated selected baseline
for the next matching message

______________________________________________________________________

## 6. Commands (`CMD-NNN`)

### CMD-001 — execute invokes the configured task

**Given** a `RelayCommand` built with `.Task(t)` where `t` is a no-op recorder
**When** `command.Execute()` is called
**Then** `t` is invoked exactly once

### CMD-002 — can_execute with no predicate returns true

**Given** a `RelayCommand` built without `.Predicate(...)`
**When** `command.CanExecute()` is called
**Then** it returns `true`

### CMD-003 — can_execute returns the predicate result

**Given** a `RelayCommand` built with `.Predicate(() => false)`
**When** `command.CanExecute()` is called
**Then** it returns `false`

### CMD-004 — Trigger emission fires CanExecuteChanged

**Given** a `RelayCommand` built with a single trigger `Subject<Unit>`
**And** a subscriber to `CanExecuteChanged`
**When** the trigger emits one `Unit`
**Then** the subscriber observes exactly one `CanExecuteChanged` fire

### CMD-005 — Parameterized variant passes parameter

**Given** a `RelayCommand<int>` built with `.Task(p => recorder.Record(p))`
**When** `command.Execute(42)` is called
**Then** the recorder receives the value `42`

### CMD-006 — execute with null task is a no-op

**Given** a `RelayCommand` built without `.Task(...)`
**When** `command.Execute()` is called
**Then** no exception is raised
**And** no observable side effect occurs

### CMD-007 — Command truth-table matches fixture

**Given** the JSON fixture `spec/fixtures/command-truthtable.json`
**When** every row is exercised against a freshly built `RelayCommand`
**Then** the row's expected `can_execute`, `execute_invokes_task`, and
`can_execute_changed_fires` results all hold

### CMD-008 — `Confirm(delegate)` is equivalent to explicit `ConfirmationDecoratorCommand`

**Given** an `ICommand` `cmd`
**And** a `confirm` delegate of shape `() -> Task<bool>`
**When** `cmd.Confirm(confirm)` is called
**Then** the returned command's `CanExecute` and `Execute` graph is identical to
`new ConfirmationDecoratorCommand(cmd, confirm)` — i.e., `CanExecute` delegates to
`cmd.CanExecute`, and `Execute` invokes `confirm()` then `cmd.Execute()` only when
`confirm` resolves to `true`

### CMD-009 — `PrecedeWith(other)` is equivalent to `CompositeCommand(other, receiver)`

**Given** two commands `cmd` and `other`
**When** `cmd.PrecedeWith(other)` is called
**Then** the returned command is equivalent to `new CompositeCommand(other, cmd)` —
i.e., `other.Execute()` is invoked before `cmd.Execute()` when both are executable

### CMD-010 — `SucceedWith(other)` is equivalent to `CompositeCommand(receiver, other)`

**Given** two commands `cmd` and `other`
**When** `cmd.SucceedWith(other)` is called
**Then** the returned command is equivalent to `new CompositeCommand(cmd, other)` —
i.e., `cmd.Execute()` is invoked before `other.Execute()` when both are executable

### CMD-011 — `WrapWith(predicate?, pre?, post?)` is equivalent to explicit `DecoratorCommand`

**Given** an `ICommand` `cmd`
**And** optional extra predicate, pre-action, and post-action arguments
**When** `cmd.WrapWith(predicate, pre, post)` is called
**Then** the returned command is equivalent to
`new DecoratorCommand(cmd, pre, post, predicate)` (the shipped C# / Python
constructor takes `(inner, preExecute, postExecute, extraPredicate)`) —
including the case where all three arguments are null/absent, which yields a
transparent decorator

### CMD-012 — `AsyncRelayCommand.Cancel()` cancels an in-flight async task, non-throwing by default

**Given** an `AsyncRelayCommand` built with a long-running cancellable async task
**And** the task has started (an execution is in flight)
**When** `command.Cancel()` is called and the awaited `ExecuteAsync` completes
**Then** the awaited execution completes **without** surfacing a cancellation
exception (non-throwing default, aligned with `DIA-007`)
**And** the command returns to a non-executing state — `IsExecuting` is `false`
and `CanExecute` returns `true`
**And** while the task was in flight `CanExecute` returned `false` (the command
cannot double-run)

> Spec: `04-commands.md §10`, ADR-0056, ADR-0076. Full-parity
> (C#/Python/TypeScript/Swift/Rust).

### CMD-013 — disposed relay commands are inert

**Given** a `RelayCommand` or parameterized `RelayCommand<T>` built with a task
**And** the command has been disposed
**When** `CanExecute` is queried
**Then** it returns `false`
**And when** `Execute` is invoked
**Then** the configured task is not invoked and no exception is raised

> Spec: `04-commands.md §5`, ADR-0068.

### CMD-014 — imperative raise emits exactly once without invoking delegates

**Given** a live `RelayCommand` with a predicate and task
**And** a subscriber to `CanExecuteChanged`
**When** the flavor-idiomatic imperative raise method is called once
**Then** the subscriber observes exactly one notification
**And** neither the predicate nor the task is invoked

### CMD-015 — repeated imperative raises and triggers are additive

**Given** a live `RelayCommand` with one trigger
**And** a subscriber to `CanExecuteChanged`
**When** the imperative raise method is called twice and the trigger emits once
**Then** the subscriber observes exactly three notifications

### CMD-016 — imperative raise after disposal is inert

**Given** disposed synchronous, parameterized, and async relay commands
**When** the imperative raise method is called on each command
**Then** no notification is published and no exception is raised

### CMD-017 — parameterized relay supports imperative raise

**Given** a live parameterized relay command
**And** a subscriber to `CanExecuteChanged`
**When** the imperative raise method is called once
**Then** the subscriber observes exactly one notification

### CMD-018 — async relay supports imperative raise while idle

**Given** a live idle `AsyncRelayCommand`
**And** a subscriber to `CanExecuteChanged`
**When** the imperative raise method is called once
**Then** the subscriber observes exactly one notification
**And** no execution starts

### CMD-019 — async in-flight imperative raise is additive

**Given** an `AsyncRelayCommand` whose execution is in flight
**And** a subscriber that observed the execution-start notification
**When** the imperative raise method is called once and the execution completes
**Then** the subscriber observes exactly three notifications in total: start,
imperative raise, and completion

> Spec: `04-commands.md §4.3` and §10.2, ADR-0086.

______________________________________________________________________

## 7. ComponentVM (`CVM-NNN`)

### CVM-001 — Construct emits ConstructionStatusChangedMessage(Constructed)

**Given** a `ComponentVM<M>` in `Destructed` state
**And** a subscriber to the hub filtered on `ConstructionStatusChangedMessage`
**When** `construct()` is called
**Then** the subscriber observes exactly two messages, with `Status` values
`Constructing` then `Constructed` in that order
**And** `vm.IsConstructed` is true after the call

### CVM-002 — Modeled component fires PropertyChanged("Model") on set

**Given** a modeled `ComponentVM<M>` with `Model = m1`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2` where `m2 != m1`
**Then** the subscriber observes a message with `PropertyName = "Model"`

### CVM-003 — ReadonlyComponentVM has no Model setter

**Given** a `ReadonlyComponentVM<M>` built with `Model(m1)`
**When** the API surface of the VM is inspected
**Then** there is no public way to set `Model` (no setter property, no method)
**And** `vm.Model == m1`

### CVM-004 — ModeledHint recomputes when Model changes

**Given** a modeled `ComponentVM<M>` built with a `ModeledHinter` that returns `"hint:" + m.Id`
**And** `Model = m1` where `m1.Id == 7`
**When** `vm.Model = m2` where `m2.Id == 8`
**Then** `vm.ModeledHint == "hint:8"`
**And** a `PropertyChangedMessage("ModeledHint")` is observed on the hub

### CVM-005 — Name and Hint are immutable post-construction

**Given** a `ComponentVM<M>` built with `Name("orig")` and `Hint("h")`
**When** the API surface is inspected
**Then** there is no public setter for `Name` or `Hint`
**And** `vm.Name == "orig"` and `vm.Hint == "h"` for the VM's lifetime

### CVM-006 — SelectCommand can_execute reflects selection state

**Given** a `ComponentVM<M>` in `Constructed` state whose parent has `Current = null`
**When** `SelectCommand.CanExecute()` is called
**Then** it returns `true`
**And** after `vm.select()`, `SelectCommand.CanExecute()` returns `false`

### CVM-007 — Notification helper emits both channels exactly once

**Given** a component subclass with an equality-gated settable property
**And** subscribers recording both the shared hub and VM-local property-change
channels
**When** the setter assigns a different value and calls the dual-channel helper
once
**Then** both subscribers can read the assigned value
**And** exactly one `PropertyChangedMessage` and one VM-local notification are
observed
**And** for an ordinary top-level hub send the hub observer runs before the
local observer
**And** both notifications use the flavor-idiomatic public property name
**And** a hub transaction may defer its observer until after the local observer
while retaining hub-enqueue-before-local invocation order
**And** if the hub observer disposes the VM re-entrantly, the admitted local
notification still occurs before its local surface completes

### CVM-008 — Notification helper leaves equality to the caller

**Given** the equality-gated property from CVM-007
**When** the setter receives its current value
**Then** the caller does not invoke the helper
**And** neither the hub nor the VM-local channel emits

### CVM-009 — Notification helper is inert after disposal

**Given** a disposed component
**When** its dual-channel property notification helper is invoked
**Then** neither the hub nor the VM-local channel emits

### CVM-010 — Modeled components explicitly republish the retained model

**Given** a writable modeled component with a reference-shaped model, modeled
hinter, model-changed callback where the flavor exposes one, and subscribers to
the hub and local property-change channels
**When** its explicit model-republish operation is called
**Then** the exact model reference/value and observable modeled hint value are
retained
**And** republish does not run equality, assignment, hinter, or model-changed
callback work
**And** exactly one flavor-idiomatic model `PropertyChangedMessage` and one local
model notification are observed in ordinary hub-before-local order
**And** a read-only modeled component exposes the same publication operation
without exposing model replacement
**And** a forwarding modeled component delegates to the wrapped sender, hub,
local stream, and disposal boundary
**And** a null/default hub remains safe while the local channel emits once
**And** a call beginning after disposal emits on neither channel
**And** one guarded re-entrant call contributes a second complete pair through
the existing iterative hub queue without recursive loss
**And** ordinary equal assignment remains silent while ordinary unequal
assignment retains its existing behavior

______________________________________________________________________

## 8. CompositeVM (`COMP-NNN`)

### COMP-001 — Add emits CollectionChanged(action=Add)

**Given** an empty `CompositeVM<VM>` in `Constructed` state
**And** a subscriber to `CollectionChanged`
**When** `composite.Add(vm)` is called
**Then** the subscriber observes a `CollectionChanged` event with
`action == Add`, `newItems == [vm]`, `newIndex == 0`

### COMP-002 — Remove emits CollectionChanged(action=Remove)

**Given** a `CompositeVM<VM>` containing one VM
**And** a subscriber to `CollectionChanged`
**When** `composite.Remove(vm)` is called
**Then** the subscriber observes a `CollectionChanged` event with
`action == Remove`, `oldItems == [vm]`, `oldIndex == 0`

### COMP-003 — select_component sets Current

**Given** a `CompositeVM<VM>` containing `vm` in `Constructed` state with
`Current == null`
**When** `composite.select_component(vm)` is called
**Then** `composite.Current == vm`
**And** `vm.IsCurrent == true`
**And** a `PropertyChangedMessage("Current")` is observed on the hub
**And** a `PropertyChangedMessage("IsCurrent")` is observed on the hub with
`Sender == vm`

### COMP-004 — Construct waits until all children reach Constructed

**Given** a `CompositeVM<VM>` in `Destructed` state with N children all in
`Destructed`
**When** `composite.construct()` is called
**Then** when it returns (or its awaiter resumes), every child has `Status == Constructed`
**And** the composite has `Status == Constructed`

### COMP-005 — Destruct waits until all children reach Destructed

**Given** a `CompositeVM<VM>` in `Constructed` state with N children all in
`Constructed` and `Current = c0`
**When** `composite.destruct()` is called
**Then** when it returns, `composite.Current == null`
**And** every child has `Status == Destructed`
**And** the composite has `Status == Destructed`

### COMP-006 — IsCurrent change on the previously-Current child dispatches on foreground

**Given** a `CompositeVM<VM>` in `Constructed` state with children `[vmA, vmB]` and
`Current = vmA`, built with a dispatcher whose `Foreground` is a `TestScheduler`-equivalent
**And** a subscriber to `PropertyChangedMessage("IsCurrent")` filtered on `Sender == vmA`,
using `ObserveOn(dispatcher.Foreground)`
**When** `composite.Current = vmB` (or `composite.deselect_component(vmA)`)
**Then** the subscriber's handler is invoked on the foreground scheduler with `vmA` as sender

### COMP-007 — Modeled composite maps model factory output to children

**Given** a `CompositeVM<M, VM>` built with `ChildrenModels(() => [m1, m2])` and
`ChildModelToChildViewModel(m => MakeVM(m))`
**When** `composite.construct()` is called
**Then** `composite.Count == 2`
**And** `composite[0].Model == m1` and `composite[1].Model == m2`

### COMP-008 — can_select_component returns false for non-children

**Given** a `CompositeVM<VM>` containing only `vmA`
**And** a foreign `vmB` (not in the composite)
**When** `composite.can_select_component(vmB)` is called
**Then** it returns `false`
**And** `composite.select_component(vmB)` raises

### COMP-009 — Current setter raises when assigned a non-child

**Given** a `CompositeVM<VM>` containing `vmA` in `Constructed` state with `Current == null`
**And** a foreign `vmB` (not in the composite)
**When** `composite.Current = vmB` is attempted
**Then** the operation raises (e.g., `InvalidOperationException` / `ValueError`)
**And** `composite.Current` is still `null`

### COMP-010 — AsyncSelection dispatches Current change via foreground scheduler

**Given** a `CompositeVM<VM>` built with `AsyncSelection(true)` and a dispatcher whose
`Foreground` is a `TestScheduler`-equivalent
**And** the composite contains `vmA` and `Current == null`
**When** `composite.select_component(vmA)` is called
**Then** `composite.Current` does NOT change synchronously
**And** advancing the test scheduler completes the dispatch, making `composite.Current == vmA`
**And** subsequent subscribers to `PropertyChangedMessage("Current")` observe on the foreground scheduler

### COMP-011 — deselect_component raises when vm is not Current

**Given** a `CompositeVM<VM>` containing `vmA` and `vmB`, with `Current == vmA`
**When** `composite.deselect_component(vmB)` is called
**Then** the operation raises
**And** `composite.Current` is still `vmA`

### COMP-012 — AutoConstructOnAdd(true) auto-constructs late children (spec v1.1)

**Given** a `CompositeVM<VM>` built with `.AutoConstructOnAdd(true)` and already in `Constructed` state
**And** `child` is a fresh `IComponentVM` in `Destructed` state
**And** a subscriber to `CollectionChanged`
**When** `composite.Add(child)` is called
**Then** `child.Status == Constructed` BEFORE the `CollectionChanged(Add)` event is observed
**And** when the subscriber receives the event, the child reads as `Constructed`

### COMP-013 — BatchUpdate suppresses per-mutation events and emits one Reset (spec v1.1)

**Given** a `CompositeVM<VM>` in `Constructed` state
**And** a subscriber to `CollectionChanged`
**When** `composite.BatchUpdate()` is entered as `using`/`with`
**And** N (≥1) mutations are applied (Add / Insert / Remove / Clear)
**And** the batch handle is disposed / the context exits
**Then** the subscriber observes exactly ONE `CollectionChanged(action=Reset)` event
**And** the subscriber observes NO per-mutation events from within the batch
**And** the composite's children reflect the post-batch state

______________________________________________________________________

## 9. GroupVM (`GRP-NNN`)

### GRP-001 — Add emits CollectionChanged(action=Add)

**Given** an empty `GroupVM<VM>` in `Constructed` state
**And** a subscriber to `CollectionChanged`
**When** `group.Add(vm)` is called
**Then** the subscriber observes a `CollectionChanged` event with
`action == Add`, `newItems == [vm]`, `newIndex == 0`

### GRP-002 — Group lacks child-navigation and child-selection members

**Given** a `GroupVM<VM>` instance
**When** the API surface is inspected
**Then** there is no `Current` property
**And** there is no `select_component`, `deselect_component`, or `can_select_component` method
**And** `SelectCommand` and `DeselectCommand` ARE present (they operate on the group's own
selection within its parent, not on the children — see `07-group-vm.md`)
**And** `SelectNextCommand` and `SelectPreviousCommand` ARE present (inherited from
the `IComponentVM` baseline) but their predicates always return `false`, since the group
exposes no internal navigation slot

### GRP-003 — Construct waits until all children reach Constructed

**Given** a `GroupVM<VM>` in `Destructed` state with N children in `Destructed`
**When** `group.construct()` is called
**Then** when it returns, every child has `Status == Constructed`
**And** the group has `Status == Constructed`

### GRP-004 — Destruct waits until all children reach Destructed

**Given** a `GroupVM<VM>` in `Constructed` state with N children in `Constructed`
**When** `group.destruct()` is called
**Then** when it returns, every child has `Status == Destructed`
**And** the group has `Status == Destructed`

### GRP-005 — AutoConstructOnAdd(true) auto-constructs late children (spec v1.1)

**Given** a `GroupVM<VM>` built with `.AutoConstructOnAdd(true)` and already in `Constructed` state
**And** `child` is a fresh `IComponentVM` in `Destructed` state
**And** a subscriber to `CollectionChanged`
**When** `group.Add(child)` is called
**Then** `child.Status == Constructed` BEFORE the `CollectionChanged(Add)` event is observed

### GRP-006 — BatchUpdate suppresses per-mutation events and emits one Reset (spec v1.1)

**Given** a `GroupVM<VM>` in `Constructed` state
**And** a subscriber to `CollectionChanged`
**When** `group.BatchUpdate()` is entered as `using`/`with`
**And** N (≥1) mutations are applied (Add / Insert / Remove / Clear)
**And** the batch handle is disposed
**Then** the subscriber observes exactly ONE `CollectionChanged(action=Reset)` event
**And** the subscriber observes NO per-mutation events from within the batch

______________________________________________________________________

## 10. AggregateVM (`AGG-NNN`)

### AGG-001 — Arity-1 ComponentN factory invoked on construct

**Given** an `AggregateVM1<VM1>` in `Destructed` built with `.Component1(() => makeVm1())`
**When** `agg.construct()` is called
**Then** `agg.Component1` is populated with the result of `makeVm1()`
**And** `agg.Component1.Status == Constructed`

### AGG-002 — Arity-2 both components reach Constructed

**Given** an `AggregateVM2<VM1, VM2>` in `Destructed`
**When** `agg.construct()` is called
**Then** when it returns, both `agg.Component1.Status` and `agg.Component2.Status`
equal `Constructed`
**And** the aggregate's `Status == Constructed`

### AGG-003 — Arity-5 all five components reach Constructed before parent

**Given** an `AggregateVM5<VM1..VM5>` in `Destructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage` where
`Sender == agg`
**When** `agg.construct()` is called
**Then** the message with `Status = Constructed` and `Sender == agg` is observed
ONLY AFTER every `ComponentI.Status` has reached `Constructed`

### AGG-004 — ComponentN property change fires on construct

**Given** an `AggregateVM3<VM1, VM2, VM3>` in `Destructed`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `agg.construct()` is called
**Then** three `PropertyChangedMessage` events with `PropertyName ∈ {"Component1", "Component2", "Component3"}` are observed

### AGG-005 — Destruction waits for all children Destructed

**Given** an `AggregateVM2<VM1, VM2>` in `Constructed`
**When** `agg.destruct()` is called
**Then** when it returns, `agg.Component1.Status == Destructed` AND
`agg.Component2.Status == Destructed`
**And** `agg.Status == Destructed`

### AGG-006 — Arity-6 all six components reach Constructed; destruction waits for all

**Given** an `AggregateVM6<VM1, VM2, VM3, VM4, VM5, VM6>` in `Destructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage` where
`Sender == agg`
**When** `agg.construct()` is called
**Then** when it returns, every `ComponentI.Status` (I ∈ {1..6}) equals `Constructed`
**And** the aggregate's `Status == Constructed`
**When** `agg.destruct()` is then called
**Then** when it returns, every `ComponentI.Status` equals `Destructed`
**And** `agg.Status == Destructed`

(Added in spec 2.2.0 per ADR-0034.)

______________________________________________________________________

## 11. Forwarding (`FWD-NNN`)

### FWD-001 — ForwardingComponentVM delegates every member to wrapped

**Given** a concrete no-op subclass of `ForwardingComponentVM<M>` wrapping `inner` (no member overridden)
**When** each public member of the forwarding VM is read or invoked
**Then** the result equals the value/effect of the same member on `inner`

### FWD-002 — Selective override replaces a single behavior

**Given** a subclass of `ForwardingComponentVM<M>` that overrides `Hint` to return
`"OVERRIDE"`
**And** the wrapped VM has `Hint == "inner-hint"`
**When** the forwarding VM's `Hint` is read
**Then** the result is `"OVERRIDE"`
**And** all other members still delegate to the wrapped VM unchanged

### FWD-003 — ForwardingCompositeVM forwards iteration

**Given** a `ForwardingCompositeVM<VM>` wrapping a composite containing `[vm1, vm2]`
**When** the forwarding composite is iterated
**Then** the iteration yields `vm1, vm2` in order

______________________________________________________________________

## 12. Builders (`BLD-NNN`)

### BLD-001 — Setter returns a new builder instance

**Given** a freshly created builder `b1`
**When** `b2 = b1.Name("x")` is called
**Then** `b1` and `b2` are different instances (`b1 is not b2` in Python; reference
inequality in C#)
**And** `b1.Name == null` (or default) while `b2.Name == "x"`

### BLD-002 — Required fields validated on Build

**Given** a builder missing one required field (e.g., no `Services` call)
**When** `.Build()` is called
**Then** a `BuilderValidationError` (Python / TS / Swift) / `BuilderValidationException` (C#) is raised
**And** the exception message identifies which field is missing

### BLD-003 — Repeated identical Build calls produce equivalent VMs

**Given** a fully-configured builder `b`
**When** `vmA = b.Build()` and `vmB = b.Build()` are called
**Then** `vmA` and `vmB` are different instances
**And** `vmA.Name == vmB.Name`, `vmA.Hint == vmB.Hint`, `vmA.Type == vmB.Type`,
and (for modeled variants) `vmA.Model == vmB.Model`

### BLD-004 — Field defaults applied when not set

**Given** a builder configured with only the required fields
**When** `.Build()` is called
**Then** `vm.Hint == ""`, `vm.Parent == null`, `vm.Type ==` the type derived from
the VM class

### BLD-005 — Additive setters retain prior values across repeated calls

**Given** a `RelayCommand.Builder()` `b1`
**And** two distinct observables `o1` and `o2`
**When** `b2 = b1.Triggers(o1)` and `b3 = b2.Triggers(o2)` are called
**Then** `b3.Build().Triggers` contains BOTH `o1` and `o2` (cumulative)
**And** the order matches insertion order (`o1` precedes `o2`)
**And** other (non-additive) setters such as `Name` and `Task` continue to overwrite
on repeated calls per BLD-001's standard semantics

### BLD-006 — Common VM options factories match builder semantics

**Given** the common VM types `ComponentVM`, modeled `ComponentVM<M>`,
`CompositeVM<VM>`, and `GroupVM<VM>`
**When** each type is constructed through its additive positional-options form
(`Create`, `create`, `create(options)`, or Swift `create(_:)`)
**Then** the produced VM has the same observable defaults and field values as the
equivalent fluent builder path
**And** missing required fields are validated through the same
`BuilderValidationError` / `BuilderValidationException` path as `Build()`
**And** where the options type can represent a partial service pair, each
supplied service is retained until normal builder validation, preserving the
builder's validation order and missing-field diagnostic

______________________________________________________________________

## 13. Threading (`THR-NNN`)

### THR-001 — PropertyChanged observed on foreground scheduler

**Given** a modeled `ComponentVM<M>` built with a dispatcher whose `Foreground` is
a `TestScheduler`-equivalent
**And** a subscriber to the hub's `Messages` filtered on `PropertyChangedMessage`
that uses `ObserveOn(dispatcher.Foreground)`
**When** `vm.Model = m2`
**Then** the subscriber's handler is invoked on the foreground scheduler

### THR-002 — Background construct dispatches on background scheduler

**Given** a `ComponentVM<M>` built with `.Background(true)` and a dispatcher whose
`Background` is a `TestScheduler`-equivalent
**When** `construct()` is called
**Then** the construction work is scheduled on `dispatcher.Background`
**And** the test scheduler advancing time advances the construction

### THR-003 — CollectionChanged observed on foreground scheduler

**Given** a `CompositeVM<VM>` built with a foreground `TestScheduler` and a
subscriber to `CollectionChanged` with `ObserveOn(dispatcher.Foreground)`
**When** `composite.Add(vm)` is called
**Then** the subscriber's handler is invoked on the foreground scheduler

### THR-004 — Subscriber observes on chosen scheduler via ObserveOn

**Given** a subscriber to `hub.Messages.ObserveOn(scheduler)` for any scheduler
**When** `hub.Send(message)` is called
**Then** the subscriber's handler is invoked on `scheduler`

______________________________________________________________________

## 14. Tree utilities (`UTIL-NNN`) — spec v1.1

### UTIL-001 — walk yields root then descendants in DFS pre-order

**Given** a tree:

```
root: CompositeVM
  ├── a: ComponentVM
  └── b: CompositeVM
        ├── b1: ComponentVM
        └── b2: ComponentVM
```

**When** `list(walk(root))` is materialized
**Then** the sequence is `[root, a, b, b1, b2]`

### UTIL-002 — walk skips empty aggregate slots

**Given** an `AggregateVM3` with `Component1` populated, `Component2 == null`, `Component3` populated
**When** `list(walk(agg))` is materialized
**Then** the sequence contains `agg`, `agg.Component1`, `agg.Component3`
**And** the sequence does NOT contain `null` / `None` / any entry for the empty slot

### UTIL-003 — find returns first matching node and short-circuits

**Given** a tree as in UTIL-001
**And** a predicate `vm => vm.Name == "b1"`
**When** `find(root, predicate)` is called
**Then** the result is `b1`
**And** the predicate was invoked at most for `root`, `a`, `b`, `b1` — never for `b2`

______________________________________________________________________

## 15. Capability micro-interfaces (`CAP-NNN`) — spec v2.0 / v2.1

Each CAP-NNN test verifies (a) the capability interface is present in the
flavor's public surface with the documented signature, and (b) a fixture class
implementing the capability satisfies the per-interface semantic contract.

### CAP-001 — ISelectable contract

**Given** a fixture class `F` that implements `ISelectable` with
`can_select() -> true` and `select()` recording one invocation
**When** `f.select()` is called after asserting `f.can_select()` returns true
**Then** the recorder has exactly one invocation

### CAP-002 — IDeselectable contract

**Given** a fixture class `F` that implements `IDeselectable` with
`can_deselect() -> true` and `deselect()` recording one invocation
**When** `f.deselect()` is called after asserting `f.can_deselect()` returns true
**Then** the recorder has exactly one invocation

### CAP-003 — ISelectionTogglable contract

**Given** a fixture class `F` that implements `ISelectionTogglable` with
`can_toggle_selection() -> true` and `toggle_selection()` flipping an internal
`selected` flag
**When** `f.toggle_selection()` is called twice, asserting `can_toggle_selection()` first
**Then** the internal flag has returned to its initial value

### CAP-004 — IExpandable contract

**Given** a fixture class `F` that implements `IExpandable` with
`IsExpanded == false`, `can_expand() -> true`, and `expand()` flipping
`IsExpanded` to true
**When** `f.expand()` is called after asserting `f.can_expand()` returns true
**Then** `f.IsExpanded == true`

### CAP-005 — ICollapsible contract

**Given** a fixture class `F` that implements `ICollapsible` with
`can_collapse() -> true` and `collapse()` recording one invocation
**When** `f.collapse()` is called after asserting `f.can_collapse()` returns true
**Then** the recorder has exactly one invocation

### CAP-006 — IExpansionTogglable contract

**Given** a fixture class `F` that implements `IExpansionTogglable` with
`can_toggle_expansion() -> true` and `toggle_expansion()` flipping an internal
`expanded` flag
**When** `f.toggle_expansion()` is called twice, asserting `can_toggle_expansion()` first
**Then** the internal flag has returned to its initial value

### CAP-007 — IClosable contract

**Given** a fixture class `F` that implements `IClosable` with
`can_close() -> true` and `close()` recording one invocation
**When** `f.close()` is called after asserting `f.can_close()` returns true
**Then** the recorder has exactly one invocation

### CAP-008 — ISearchable contract

**Given** a fixture class `F` that implements `ISearchable` with `SearchTerm = ""`
**When** `f.SearchTerm = "abc"` is set, then `f.search()` is called after
asserting `f.can_search()` returns true
**Then** `f.SearchTerm == "abc"`
**And** the search recorder records the term `"abc"`

### CAP-009 — IApprovable contract

**Given** a fixture class `F` that implements `IApprovable` with
`can_approve() -> true` and `approve()` recording one invocation
**When** `f.approve()` is called after asserting `f.can_approve()` returns true
**Then** the recorder has exactly one invocation

### CAP-010 — ICancelable contract

**Given** a fixture class `F` that implements `ICancelable` with
`can_cancel() -> true` and `cancel()` recording one invocation
**When** `f.cancel()` is called after asserting `f.can_cancel()` returns true
**Then** the recorder has exactly one invocation

### CAP-011 — ISavable<T> contract

**Given** a fixture class `F` that implements `ISavable<T>` for some `T`
with `can_save(item) -> true` and `save(item)` recording the item
**When** `f.save(item_a)` is called after asserting `f.can_save(item_a)` returns true
**Then** the recorder records `item_a`

### CAP-012 — IManagable<T> contract

**Given** a fixture class `F` that implements `IManagable<T>` for some `T`
with `can_manage(item) -> true` and `manage(item)` recording the item
**When** `f.manage(item_a)` is called after asserting `f.can_manage(item_a)` returns true
**Then** the recorder records `item_a`

### CAP-013 — INewCreatable contract

**Given** a fixture class `F` that implements `INewCreatable` with
`can_create_new() -> true` and `create_new()` recording one invocation
**When** `f.create_new()` is called after asserting `f.can_create_new()` returns true
**Then** the recorder has exactly one invocation

### CAP-014 — IDeletable<T> contract

**Given** a fixture class `F` that implements `IDeletable<T>` for some `T`
with `can_delete(item) -> true` and `delete(item)` recording the item
**When** `f.delete(item_a)` is called after asserting `f.can_delete(item_a)` returns true
**Then** the recorder records `item_a`

### CAP-015 — IUpdatable<T> contract

**Given** a fixture class `F` that implements `IUpdatable<T>` for some `T`
with `can_update(item) -> true` and `update(item)` recording the item
**When** `f.update(item_a)` is called after asserting `f.can_update(item_a)` returns true
**Then** the recorder records `item_a`

### CAP-016 — ICurrentDeletable contract

**Given** a fixture class `F` that implements `ICurrentDeletable` with
`can_delete_current() -> true` and `delete_current()` recording one invocation
**When** `f.delete_current()` is called after asserting `f.can_delete_current()` returns true
**Then** the recorder has exactly one invocation

### CAP-017 — ICurrentUpdatable contract

**Given** a fixture class `F` that implements `ICurrentUpdatable` with
`can_update_current() -> true` and `update_current()` recording one invocation
**When** `f.update_current()` is called after asserting `f.can_update_current()` returns true
**Then** the recorder has exactly one invocation

### CAP-018 — Lifecycle capability set

**Given** a fixture class `F` that implements all three of `IConstructable`,
`IDestructable`, and `IReconstructable`
**When** the API surface is inspected
**Then** `F` has `can_construct`, `construct`, `can_destruct`, `destruct`,
`can_reconstruct`, and `reconstruct` members at the documented signatures

### CAP-019 — A single VM may implement multiple capabilities

**Given** a fixture class `F` declared as implementing
`ISelectable, IExpandable, IClosable, IApprovable, ICancelable` simultaneously
**When** the type is queried for each interface
**Then** the answer is `true` for all five interfaces
**And** invoking each interface's verb (after asserting its can\_-predicate)
records an invocation on the correct recorder

### CAP-020 — Core VM types do NOT implement non-baseline capabilities by default

**Given** a default-built `ComponentVM` (non-modeled, base type)
**When** the type is queried for `ISelectable`, `IExpandable`, `IClosable`,
`INewCreatable`, `ICurrentDeletable`, `ISearchable`
**Then** the answer is `false` for every one of those six
**And** the base VM does still report `true` for `IConstructable`,
`IDestructable`, and `IReconstructable` (lifecycle capabilities are baseline)

### CAP-021 — `IFilterable<TItem>` capability contract surface and opt-in behavior

**Given** a fixture class `F` that implements `IFilterable<TItem>` and a minimal
`CompositeVM` wrapper that opts in by declaring the capability
**When** the API surface is inspected
**Then** `F` exposes a settable `Filter` predicate and a `can_filter()` decision
**And** setting `Filter` to `null`/`None` clears the filter (no predicate applied)
**And** a VM that does NOT opt in reports `false` for `IFilterable<TItem>`

### CAP-022 — `IPageable` capability contract surface and clamping/navigation behavior

**Given** a fixture class `F` that implements `IPageable` with a minimal opt-in
implementer
**When** the API surface is inspected
**Then** `F` exposes mutable `PageSize` and `CurrentPageIndex`, derived `PageCount`
and `IsPagingEnabled`
**And** setting `PageSize = 0` means "all items in one page" and disables paging
(`IsPagingEnabled == false`)
**And** `move_to_first_page()`, `move_to_previous_page()`, `move_to_next_page()`,
and `move_to_last_page()` are present and behave as no-ops at their respective
bounds
**And** `CurrentPageIndex` is clamped to `[0, PageCount-1]` when `PageSize > 0`

______________________________________________________________________

## 16. Null-object service variants (`NULL-NNN`) — spec v2.0

Each NULL-NNN test verifies a null-object variant satisfies its service
contract as a safe no-op per ADR-0017.

### NULL-001 — NullMessageHub is a safe no-op

**Given** a `NullMessageHub` instance
**And** a subscriber to `Messages` that records every emission and counts completion
**When** `Send(message)` is called any number of times
**Then** the subscriber records zero emissions
**And** the subscription completes immediately upon subscribe (no values, no error)
**And** no exception is raised by any of the calls

### NULL-002 — NullDispatcher schedules synchronously on the calling thread

**Given** a `NullDispatcher` instance
**When** an action is scheduled on `Foreground` or on `Background`
**Then** the action executes synchronously on the calling thread
**And** by the time the schedule call returns, the action has completed

### NULL-003 — Null-object convention is satisfied for the base core service contracts

**Given** the set of base-package core service contracts: `IMessageHub`,
`IDispatcher` (sub-package contracts `INotificationHub` and `ILocalizer` are
covered by NOTIF-009 and LOC-002 respectively, not by this ID)
**When** the flavor's public surface is inspected
**Then** each contract has a paired null variant (`NullMessageHub`,
`NullDispatcher`) reachable from the public surface
**And** the null variant satisfies the contract (its operations are total —
they do not raise on any input)

______________________________________________________________________

## 17. Derived properties (`DPROP-NNN`) — spec v2.0

Each DPROP-NNN test verifies the `DerivedProperty<TValue>` contract from
spec/15-derived-properties.md.

### DPROP-001 — Single-source derived value computes on construction

**Given** a single source observable `s1` whose latest value is `10`
**And** a `DerivedProperty<int>` built from `s1` with transform `x => x * 2`
**When** `Value` is read after the derived property is constructed
**Then** `Value == 20`

### DPROP-002 — Source change triggers recompute

**Given** a `DerivedProperty<int>` built from source `s1` (initial `10`) with
transform `x => x * 2`
**When** `s1` emits the value `5`
**Then** `Value == 10`

### DPROP-003 — Two-source derived value

**Given** sources `s1` (initial `3`) and `s2` (initial `4`)
**And** a `DerivedProperty<int>` built from `(s1, s2)` with transform `(a, b) => a + b`
**When** `Value` is read after construction
**Then** `Value == 7`
**When** `s2` emits `6`
**Then** `Value == 9`

### DPROP-004 — Five-source derived value (spec minimum)

**Given** sources `s1..s5` with initial values `(1, 2, 3, 4, 5)`
**And** a `DerivedProperty<int>` built from all five with transform `sum`
**When** `Value` is read after construction
**Then** `Value == 15`

### DPROP-005 — Mutation of any source recomputes

**Given** the five-source setup from DPROP-004
**When** `s3` emits the value `30`
**Then** `Value == 1 + 2 + 30 + 4 + 5 == 42`

### DPROP-006 — Default-built derived property is read-only

**Given** a `DerivedProperty<int>` built without a validator or write-back
**When** `CanSet(any_value)` is queried
**Then** the result is `false` for every input

### DPROP-007 — Validator + write-back enables SetValue

**Given** a `DerivedProperty<int>` built with validator `v => v > 0` and a
recording write-back action
**When** `SetValue(5)` is called
**Then** the write-back action records `5`
**And** when `SetValue(-1)` is called, the operation raises and the write-back
is NOT invoked

### DPROP-008 — Write-back action receives the value

**Given** a `DerivedProperty<int>` built with validator `_ => true` and
write-back action `v => recorder.Add(v)`
**When** `SetValue(7)` is called
**Then** the recorder has exactly one entry, equal to `7`

### DPROP-009 — ValueChanged emits on recompute

**Given** a `DerivedProperty<int>` from `s1` (initial `1`) and a subscriber
to `ValueChanged`
**When** `s1` emits `2`, then `3`
**Then** the subscriber observes the sequence `[2, 3]`
**And** the subscriber did NOT observe the initial value as an emission
(only post-construction changes count)

### DPROP-010 — ValueChanged does not emit when transform output is unchanged

**Given** a `DerivedProperty<int>` from `(s1, s2)` with transform `(a, b) => a + b`
and a subscriber to `ValueChanged`
**And** initial values `s1=5, s2=5` so `Value == 10`
**When** `s1` emits `3` (so the transform produces `3 + 5 == 8`) then `s2` emits `7`
(so the transform produces `3 + 7 == 10` again)
**Then** the subscriber observes exactly `[8, 10]` — the second mutation
re-produces `10` and is not suppressed because the previous value was `8`
**When** continuing with `s1` emits `3` again (same source value)
**Then** no additional emission (transform output stays `10`)

### DPROP-011 — Dispose ends subscriptions and ValueChanged completes

**Given** a `DerivedProperty<int>` from `s1` (initial `1`) with a subscriber
to `ValueChanged` that records completion
**When** the derived property's `Dispose` is called
**Then** the subscriber's `complete` (or equivalent) callback is invoked
**And** subsequent emissions from `s1` do NOT update `Value` further

### DPROP-012 — Derived-property scenarios match fixture

**Given** the JSON fixture `spec/fixtures/derived-properties.json`
**When** each scenario is exercised — initial values populate sources, the
named transform is resolved, and the mutation sequence is replayed
**Then** the sequence of `Value` reads (one initial, one after each mutation)
matches `expected_values` exactly

______________________________________________________________________

## 18. Command decorators (`CMDD-NNN`) — spec v2.0

Each CMDD-NNN test verifies behaviour of the three decorators added in
spec/04-commands.md §Decorators (CMDD-010 added in spec v3, ADR-0049).

### CMDD-001 — CompositeCommand.CanExecute is OR over inner commands

**Given** a `CompositeCommand` aggregating inner commands `c1` (`CanExecute() == false`)
and `c2` (`CanExecute() == true`)
**When** `composite.CanExecute()` is called
**Then** the result is `true`
**And** when both inners return false, the result is `false`

### CMDD-002 — CompositeCommand.Execute invokes only enabled inner commands

**Given** a `CompositeCommand` aggregating `c1` (`CanExecute() == true`, records),
`c2` (`CanExecute() == false`, records), and `c3` (`CanExecute() == true`, records)
**When** `composite.Execute()` is called
**Then** `c1` and `c3` each record one invocation
**And** `c2` records zero invocations

### CMDD-003 — CompositeCommand propagates inner CanExecuteChanged

**Given** a `CompositeCommand` aggregating `c1` with a trigger, and a subscriber to
the composite's `CanExecuteChanged`
**When** `c1`'s trigger fires
**Then** the subscriber observes a `CanExecuteChanged` emission

### CMDD-004 — DecoratorCommand.CanExecute is inner AND extra-predicate

**Given** a `DecoratorCommand` wrapping `inner` (`CanExecute() == true`) with extra
predicate returning `false`
**When** `decorator.CanExecute()` is called
**Then** the result is `false`
**And** when the extra predicate returns `true`, the result is `true`
**And** when `inner.CanExecute()` is `false`, the result is `false` regardless of
the extra predicate

### CMDD-005 — DecoratorCommand.Execute invokes pre, inner, post in order

**Given** a `DecoratorCommand` wrapping `inner` (records) with pre-action `pre`
(records) and post-action `post` (records)
**When** `decorator.Execute()` is called (and `CanExecute` is true)
**Then** the recorded order is `[pre, inner, post]`

### CMDD-006 — DecoratorCommand.Execute is no-op when CanExecute is false

**Given** a `DecoratorCommand` wrapping `inner` (records) with extra predicate
returning `false`
**When** `decorator.Execute()` is called
**Then** `inner`, `pre`, and `post` all record zero invocations

### CMDD-007 — ConfirmationDecoratorCommand invokes inner only when confirmed

**Given** a `ConfirmationDecoratorCommand` wrapping `inner` (records) with a confirm
delegate that resolves `true`
**When** `decorator.Execute()` is called and the resulting task is awaited
**Then** `inner` records one invocation
**And** when the confirm delegate resolves `false`, `inner` records zero invocations

### CMDD-008 — ConfirmationDecoratorCommand.CanExecute delegates to inner

**Given** a `ConfirmationDecoratorCommand` wrapping `inner` with no extra gating
**When** `decorator.CanExecute()` is called
**Then** the result equals `inner.CanExecute()` for any state of `inner`

### CMDD-009 — Decorators compose (decorator of confirmation of relay)

**Given** a `RelayCommand` `relay` (records) wrapped by `ConfirmationDecoratorCommand`
`conf` (confirm returns `true`) wrapped by `DecoratorCommand` `dec` (no pre/post,
no extra predicate)
**When** `dec.Execute()` is called and awaited
**Then** `relay` records exactly one invocation

### CMDD-010 — ConfirmationDecoratorCommand surfaces fire-and-forget errors on `errors`

Per spec/04-commands.md §8.3.1 and ADR-0049. Full-parity in every flavor that
ships `ConfirmationDecoratorCommand` (C#, Python, TypeScript, Swift).

**Given** a `ConfirmationDecoratorCommand` wrapping `inner`, and a subscriber to its
`errors` observable
**When** the fire-and-forget `Execute()` runs with a `confirm` delegate that
rejects/raises
**Then** the subscriber observes that exception on `errors` (it is NOT swallowed)
**And** when instead `confirm` resolves `true` and `inner.Execute()` throws, the
subscriber observes the inner exception on `errors`

______________________________________________________________________

## 19. Notification sub-package (`NOTIF-NNN`) — spec v2.0 / v2.1

Each NOTIF-NNN test verifies the `INotificationHub` contract from
spec/16-notifications.md and ADR-0013.

### NOTIF-001 — Post returns an awaitable that completes when Resolve is called

**Given** a `NotificationHub` instance and a notification
`n = Notification(Notification, "info")`
**When** `task = hub.Post(n)` is called, then `hub.Resolve(n, Approve)` is called
**Then** awaiting `task` yields `Approve`

### NOTIF-002 — Post adds the notification to Pending

**Given** a `NotificationHub` with a subscriber to `Pending`
**When** `hub.Post(n)` is called
**Then** the subscriber observes a new `Pending` snapshot whose contents include `n`

### NOTIF-003 — Resolve removes the notification from Pending

**Given** a `NotificationHub` with `n` posted and pending
**And** a subscriber to `Pending` that captures every snapshot
**When** `hub.Resolve(n, Approve)` is called
**Then** the final observed `Pending` snapshot does NOT include `n`

### NOTIF-004 — NotificationType has Error / Notification / Confirmation values

**Given** the `NotificationType` enum
**When** its values are enumerated
**Then** the set is exactly `{Error, Notification, Confirmation}`

### NOTIF-005 — NotificationReaction has Pending / Approve / Reject values

**Given** the `NotificationReaction` enum
**When** its values are enumerated
**Then** the set is exactly `{Pending, Approve, Reject}`

### NOTIF-006 — The resolved task carries the reaction value

**Given** a `NotificationHub` with `n` posted and `task = hub.Post(n)`
**When** `hub.Resolve(n, Reject)` is called
**Then** awaiting `task` yields `Reject`

### NOTIF-007 — Confirmation notifications can be resolved Approve or Reject

**Given** a `NotificationHub`
**And** `nApprove = Notification(Confirmation, "x")` posted via `taskA = hub.Post(nApprove)`
**And** `nReject  = Notification(Confirmation, "y")` posted via `taskR = hub.Post(nReject)`
**When** `hub.Resolve(nApprove, Approve)` and `hub.Resolve(nReject, Reject)`
**Then** `taskA` yields `Approve`
**And** `taskR` yields `Reject`

### NOTIF-008 — Resolving a notification not in Pending is a no-op

**Given** a `NotificationHub` and a fresh notification `n` that was never posted
**When** `hub.Resolve(n, Approve)` is called
**Then** no exception is raised
**And** `Pending` is unchanged

### NOTIF-009 — NullNotificationHub.Post resolves to Approve immediately

**Given** a `NullNotificationHub` instance and a notification
`n = Notification(Confirmation, "x")`
**When** `task = hub.Post(n)` is called
**Then** awaiting `task` yields `Approve`
**And** the wait completes immediately (does not block on user input)

### NOTIF-010 — make_confirm helper returns true iff resolved Approve

**Given** a `NotificationHub` and the helper `confirm = make_confirm(hub, "ok?")`
**When** the call `confirm()` is initiated and the next pending notification
is resolved Approve
**Then** awaiting `confirm()` yields `true`
**And** when the next pending notification is resolved Reject instead, awaiting
yields `false`

### NOTIF-011 — `NotificationVM` opacity decays linearly from 1.0 to 0.0 over `Lifespan` — spec v2.1

**Given** a `NotificationVM` with `Lifespan = 10 s` constructed under a `TestScheduler`
**When** `Opacity` is read at construction time
**Then** `Opacity` is `1.0`
**When** the scheduler is advanced by 5 s
**Then** `Opacity` is approximately `0.5` (±0.01)
**When** the scheduler is advanced to the full 10 s mark
**Then** `Opacity` is approximately `0.0` (±0.01)

### NOTIF-012 — `NotificationVM` auto-dismisses (resolves Approve) when `RemainingTime` reaches 0 — spec v2.1

**Given** a `NotificationVM` with `Lifespan = 10 s` under a `TestScheduler`
**And** the notification has been posted to a `NotificationHub`
**When** the scheduler is advanced by 10 s
**Then** `IsResolved` is `true`
**And** the hub notification is resolved with `NotificationReaction.Approve`

### NOTIF-013 — `ConfirmationVM` exposes `ApproveCommand` and `RejectCommand`; each resolves with the corresponding `NotificationReaction` — spec v2.1

**Given** a `ConfirmationVM` wrapping a posted notification
**When** `ApproveCommand.Execute()` is called
**Then** the hub notification is resolved with `NotificationReaction.Approve`
**And** `IsResolved` is `true`

**Given** a second `ConfirmationVM` wrapping a different posted notification
**When** `RejectCommand.Execute()` is called
**Then** the hub notification is resolved with `NotificationReaction.Reject`
**And** `IsResolved` is `true`

### NOTIF-014 — Manual `DismissCommand` cancels the lifespan timer; subsequent timer ticks have no effect — spec v2.1

**Given** a `NotificationVM` with `Lifespan = 10 s` under a `TestScheduler`
**And** the notification has been posted to a `NotificationHub`
**When** `DismissCommand.Execute()` is called at time 0
**And** the scheduler is advanced past the full 10 s lifespan
**Then** the hub notification is resolved exactly once (not twice)
**And** `IsResolved` is `true`

### NOTIF-015 — Hub-side `Resolve()` on the notification propagates to VM `IsResolved` state — spec v2.1

**Given** a `NotificationVM` wrapping a posted notification
**And** `IsResolved` is initially `false`
**When** `hub.Resolve(notification, NotificationReaction.Approve)` is called externally
(not through the VM's own commands)
**Then** `IsResolved` becomes `true`
**And** the lifespan timer is cancelled (no further auto-dismiss effects)

### NOTIF-016 — Deterministic behavior under injected `TestScheduler` / fake clock — spec v2.1

**Given** a `NotificationVM` with `Lifespan = L` under a `TestScheduler` starting at
virtual time 0
**When** the scheduler is advanced to exactly `L`
**Then** `RemainingTime` is 0
**And** `Opacity` is 0.0
**And** auto-dismiss fires exactly once
**And** no further effects occur when the scheduler advances beyond `L`

### NOTIF-017 — Hub dispose resolves in-flight waiters with `Pending` — spec v2.5.0

**Given** a `NotificationHub` with one or more posted-but-unresolved notifications
**When** the hub is disposed
**Then** every in-flight awaitable returned by `Post` resolves with
`NotificationReaction.Pending`
**And** the `Pending` observable completes
**And** a subsequent `Post` resolves immediately with `Pending` and does not enqueue
**And** a subsequent `Resolve` is a no-op
**And** disposing again is a no-op (idempotent)

______________________________________________________________________

## 20. CompositeVM search/filter, modeled CRUD & builder hooks (`COMP-014..037`)

Search/filter (COMP-014..018, see ADR-0014), modeled CRUD (COMP-019..024,
see ADR-0016), and builder hooks (COMP-025..026, see ADR-0042) additions to
chapter 06.

### COMP-014 — SearchableState defaults to empty search term

**Given** a `SearchableState` over a list of items
**When** `SearchTerm` is read after construction
**Then** the value is `""`
**And** `Filtered` initially emits every item (predicate matches everything)

### COMP-015 — Setting SearchTerm triggers a debounced recompute

**Given** a `SearchableState` over `["apple", "banana", "cherry"]` with predicate
"case-insensitive substring match" and debounce 0 (no delay, for the test)
**And** a subscriber to `Filtered`
**When** `SearchTerm = "an"` is set
**Then** the subscriber observes a snapshot `["banana"]`

### COMP-016 — search() forces immediate recompute, bypassing debounce

**Given** a `SearchableState` over `["one", "two"]` with predicate "exact match"
and a large debounce (1 second)
**And** a subscriber to `Filtered`
**When** `SearchTerm = "two"` is set, then `search()` is called immediately
**Then** the subscriber observes a snapshot `["two"]` before the debounce window
elapses

### COMP-017 — Predicate is user-supplied

**Given** a `SearchableState` constructed with predicate
`(item, term) => item.length > term.length` over `["a", "bb", "ccc"]`
**When** `SearchTerm = "bb"` is set and `search()` is called
**Then** `Filtered` emits `["ccc"]`

### COMP-018 — Filtered recomputes when Items source changes

**Given** a `SearchableState` over an initial list `["one"]` with predicate
"any match" and a search term of `"x"`
**And** a subscriber to `Filtered`
**And** no optional source-change signal was supplied
**When** the items source is updated to `["one", "two"]` and `search()` is
called explicitly
**Then** the subscriber observes a snapshot containing two items

### COMP-019 — CreateNewCommand invokes create-new action

**Given** a `ModeledCrudCommands` built with a recording `create_new` action
**When** `CreateNewCommand.Execute()` is called
**Then** the recorder has exactly one invocation

### COMP-020 — UpdateCurrentCommand invokes update with current VM

**Given** a `ModeledCrudCommands` with `current` returning `vm1` and a
recording `update_current(vm)` action
**When** `UpdateCurrentCommand.Execute()` is called
**Then** the recorder records `vm1` once

### COMP-021 — UpdateCurrentCommand.CanExecute false when current is null

**Given** a `ModeledCrudCommands` with `current` returning `null`
**When** `UpdateCurrentCommand.CanExecute()` is called
**Then** the result is `false`

### COMP-022 — DeleteCurrentCommand invokes delete with current VM

**Given** a `ModeledCrudCommands` with `current = vm1` and a recording
`delete_current(vm)` action
**When** `DeleteCurrentCommand.Execute()` is called
**Then** the recorder records `vm1` once

### COMP-023 — DeleteCurrentCommand.CanExecute false when current is null

**Given** a `ModeledCrudCommands` with `current` returning `null`
**When** `DeleteCurrentCommand.CanExecute()` is called
**Then** the result is `false`

### COMP-024 — DeleteCurrentCommand confirm gate

**Given** a `ModeledCrudCommands` with `current = vm1`, a recording
`delete_current` action, and a confirm delegate that resolves `false`
**When** `DeleteCurrentCommand.Execute()` is awaited
**Then** the recorder is empty
**And** when the confirm delegate resolves `true`, the recorder records `vm1`

### COMP-025 — `Current(selector)` builder hook drives initial selection during construct

**Given** a `CompositeVM<VM>` built with three children `a`, `b`, `c` and
`.Current(xs => xs.Skip(1).First())` (idiomatic per flavor) in `Destructed` state
**When** `composite.construct()` is called
**Then** after `construct()` returns, `composite.Current == b`
**And** the selector ran exactly once, after every child reached `Constructed` and
before the composite reached `Constructed`
**And** when the same composite is instead built with `.Current(_ => null)`,
after `construct()` returns `composite.Current` is `null` and no
`PropertyChangedMessage("Current")` is published

### COMP-026 — `OnCurrentChanged(callback)` fires synchronously after each `Current` change

**Given** a `CompositeVM<VM>` built with three children `a`, `b`, `c` and
`.OnCurrentChanged(vm => observed.Add(vm))` where `observed` is an empty list
**And** the composite is in `Constructed` state with `Current == null`
**When** `composite.select_component(b)` then `composite.deselect_component(b)` are called
**Then** `observed` equals `[b, null]` (exactly two invocations)
**And** each invocation is observed after the corresponding
`PropertyChangedMessage("Current")` is published on the hub
**And** when the composite is instead built with both
`.Current(xs => xs.First())` and `.OnCurrentChanged(vm => observed.Add(vm))`,
after `construct()` returns `observed` equals `[a]` (exactly one invocation
from the initial-selector assignment)

### COMP-027 — Adding a child sets its `Parent`; removing clears it

**Given** a `Constructed` `CompositeVM<VM>` `composite` and a separately-built,
`Constructed` child `c` that has not yet been added to any container
**Then** `c.can_select()` is `false` (a VM with no `Parent` is not selectable)
**When** `composite.Add(c)` is called
**Then** `c.can_select()` is `true` (the container set `c`'s `Parent` to itself on add,
and `c` is `Constructed` and not yet `Current`)
**And** `c.select()` makes `composite.Current` equal `c` and `c.IsCurrent` `true`
(the predicate and `select()` delegate through the newly-wired `Parent`)
**When** `c.deselect()` then `composite.Remove(c)` are called
**Then** `c.can_select()` is `false` again (removal cleared `c`'s `Parent` to `null`)
**And** a subsequent `c.select()` is a no-op — `composite.Current` stays `null` —
because `c` no longer has a `Parent` to delegate to

### COMP-028 — FilteredCompositeVM visible projection

**Given** a source `CompositeVM<VM>` and a predicate
**When** a `FilteredCompositeVM<VM>` is created over the source
**Then** `Visible` contains only source children accepted by the predicate
**And** source order is preserved

### COMP-029 — FilteredCompositeVM visible count

**Given** a filtered composite view
**When** `VisibleCount` is queried
**Then** it equals the current visible projection length

### COMP-030 — FilteredCompositeVM current maps to visible domain

**Given** a filtered composite view with at least one visible item
**When** `Current` is set to a visible item
**Then** `Current` returns that same source child

### COMP-031 — predicate change recomputes projection

**Given** a filtered composite view
**When** its predicate is replaced
**Then** the visible projection is recomputed immediately

### COMP-032 — source mutation reconciles projection

**Given** a filtered composite view subscribed to its source composite
**When** the source composite is mutated
**Then** the visible projection is recomputed

### COMP-033 — filtered cursor policies

**Given** a filtered composite view whose current item becomes filtered out
**When** the cursor policy is snap-to-first
**Then** `Current` moves to the first visible item
**And when** the cursor policy is clear
**Then** `Current` becomes null

### COMP-034 — visible navigation

**Given** a filtered composite view with multiple visible items
**When** next and previous visible navigation methods are invoked
**Then** `Current` moves within the visible projection and clamps at bounds

### COMP-035 — filtered view disposal

**Given** a filtered composite view
**When** it is disposed
**Then** later source mutations no longer update that view

### COMP-036 — scored filter orders by score with stable ties

**Given** a scored filtered composite view
**When** scores are computed
**Then** items with null/absent scores are excluded
**And** remaining items are ordered by descending score
**And** equal scores preserve source order

### COMP-037 — scored filter can recompute ordering

**Given** a scored filtered composite view whose scorer reads external score state
**When** that score state changes and `RefreshScores()` is called
**Then** the visible projection is reordered from the latest scores

### COMP-038 — Adding to a new parent transfers exclusive ownership

**Given** two mutable containers `old` and `new`, covering both `CompositeVM`
and `GroupVM` as source and destination
**And** the same child identity `c` occurs once in `old` and is `Constructed`
**When** `new.Add(c)` is called
**Then** `old` no longer contains `c` and `new` contains it exactly once
**And** `c.Parent` denotes only `new`, including parent-derived selection behavior
**And** `c.Status` remains `Constructed`
**And** a later removal attempt against `old` cannot clear `c`'s new parent

### COMP-039 — Duplicate and cycle rejection is mutation-free

**Given** a mutable composite or group `parent` containing child `c`
**When** `parent.Add(c)` is attempted again
**Then** the flavor-standard ownership error is returned or raised
**And** membership, parent link, selection state, lifecycle state, and
collection notifications are unchanged
**And** attaching a container to itself or beneath one of its descendants is
rejected with the same mutation-free guarantee

### COMP-040 — Failed ownership transfer restores exact state

**Given** child `c` at index `i` in `old`, with `old.Current == c` when `old` is
a composite
**And** destination `new` is configured to auto-construct added children
**And** `c` is `Destructed` and its construct hook fails
**When** `new.Add(c)` is attempted
**Then** the original construction error is returned or raised
**And** `c` is restored at index `i` in `old` with the original `Parent`,
`Current`, `IsCurrent`, and `Destructed` state
**And** `new` has its exact pre-call membership and selection state
**And** lazy or bulk population remains retryable after the failing child is fixed

### COMP-041 — Transfer notifications commit removal before addition

**Given** collection-change recorders on `old` and `new`
**And** child `c` belongs to `old`
**When** `new.Add(c)` succeeds
**Then** the global observation order is `old:Remove(c)` followed by `new:Add(c)`
**And** each callback observes committed membership and the new parent link
**And** when destination attachment or construction fails, neither recorder
observes a membership event

### SRCH-001 — source signal refreshes an unchanged search term

**Given** a `SearchableState` over `["one"]` with an optional source-change
signal, an empty unchanged term, and a subscriber to the filtered output
**When** `"two"` is added to the supplier's collection and the source emits one
signal
**Then** exactly one new filtered notification is observed
**And** its latest projection is `["one", "two"]`

### SRCH-002 — remove, replace, reset, and reorder read the latest source

**Given** a signaled `SearchableState` over an ordered mutable source and a term
that matches every item
**When** the source is removed from, replaced in place, reset to a different
sequence, and reordered, with one signal after each committed mutation
**Then** each notification contains or exposes the exact latest ordered supplier
snapshot
**And** no removed or replaced value remains in a later projection

### SRCH-003 — source pulses are transparent to equality and upstream batching

**Given** a signaled `SearchableState` whose supplier result is value-equal to
its previous result
**When** the source emits two separate pulses
**Then** two filtered notifications are observed
**When** several committed mutations are represented by one upstream-coalesced
pulse
**Then** exactly one additional filtered notification is observed

### SRCH-004 — source refresh is independent of pending term work

**Given** a signaled `SearchableState` with a non-zero term debounce
**When** a new term is set and, before its debounce window elapses, the source is
mutated and emits a pulse
**Then** the source pulse immediately refreshes using the current new term
**And** the pending term delivery is neither canceled nor restarted and remains
eligible at its original deadline
**And** a flavor whose established reactive facade delivers term notifications
synchronously proves the source and term notifications remain independent

### SRCH-005 — source completion or failure is isolated

**Given** a signaled `SearchableState` with an active filtered subscriber
**When** an error-capable source signal fails, or a non-failing signal completes
or is disposed
**Then** automatic source refresh stops without failing the filtered output
**When** the supplier changes and explicit `search()` is invoked
**Then** the latest projection remains available and a new filtered notification
is produced where the flavor exposes a pushed filtered output

### SRCH-006 — disposal cancels source observation exactly once

**Given** a signaled `SearchableState` and an observer of its filtered output
**When** the helper is disposed twice and the source later emits
**Then** the source subscription has been canceled exactly once
**And** no post-disposal filtered notification occurs
**And** the source signal and supplied items have not been disposed by the helper

### SRCH-007 — omitting the signal preserves explicit-refresh compatibility

**Given** a `SearchableState` constructed without a source-change signal
**When** its supplier's collection changes while the term is unchanged
**Then** no automatic filtered notification occurs
**When** `search()` is called
**Then** the latest supplier projection is returned or emitted
**And** the helper owns neither the supplier collection nor its items

______________________________________________________________________

## 21. GroupVM v2.0 additions (`GRP-007..011`)

Search/filter additions to chapter 07. The helper is the same
`SearchableState<TItem>` documented for composites (see ADR-0014); group-context
tests verify the helper behaves identically when items are group children.

### GRP-007 — SearchableState defaults to empty search term (group context)

**Given** a `SearchableState` over a list of group children
**When** `SearchTerm` is read after construction
**Then** the value is `""`

### GRP-008 — Setting SearchTerm triggers debounced recompute (group context)

**Given** a `SearchableState` over `["x", "yx", "z"]` with predicate
"case-insensitive substring match" and debounce 0
**And** a subscriber to `Filtered`
**When** `SearchTerm = "x"` is set
**Then** the subscriber observes a snapshot `["x", "yx"]`

### GRP-009 — search() forces immediate recompute (group context)

**Given** a `SearchableState` with a large debounce
**When** `SearchTerm` is set then `search()` is called immediately
**Then** the subscriber observes the filtered snapshot before the debounce
window elapses

### GRP-010 — Predicate is user-supplied (group context)

**Given** a `SearchableState` with a custom predicate
**When** `SearchTerm` is set and `search()` is called
**Then** the filtered snapshot reflects the custom predicate's matches

### GRP-011 — Group children are not selectable peers

**Given** a constructed `GroupVM<VM>` containing `child`
**And** `child` has reached `Constructed`
**When** `child.can_select` / `child.CanSelect()` / `child.canSelect()` is queried
**Then** the result is `false`
**And** the inherited child select command's predicate is disabled
**And** calling `child.select()` / `child.Select()` does not make the child current

______________________________________________________________________

## 22. Expand / collapse (`EXP-NNN`) — spec v2.0

Each EXP-NNN test verifies the `ExpandableState` helper and `walk_expanded`
tree traversal from spec/05-component-vm.md and spec/13-tree-utilities.md.

### EXP-001 — ExpandableState defaults to collapsed

**Given** a freshly built `ExpandableState`
**When** `IsExpanded` is read
**Then** the value is `false`
**And** `CanExpand()` returns `true`, `CanCollapse()` returns `false`

### EXP-002 — Expand flips state and emits IsExpandedChanged

**Given** an `ExpandableState` with `IsExpanded == false`
**And** a subscriber to `IsExpandedChanged`
**When** `Expand()` is called
**Then** `IsExpanded == true`
**And** the subscriber observes exactly one emission with value `true`
**And** subsequent `Expand()` calls are no-ops (`IsExpanded` stays `true`, no
additional emissions)

### EXP-003 — Collapse flips state back

**Given** an `ExpandableState` with `IsExpanded == true`
**And** a subscriber to `IsExpandedChanged`
**When** `Collapse()` is called
**Then** `IsExpanded == false`
**And** the subscriber observes exactly one emission with value `false`

### EXP-004 — ToggleExpansion alternates state

**Given** an `ExpandableState` with `IsExpanded == false`
**When** `ToggleExpansion()` is called twice
**Then** `IsExpanded == false`
**And** when called a third time, `IsExpanded == true`

### EXP-005 — walk_expanded skips descendants of collapsed nodes

**Given** a tree:

```
root: CompositeVM with IExpandable wrapper, expanded
  ├── a: ComponentVM (no IExpandable)
  └── b: CompositeVM with IExpandable wrapper, COLLAPSED
        ├── b1: ComponentVM
        └── b2: ComponentVM
```

**When** `list(walk_expanded(root))` is materialized
**Then** the sequence is `[root, a, b]` — b's children are NOT visited

______________________________________________________________________

## 23. Localization (`LOC-NNN`) — spec v2.0

Each LOC-NNN test verifies the `ILocalizer` contract and `NullLocalizer`
null-default from spec/17-localization.md.

### LOC-001 — ILocalizer.Localize returns a string

**Given** a concrete `ILocalizer` implementation that returns `"hello"` for
key `"greeting"`
**When** `localizer.Localize("greeting")` is called
**Then** the result is the string `"hello"`

### LOC-002 — NullLocalizer.Localize returns the key verbatim

**Given** a `NullLocalizer` instance
**When** `localizer.Localize("some-key")` is called
**Then** the result is `"some-key"` (the key is returned unchanged)
**And** `localizer.Localize("some-key", [arg1, arg2])` also returns
`"some-key"` (no formatting)

### LOC-003 — Custom localizer can be substituted

**Given** a fixture localizer that returns `"X:" + key` for every key
**When** the fixture localizer is used in place of the null variant
**Then** calling `Localize("foo")` returns `"X:foo"`
**And** the framework's `ILocalizer` contract accepts the fixture without
type errors

______________________________________________________________________

## 24. Collection primitives (`COL-NNN`) — spec v2.1

Each COL-NNN test verifies a collection primitive from `spec/21-collections.md`.
See ADR-0024 (`ServicedObservableCollection<T>`), ADR-0025 (`ObservableDictionary`),
ADR-0026 (`ObservableList<T>`), ADR-0023 (`PagedComposition<TVM>`), and
ADR-0096 (serviced collection parity), and ADR-0097 (keyed serviced
collection).

### COL-001 — `ServicedObservableCollection<T>` publishes to hub after local event on add

**Given** a `ServicedObservableCollection<T>` constructed with a hub
**And** subscribers that record the order of local collection-change and
external-hub `CollectionChangedMessage` receipts
**When** an item is added
**Then** the local collection-change channel fires before the external-hub
message is published
**And** in C#, Python, TypeScript, and Swift the hub message carries Add, the
added item, `index == newIndex == insertion`, and `oldIndex == -1`
**And** in Rust it carries Add, `old_index == None`, and
`new_index == Some(insertion)`, with no legacy `index` or typed item payload

### COL-002 — `ServicedObservableCollection<T>` publishes on remove and replace

**Given** a `ServicedObservableCollection<T>` constructed with a hub and containing items
**When** an item is removed, then another is replaced
**Then** each mutation publishes exactly one `CollectionChangedMessage` to the hub
**And** the `Action` field equals `Remove` for the removal and `Replace` for the replacement
**And** in C#, Python, TypeScript, and Swift the removal carries its old item,
`index == oldIndex`, and `newIndex == -1`, while replacement carries both items
and equal present integer positions
**And** in Rust removal carries a present `old_index` and absent `new_index`,
while replacement carries equal present optional positions; neither message has
a legacy `index` or typed item payload

### COL-003 — Null-hub fallback: no hub means no publication, no error

**Given** a `ServicedObservableCollection<T>` constructed with no hub (or an explicit null)
**When** items are added, removed, and replaced
**Then** all mutations complete without raising any exception
**And** local `CollectionChanged` events fire normally for each mutation
**And** no hub message is published (no hub is present)

### COL-004 — `ServicedObservableCollection<T>` does not marshal; fires on caller thread

**Given** a `ServicedObservableCollection<T>` with a hub
**And** a subscriber that records the thread ID of each hub `CollectionChangedMessage` receipt
**When** an item is added on thread T
**Then** the hub message is received on thread T
**And** no scheduler or dispatcher is involved in the delivery

### COL-005 — `ObservableList<T>` `ItemAdded` payload shape

**Given** an `ObservableList<T>` with a subscriber to `ItemAdded`
**When** `Add(item)` is called
**Then** `ItemAdded` emits exactly once with `item` equal to the added item
**And** the `index` in the payload equals the position at which the item was inserted (zero-based)

### COL-006 — `ObservableList<T>` `ItemRemoved` payload shape

**Given** an `ObservableList<T>` containing `[a, b, c]` with a subscriber to `ItemRemoved`
**When** `RemoveAt(1)` is called (removing `b`)
**Then** `ItemRemoved` emits with `item == b` and `index == 1` (position before removal)

### COL-007 — `ObservableList<T>` `ItemReplaced` payload shape

**Given** an `ObservableList<T>` containing `[a, b]` with a subscriber to `ItemReplaced`
**When** `Replace(0, c)` is called (replacing `a` with `c`)
**Then** `ItemReplaced` emits with `newItem == c`, `oldItem == a`, and `index == 0`

### COL-008 — `ObservableList<T>` `Count` / `PropertyChanged` ordering after add

**Given** an `ObservableList<T>` with a subscriber that records the sequence of `ItemAdded` and `PropertyChanged("Count")` events
**When** `Add(item)` is called
**Then** `ItemAdded` fires before `PropertyChanged("Count")`
**And** `Count` reflects the new value by the time `PropertyChanged("Count")` fires

### COL-009 — `ObservableList<T>` batch suppression: only `Reset` fires inside `BatchUpdate`

**Given** a VM with an `ObservableList<T>` and a subscriber recording `ItemAdded`, `ItemRemoved`, and `Reset` events
**When** a `BatchUpdate()` scope is entered and three items are added and one removed inside the batch
**Then** no `ItemAdded` or `ItemRemoved` events fire during the batch
**And** exactly one `Reset` event fires when the batch completes

### COL-010 — `ObservableDictionary` insert and retrieve

**Given** an `ObservableDictionary<TKey1, TKey2, TValue>` (empty)
**When** `Add(k1, k2, v)` is called
**Then** `ContainsKey(k1, k2)` returns true
**And** the indexer `[k1, k2]` returns `v`
**And** `Count == 1`

### COL-011 — `ObservableDictionary` remove

**Given** an `ObservableDictionary` containing `(k1, k2) → v`
**When** `Remove(k1, k2)` is called
**Then** `ContainsKey(k1, k2)` returns false
**And** `Count == 0`

### COL-012 — `ObservableDictionary` replace

**Given** an `ObservableDictionary` containing `(k1, k2) → v1`
**When** the entry is replaced with `v2` (via indexer or `Add` after remove)
**Then** `[k1, k2]` returns `v2`
**And** `Count` remains unchanged

### COL-013 — `ObservableDictionary` distinct-key observable views stay in sync

**Given** an `ObservableDictionary<string, int, string>` with subscribers to `Keys1` (`ItemAdded`, `ItemRemoved`) and `Keys2`
**When** `Add("a", 1, "x")` then `Add("a", 2, "y")` then `Remove("a", 1)` are called
**Then** `Keys1` contains `["a"]` (only one entry; "a" appeared once and survives while any (a,?) entry exists)
**And** `Keys2` contains `[2]` (1 was removed because no other entry uses key2=1)

### COL-014 — `ObservableDictionary` enumeration order is insertion order

**Given** an `ObservableDictionary` with entries inserted in order `(k1, k2a)`, `(k2, k2b)`, `(k3, k2c)`
**When** the dictionary is enumerated
**Then** entries appear in insertion order: `(k1, k2a)`, `(k2, k2b)`, `(k3, k2c)`

### COL-015 — `ObservableDictionary` clear empties keys views

**Given** an `ObservableDictionary` containing multiple entries and subscribers to `Keys1` and `Keys2`
**When** `Clear()` is called
**Then** `Count == 0`
**And** `Keys1` and `Keys2` are both empty
**And** `Keys1` and `Keys2` each emitted the appropriate removal events

### COL-016 — `PagedComposition<TVM>` clamps `CurrentPageIndex` when source shrinks

**Given** a `PagedComposition<TVM>` wrapping a 10-item source with `PageSize == 3` and `CurrentPageIndex == 2` (last page)
**When** items are removed from the source until 4 items remain (2 full pages)
**Then** `PageCount == 2`
**And** `CurrentPageIndex` is clamped to `1` (the new upper bound)
**And in TypeScript** non-finite or fractional page sizes and indexes raise
`RangeError` before retained state or property notifications change, while
negative finite integers retain zero clamping

### COL-017 — `PagedComposition<TVM>` `PageCount` derivation under add and remove

**Given** a `PagedComposition<TVM>` wrapping a source with `PageSize == 5`
**When** the source starts empty, then 5 items are added, then 1 more is added
**Then** `PageCount` transitions: `0` → `1` → `2`
**And** when 1 item is removed, `PageCount` drops back to `1`

### COL-018 — `PagedComposition<TVM>` navigation no-ops at bounds

**Given** a `PagedComposition<TVM>` with `PageSize == 3` over an 8-item source (`PageCount == 3`)
**When** `move_to_first_page()` is called while `CurrentPageIndex == 0`
**Then** `CurrentPageIndex` remains `0`
**When** `move_to_last_page()` is called while `CurrentPageIndex == PageCount - 1`
**Then** `CurrentPageIndex` remains unchanged

### COL-019 — `PagedComposition<TVM>` `PageSize == 0` passes through all items

**Given** a `PagedComposition<TVM>` wrapping a 7-item source with `PageSize == 0`
**When** the composition's paging state and `Items` are queried
**Then** `IsPagingEnabled == false`
**And** `PageCount == 1`
**And** `CurrentPageIndex == 0`
**And** `Items` yields all 7 items

### COL-020 — `PagedComposition<TVM>` empty-source behavior

**Given** a `PagedComposition<TVM>` wrapping an empty source with `PageSize == 5`
**When** the composition's paging state, `Items`, and navigation verbs are exercised
**Then** `PageCount == 0`
**And** `CurrentPageIndex == 0`
**And** `Items` yields no items
**And** all four navigation verbs are no-ops (no exception raised)

### COL-021 — `PagedComposition<TVM>` composition with `SearchableState<T>`

**Given** a source composition of 10 items
**And** a `SearchableState<ItemVM>` wrapping the source that filters to 4 items
**And** a `PagedComposition<ItemVM>` wrapping the `SearchableState` filtered view with `PageSize == 3`
**When** the filter is applied
**Then** `PagedComposition.PageCount == 2` (ceil(4 / 3))
**And** the first page yields the first 3 filtered items
**And** `Items` does NOT include any items filtered out by `SearchableState`

### COL-022 — `ObservableDictionary` hub publication

**Given** an `ObservableDictionary<TKey1, TKey2, TValue>` constructed with an `IMessageHub`
**And** a subscriber recording `CollectionChangedMessage` receipts from the hub
**When** an entry is inserted, then a different entry is removed, then an existing entry is
replaced, then `Clear()` is called
**Then** each mutation publishes exactly one `CollectionChangedMessage` to the hub after
the local `CollectionChanged` event fires
**And** the `Action` field carries the correct value (`Add`, `Remove`, `Replace`,
`Reset`) for each mutation

**Given** an `ObservableDictionary` constructed with no hub (or an explicit null)
**When** the same four mutations are performed
**Then** all mutations complete without raising any exception
**And** no hub message is published

### COL-023 — `ObservableList` batch-end `Count` notification

**Given** an `ObservableList<T>` with at least one item already present
**And** a subscriber recording `Reset` events and `PropertyChanged("Count")` events

**When** a `batch_update`/`withBatch`/`BatchUpdate()` block contains mutations
that change the collection's `Count` (e.g., at least one add or remove)
**Then** the batch-end `Reset` is emitted first
**And** a `PropertyChanged("Count")` notification is emitted immediately after
**And** the `Count` value is already updated when the `PropertyChanged` fires

**When** a `batch_update`/`withBatch`/`BatchUpdate()` block is empty (no mutations)
**Then** no `Reset` is emitted
**And** no `PropertyChanged("Count")` is emitted

**When** a `batch_update`/`withBatch`/`BatchUpdate()` block contains only
count-preserving mutations (e.g., only replace operations)
**Then** a `Reset` is emitted (mutations occurred)
**And** no `PropertyChanged("Count")` is emitted (count unchanged)

### COL-024 — `TokenPagedComposition<TVM,TToken>` initial state

**Given** a token-paged composition with an async `fetch_next` function
**When** the composition is created before any fetch
**Then** `Items` is empty
**And** `CurrentToken` is terminal/null
**And** `HasMore` is true
**And** `LoadMoreCommand.CanExecute` is true

### COL-025 — token load-more appends items and advances token

**Given** a token-paged composition whose first fetch returns items and a next token
**When** `LoadMoreCommand` is executed
**Then** the returned items are appended to `Items`
**And** `CurrentToken` becomes the returned next token
**And** a later load passes that token to `fetch_next`

### COL-026 — terminal token disables load-more

**Given** a token-paged composition whose fetch returns a terminal/null next token
**When** the load completes
**Then** `HasMore` is false
**And** `LoadMoreCommand.CanExecute` is false

### COL-027 — refresh refetches from the initial token

**Given** a token-paged composition with previously loaded items
**When** `RefreshCommand` is executed
**Then** `fetch_next` is called with the initial terminal/null token
**And** the accumulator reflects the refreshed first page
**And** token state reflects the refreshed next token

### COL-028 — refresh dedup suppresses redundant mutation

**Given** a token-paged composition whose refreshed first page matches the current accumulator head
**When** `RefreshCommand` is executed
**Then** the accumulator is not mutated
**And** no `CollectionChanged` event is emitted for the redundant refresh

### COL-029 — token-paged collection changes use reset semantics

**Given** a token-paged composition with a `CollectionChanged` subscriber
**When** a load effectively mutates the accumulator
**Then** exactly one coarse `Reset` collection event is emitted

### COL-030 — token-paged auto-construct-on-add

**Given** a token-paged composition created with auto-construct-on-add enabled
**And** a fetched page contains VMx component VMs
**When** the load completes
**Then** the added component VMs are constructed before subscribers observe the reset event

### COL-031 — `PagedComposition<TVM>` observes composite collection changes

**Given** a finite `PagedComposition<TVM>` wrapping a `CompositeVM<TVM>` source
**And** a property-changed subscriber
**When** the composite source is mutated
**Then** the paged composition recomputes page state
**And** emits an `Items` property notification

### COL-032 — shared VM collection capability keeps selection separate

**Given** one `CompositeVM<VM>` and one `GroupVM<VM>`
**Then** both satisfy the shared VM collection capability, including count,
indexed/iterable reads, observation, mutation, move, and batching
**And** only the composite satisfies the selectable collection capability
**And** the group exposes no `Current` child slot

### COL-033 — forward move is one precise collection mutation

**Given** a VM collection containing `[a, b, c]`
**When** `move(0, 2)` is called
**Then** its order is `[b, c, a]`
**And** exactly one `Move` event names `a`, old index `0`, and new index `2`

### COL-034 — backward move applies to non-selecting groups

**Given** a `GroupVM` containing `[a, b, c]`
**When** `move(2, 0)` is called
**Then** its order is `[c, a, b]`
**And** exactly one `Move` event names old index `2` and new index `0`

### COL-035 — same-index move is a true no-op

**Given** a VM collection containing `[a, b, c]`
**When** `move(1, 1)` is called
**Then** order and child state are unchanged
**And** no collection event is emitted
**And** an enclosing batch is not dirtied by that call

### COL-036 — invalid move bounds fail atomically

**Given** a VM collection of count three
**When** either move index is outside `[0, 3)`
**Then** a flavor-idiomatic catchable bounds error is raised
**And** no item, state, or event changes

### COL-037 — move preserves child and selection invariants

**Given** a constructed composite whose current child is `a`
**When** `a` is moved to another valid index
**Then** the child at the destination is the identical `a` instance
**And** its parent, lifecycle status, subscriptions, and `IsCurrent` stay unchanged
**And** the composite's `Current` remains the identical `a` instance

### COL-038 — batched move coalesces to reset

**Given** a VM collection with an open batch
**When** a non-no-op move occurs and the outer batch closes
**Then** no granular move event escapes the batch
**And** exactly one `Reset` event is emitted

### COL-039 — move does not trigger auto-construction

**Given** a constructed VM collection with auto-construct-on-add enabled
**And** an added child has already been constructed exactly once
**When** that child is moved
**Then** its construct hook is not called again
**And** the identical constructed instance occupies the destination

### COL-040 — whole-list replacement growth

**Given** a one-item `ObservableList<T>` with every notification channel observed
**When** `ReplaceAll` replaces it with three items
**Then** the final contents are exactly the three input items
**And** no granular item event fires
**And** exactly one Reset followed by one `PropertyChanged("Count")` fires

### COL-041 — whole-list replacement shrink

**Given** a three-item `ObservableList<T>`
**When** `ReplaceAll` replaces it with one item
**Then** the final contents contain only that item
**And** exactly one Reset followed by one `PropertyChanged("Count")` fires

### COL-042 — equal-count and identical replacement

**Given** an `ObservableList<T>` whose element type has no equality constraint
**When** `ReplaceAll` receives different contents of the same count
**And** it later receives the element-for-element identical non-empty contents
**Then** each call emits exactly one Reset and no `Count` notification
**And** VMx does not compare elements to suppress either call

### COL-043 — empty replacement cases

**Given** an empty `ObservableList<T>`
**When** `ReplaceAll` receives an empty input
**Then** no content or event changes
**But given** a non-empty list receives an empty input
**Then** it becomes empty and emits Reset followed by `PropertyChanged("Count")`

### COL-044 — replacement input snapshot

**Given** a non-empty `ObservableList<T>`
**When** `ReplaceAll` receives the list itself or a live view over it
**Then** the input is fully materialized before the backing list changes
**And** the final contents equal the input snapshot
**And** exactly one Reset fires

### COL-045 — replacement inside an existing batch

**Given** an `ObservableList<T>` with an open batch
**When** `ReplaceAll` performs an effective replacement
**Then** nothing is emitted before the outermost batch exits
**And** outermost exit emits exactly one Reset and `Count` only if cardinality changed

### COL-046 — exceptional batch exit

**Given** a batch body performs `ReplaceAll` and then fails
**When** the original failure propagates
**Then** every entered batch scope has closed
**And** the completed mutation emits the usual one Reset and optional `Count`
**And** a later replacement publishes normally outside the former batch

### COL-047 — replacement notification ordering and visibility

**Given** Reset and `PropertyChanged("Count")` observers read the list in their handlers
**When** `ReplaceAll` changes cardinality
**Then** Reset fires before `PropertyChanged("Count")`
**And** both handlers observe the complete final snapshot

### COL-048 — serviced value removal targets the first duplicate

**Given** a `ServicedObservableCollection<T>` containing `[a, b, a]`
**When** value removal is requested for `a`
**Then** only the first `a` is removed and the final contents are `[b, a]`
**And** in C#, Python, TypeScript, and Swift exactly one Remove message carries
`a`, `index == oldIndex == 0`, and `newIndex == -1`
**And** in Rust exactly one Remove message has `old_index == Some(0)` and
`new_index == None`, with no legacy `index` or typed item payload
**When** removal is requested for a missing value
**Then** contents and notification channels stay unchanged
**And** C#, TypeScript, Swift, and Rust return false, while Python raises its
documented list-style `ValueError`

### COL-049 — serviced indexed removal resolves or rejects before mutation

**Given** a `ServicedObservableCollection<T>` containing `[a, b, c]`
**When** the item at index `1` is removed
**Then** the operation returns according to the flavor idiom
**And** in C#, Python, TypeScript, and Swift exactly one Remove message carries
`b`, `index == oldIndex == 1`, and `newIndex == -1`
**And** in Rust exactly one Remove message has `old_index == Some(1)` and
`new_index == None`, with no legacy `index` or typed item payload
**And** each in-range negative Python index resolves to its nonnegative message
position, including `remove_at(-2)` resolving to `1`
**And** Python rejects excessively negative indices, while C#, TypeScript, and
Swift reject every negative index
**And** Rust's `usize` index type makes negative values unrepresentable
**And** all flavors reject indices at or above the count according to their
documented bounds behavior without partial mutation or publication

### COL-050 — serviced replacement is explicit and atomic

**Given** a `ServicedObservableCollection<T>` containing `[a, b]`
**When** index `1` is replaced by `c`
**Then** in C#, Python, TypeScript, and Swift exactly one Replace message carries
old item `b`, new item `c`, and `index == oldIndex == newIndex == 1`
**And** in Rust exactly one Replace message has
`old_index == new_index == Some(1)`, with no legacy `index` or typed item
payload
**When** the replacement item is identical or equal to the current item
**Then** exactly one Replace is still emitted without an equality precheck
**And** an invalid index follows the documented flavor bounds behavior without
changing contents or either notification channel

### COL-051 — serviced whole-list replacement uses one snapshot Reset

**Given** a `ServicedObservableCollection<T>` whose notification channels are
observed
**When** `ReplaceAll` receives the collection itself, a live view, or new input
**Then** the input is fully materialized before mutation and the final contents
equal that snapshot
**And** in C#, Python, TypeScript, and Swift every effective call emits exactly
one Reset with empty item payloads and `index == oldIndex == newIndex == -1`
**And** in Rust every effective call emits exactly one Reset with
`old_index == new_index == None`, no legacy `index`, and no typed item payload
**And** no flavor emits a granular message
**And** identical non-empty input remains effective, while empty-to-empty emits
nothing
**And** input iteration failure leaves contents and both channels unchanged

### COL-052 — serviced move preserves identity and precise positions

**Given** a `ServicedObservableCollection<T>` containing `[a, b, c]`
**When** `move(0, 2)` and, on a fresh collection, `move(2, 0)` are called
**Then** the final orders are `[b, c, a]` and `[c, a, b]`, respectively
**And** in C#, Python, TypeScript, and Swift each call emits exactly one Move
whose `index` equals the destination, whose integer `oldIndex` and `newIndex`
name the source and destination, and whose old/new payloads carry the identical
moved item
**And** in Rust each call emits exactly one Move whose present `old_index` and
`new_index` name the source and destination, with no legacy `index` or typed
item payload

### COL-053 — serviced move no-ops and bounds are strict

**Given** a `ServicedObservableCollection<T>` containing `[a, b, c]`
**When** `move(1, 1)` is called
**Then** contents and both notification channels remain unchanged
**When** either representable index is outside `[0, 3)`, including a negative
Python index
**Then** a flavor-idiomatic catchable bounds error is raised before mutation
and neither channel publishes

### COL-054 — serviced delivery is local-before-hub with final-state visibility

**Given** a `ServicedObservableCollection<T>` with local and hub subscribers
that inspect contents and record delivery order
**When** each effective add, remove, replace, ReplaceAll, move, and clear
operation is performed
**Then** backing state changes before notification, local delivery precedes the
equivalent hub message, and both subscribers observe the complete final state
**And** each operation delivers immediately without a serviced batch mechanism

### COL-055 — serviced clear and mutations preserve caller ownership

**Given** an empty serviced collection and lifecycle-observable item fixtures
**When** the empty collection is cleared
**Then** no local or hub notification is emitted
**When** a non-empty collection is cleared
**Then** C#, Python, TypeScript, and Swift emit exactly one Reset with empty item
payloads and `index == oldIndex == newIndex == -1`
**And** Rust emits exactly one Reset with `old_index == new_index == None`, no
legacy `index`, and no typed item payload
**And** value/index removal, replacement, ReplaceAll, move, and clear never
construct, dispose, reparent, or otherwise manage any contained item

### COL-056 — keyed serviced lookup uses captured keys and preserves order

**Given** a `KeyedServicedObservableCollection` containing items `a`, `b`, and
`c` in that insertion order
**And** an instrumented projector records every projection
**When** lookup and membership are queried repeatedly for all three keys
**Then** each lookup returns the corresponding stored value
**And** lookup and membership do not invoke the projector again
**And** indexed reads, iteration, and snapshots remain `[a, b, c]`
**When** `b`'s key-like property is mutated without replacing its membership
**Then** the old captured key still resolves to `b`, the newly projectable key
misses, and no collection or hub message is emitted
**And** a C# miss returns `false` through
`[MaybeNullWhen(false)] out TItem item`, while the other flavors return their
specified `None` / `undefined` / optional miss value

### COL-057 — keyed serviced insert uniqueness and projection failure are atomic

**Given** a keyed serviced collection with its local and hub channels observed
**And** snapshots of its items, captured-key behavior, and lookup results
**When** append or a flavor-exposed insert receives an item whose projected key
is already captured
**Then** C# throws `ArgumentException`, Python raises `ValueError`, TypeScript
throws `Error`, Swift throws
`KeyedServicedCollectionError.duplicateKey`, and Rust returns
`Err(VmxError::InvalidArgument(_))`
**And** the same exact error mapping applies when indexed replacement,
whole-list replacement, or slice/splice final-result validation discovers a
duplicate
**And** items, lookup results, captured keys, and both notification channels
remain unchanged
**When** a projector throws or returns its documented failure for a candidate
item
**Then** the failure propagates according to the flavor idiom with the same
unchanged-state and no-notification guarantees
**And** Swift's append, replace/setAt, replaceAll, and upsert have their exact
throwing signatures, while Rust's `new(owner_id, key_of)` /
`with_hub(owner_id, hub, key_of)` compile and push, replace, replace_all, and
upsert return their specified `VmxResult`

### COL-058 — keyed serviced upsert distinguishes Add from stable-position Replace

**Given** a keyed serviced collection containing `[a, b]`
**When** `upsert(c)` projects a missing key
**Then** it returns the Add outcome, appends `c` at index `2`, and emits exactly
one Add with the ordinary serviced item and position payload
**When** `upsert(b2)` projects `b`'s existing key
**Then** it returns the Replace outcome, leaves that membership at index `1`,
and emits exactly one Replace carrying the ordinary serviced old/new item and
stable-position payload
**When** upsert receives the identical instance currently stored for a present
key
**Then** it still emits one Replace at that stable position
**And** after every notification the captured-key lookup and ordered snapshot
already reflect the complete mutation

### COL-059 — keyed deletion reports success and the pre-removal position

**Given** a keyed serviced collection containing `[a, b, c]`
**When** deletion is requested for `b`'s captured key
**Then** the final order is `[a, c]`, the key no longer resolves, and exactly
one Remove names pre-removal index `1` using the flavor's ordinary serviced
message payload
**And** C#, Python, TypeScript, and Swift report success, while Rust returns the
removed `b` value
**When** deletion is requested for a missing key
**Then** it reports false / `None`, changes nothing, and emits no local or hub
message

### COL-060 — every removal and explicit rekey keeps the captured index synchronized

**Given** keyed serviced collections with mutable-key item fixtures
**When** first-equal value removal and indexed removal are exercised
**Then** each removes the targeted membership's captured key without
reprojecting stored items
**And** all later key lookups resolve the shifted ordered positions correctly
**When** an item's key-like property changes and indexed replacement installs
that same item at its existing position
**Then** the old captured key stops resolving, the newly projected key resolves
at that position, and exactly one Replace is emitted
**And** attempting that rekey to a key owned by another position fails
atomically
**But given** a fresh collection containing one item whose key-like property is
mutated after insertion
**When** that same instance is upserted under its now-missing projected key
**Then** a second membership is appended and both old and new captured keys
resolve to the identical item instance

### COL-061 — keyed whole-list replacement preflights keys and self input

**Given** a non-empty keyed serviced collection with both channels observed
**When** whole-list replacement receives new unique-key items
**Then** it materializes and projects every item before commit, installs the
new ordered items and captured keys atomically, and emits exactly one Reset
**When** whole-list replacement receives the collection itself
**Then** self input is safe and exactly one Reset is emitted for the valid
non-empty replacement
**When** replacement input contains duplicate projected keys or projection /
input iteration fails
**Then** the failure occurs before mutation and preserves the former items,
captured-key lookups, and silent channels
**And** empty-to-empty is the only valid replacement no-op

### COL-062 — keyed move, clear, and convenience mutations preserve invariants and ownership

**Given** a keyed serviced collection containing caller-owned,
lifecycle-observable items
**And** Python / TypeScript fixtures containing captured keys `[a, b, c]`
**When** Python slice assignment or TypeScript `splice` removes `b` and inserts
a replacement that projects key `b` in the same operation
**Then** inserted input is materialized/projected, the removed key is reusable,
the final order and lookup index commit atomically, and the ordinary Reset
notification is emitted
**When** the same operation inserts duplicate keys or a key retained outside
the removed range, or its input/projector fails
**Then** the former ordered items, captured keys, lookup index, and both
notification channels remain unchanged
**When** Python slice deletion or a TypeScript splice deletion succeeds
**Then** the deleted memberships' captured keys stop resolving and later
positions resolve correctly without reprojecting retained items
**And** TypeScript returns the removed items and uses Remove only for exactly
one removal with no insertion, Reset for every other effective splice, and no
message for removal/insertion of nothing; Python slice mutation uses Reset
**When** Python reverse is called for zero or one membership
**Then** it is a silent no-op without reprojection
**When** Python reverse is called for two or more memberships
**Then** items and captured keys reverse atomically without reprojection and
exactly one Reset is emitted
**When** a valid move, pop/removeLast, and the remaining flavor conveniences
are exercised
**Then** each ordinary serviced message has its specified action and old/new
position, and every post-mutation lookup matches the ordered snapshot
**When** equal-index move, empty clear, or another documented convenience no-op
is exercised
**Then** items, captured keys, and both channels remain unchanged
**When** a non-empty collection is cleared
**Then** all key lookups miss and exactly one Reset is emitted
**And** no move, removal, replacement, reset, or clear constructs, disposes,
destructs, reparents, or otherwise manages any item

### COL-063 — keyed delivery is local-before-hub and respects an existing hub transaction

**Given** a keyed serviced collection with local and hub observers that inspect
ordered items and key lookups
**When** an effective mutation occurs outside a hub transaction
**Then** all item/key/index state commits first, local delivery precedes the
equivalent hub message, and both observers see consistent final state
**Given** the injected hub is already inside its transaction/batch
**When** multiple keyed mutations occur
**Then** local notifications remain immediate and granular while hub delivery
is deferred
**And** transaction completion delivers the same hub messages in original hub
order without collapsing them into Reset
**And** the collection exposes no independent collection batch scope

### COL-064 — reentrant keyed mutation preserves index consistency and per-operation ordering

**Given** a keyed serviced local observer that performs a second keyed mutation
while handling the first
**And** local and hub deliveries are tagged by their originating operation
**When** the outer mutation triggers the reentrant mutation
**Then** every observer invocation sees ordered items, captured-key lookup, and
key-to-index state in one consistent committed state
**And** for each individual operation its local delivery precedes its hub
delivery
**And** no portable assertion requires one global interleaving order across the
outer and nested operations

## 25. HIER — HierarchicalVM (chapter 18) — spec v2.1

### HIER-001 — Recursive generic constraint compiles

**Given** a concrete subclass `MyNode : HierarchicalVM<MyModel, MyNode>`
(using per-flavor recursive-constraint idiom per ADR-0028 §3 item 2)
**When** the type is instantiated with a model and a children factory
**Then** it compiles and constructs without generic-bound errors
**And** per-flavor idiomatic naming applies (C#/Python/TypeScript/Swift conventions per ADR-0006)

### HIER-002 — `Parent` is null for root, non-null for non-root

**Given** a root node and one child node attached to it
**When** `Parent` is read on each node
**Then** the root's `Parent` is null
**And** the child's `Parent` is a reference to the root node

### HIER-003 — `Depth` derivation

**Given** a tree with root, a child at depth 1, and a grandchild at depth 2
**When** `Depth` is read on each node
**Then** the root's `Depth` is 0
**And** the child's `Depth` is 1
**And** the grandchild's `Depth` is 2

### HIER-004 — `Path` materialization and cache identity

**Given** a three-level tree (root → child → grandchild)
**When** `Path` is read on the grandchild
**Then** the returned sequence is `[root, child, grandchild]` (root-first)
**And** a second read of `Path` without any structural change returns an
identical (identity-equal in the same materialization window) sequence
**And** after the grandchild is reparented, the next read of `Path` returns
the updated sequence

### HIER-005 — `IsLeaf` and `IsRoot` derivation

**Given** a root node with two children, where each child has no children
**When** `IsRoot` and `IsLeaf` are read on each node
**Then** the root's `IsRoot` is true and `IsLeaf` is false
**And** each child's `IsRoot` is false and `IsLeaf` is true

### HIER-006 — `IsFirst` and `IsLast` position predicates

**Given** a parent with three children: A (index 0), B (index 1), C (index 2)
**When** `IsFirst` and `IsLast` are read on each child
**Then** A's `IsFirst` is true and `IsLast` is false
**And** B's `IsFirst` is false and `IsLast` is false
**And** C's `IsFirst` is false and `IsLast` is true
**And** for the root node, both `IsFirst` and `IsLast` are false

### HIER-007 — Default lazy child loading

**Given** a node constructed with the default (lazy) mode
**And** a children factory delegate that records whether it was invoked
**When** the node is constructed and `Children` has NOT been accessed yet
**Then** the children factory delegate has NOT been invoked
**When** `Children` is accessed for the first time
**Then** the children factory delegate IS invoked exactly once

### HIER-008 — Eager child loading via constructor option

**Given** a tree constructed with the `eagerChildren=true` (C# / TS) / `eager_children=True` (Python) constructor option
**And** a children factory delegate that records invocations per node
**When** the root node's `construct()` completes
**Then** the children factory has been invoked for every node in the tree
**And** all descendants are materialized without any explicit `Children` access

### HIER-009 — Depth-first construction order (eager mode)

**Given** a two-level eager tree: root with child A; A with child AA
**And** a recorder observing `ConstructionStatus == Constructed` transitions
**When** the root is constructed
**Then** AA transitions to `Constructed` before A
**And** A transitions to `Constructed` before root
**And** root transitions to `Constructed` last

### HIER-010 — `PropertyChangedMessage` on `Parent` change

**Given** a node with a message hub subscriber recording `PropertyChangedMessage`
**When** the node's `Parent` reference changes (e.g., it is reparented)
**Then** a `PropertyChangedMessage` with `PropertyName == "Parent"` is published
on the hub

### HIER-011 — `TreeStructureChangedMessage` on structural mutations

**Given** a parent node with a message hub subscriber recording
`TreeStructureChangedMessage`
**When** a child is added to the parent
**Then** a `TreeStructureChangedMessage` with `Change == Added` is published
with `Source == parent` and `Affected == child`
**When** a child is removed from the parent
**Then** a `TreeStructureChangedMessage` with `Change == Removed` is published
**When** a child is reparented to a different parent
**Then** a `TreeStructureChangedMessage` with `Change == Reparented` is published

### HIER-012 — `walk_expanded` honors lazy boundaries via `ExpandableState`

**Given** a three-level tree where the root has `ExpandableState` composed
**And** the root's `IsExpanded` is false
**When** `walk_expanded(root)` is called
**Then** only the root is yielded; its children are NOT traversed
**When** the root is expanded (IsExpanded set to true) and `walk_expanded` is called again
**Then** the root and its direct children are yielded
**And** `HierarchicalVM` does NOT auto-implement `IExpandable` (per ADR-0028 §3.6)

### HIER-013 — Composition with `SearchableState` filters materialized portion

**Given** a tree with several leaf nodes whose models have a `Name` property
**And** a `SearchableState` composed on the tree VM with a name-matching predicate
**When** a search term is set that matches only a subset of leaves
**Then** the filtered view returned by `SearchableState` contains only matching nodes
**And** un-materialized children (lazy nodes not yet accessed) are not included in results

### HIER-014 — Composition with `ModeledCrudCommands` mutates the tree

**Given** a parent node composed with `ModeledCrudCommands` targeting its `Children`
**When** `CreateNewCommand` is executed with a new model
**Then** a new child VM is added to the parent's `Children`
**And** a `TreeStructureChangedMessage` with `Change == Added` is published
**When** `DeleteCurrentCommand` is executed on an existing child
**Then** the child is removed from `Children`
**And** a `TreeStructureChangedMessage` with `Change == Removed` is published

### HIER-015 — `HierarchicalVMBuilder<M, VM>.Build()` validates required fields

**Given** a `HierarchicalVMBuilder<M, VM>` configured with `Model(m)` and
`ChildrenFactory(f)` but no `Services(hub, dispatcher)` call
**When** `.Build()` is called
**Then** a `BuilderValidationError` / `BuilderValidationException` is raised
**And** the exception message identifies `Services` (or the flavor-idiomatic name)

**Given** a builder configured with `ChildrenFactory(f)` + `Services(hub, dispatcher)`
but no `Model`
**When** `.Build()` is called
**Then** the exception message identifies `Model`

**Given** a builder configured with `Model(m)` + `Services(hub, dispatcher)` but no
`ChildrenFactory`
**When** `.Build()` is called
**Then** the exception message identifies `ChildrenFactory`

### HIER-016 — `HierarchicalVMBuilder<M, VM>` repeated identical Build calls

**Given** a `HierarchicalVMBuilder<M, VM>` `b` fully configured with `Model(m0)`,
`ChildrenFactory(f)`, `Services(hub, dispatcher)`, `Hint("h")`, `EagerChildren(true)`
**When** `nodeA = b.Build()` and `nodeB = b.Build()` are called
**Then** `nodeA` and `nodeB` are different instances
**And** `nodeA.Model == nodeB.Model == m0`, `nodeA.Hint == nodeB.Hint == "h"`
**And** both nodes' subtrees are materialized at construction time (per `EagerChildren`)

### HIER-017 — `HierarchicalVMBuilder<M, VM>` field defaults applied when not set

**Given** a `HierarchicalVMBuilder<M, VM>` configured with only the required fields
(`Model`, `ChildrenFactory`, `Services`)
**When** `.Build()` is called
**Then** `node.Hint == ""`, `node.Name == typeof(TVM).Name` (or its
flavor-idiomatic equivalent), and `node.Children` is materialized **lazily** on first
access (the default for `EagerChildren = false`)

### HIER-018 — Hierarchy mutators reject cycles and transfer atomically — spec v3.20.1

**Given** a hierarchy `root → mid → leaf`
**When** `leaf.ReparentChild(root)` is called (reparenting an ancestor under its own
descendant) or `node.ReparentChild(node)` is called (self-reparenting)
**Then** the flavor's standard invalid-operation error is raised
(`InvalidOperationException` / `ValueError` / `Error`)
**And** the tree structure is unchanged (`Parent`, `Depth`, and `Path` of every node
are as before)
**And** no `TreeStructureChangedMessage` is published

**When** the equivalent cycle is attempted through `AddChild`
**Then** it is rejected through the flavor's idiomatic failure channel with the
same no-mutation and no-message guarantees.

**When** `newParent.AddChild(child)` is called for a child owned by `oldParent`
**Then** the child is removed from `oldParent` by identity, appended once to
`newParent`, and its parent/path state points only to `newParent`
**And** one `Reparented` message is published by `newParent`

### HIER-019 — `InvalidateChildren` reloads on next access

**Given** a `HierarchicalVM` node whose `Children` have already been materialized
**When** `InvalidateChildren` is called
**And** `Children` is accessed again
**Then** the children factory is invoked again
**And** the new child list replaces the previous cache

### HIER-020 — `InvalidateChildren` on an unmaterialized node is a no-op

**Given** a `HierarchicalVM` node whose `Children` have not been materialized
**When** `InvalidateChildren` is called
**Then** the children factory is not invoked
**And** the next `Children` access still performs the first materialization

### HIER-021 — `InvalidateSubtree` invalidates materialized descendants

**Given** a materialized hierarchy with at least one materialized descendant
**When** `InvalidateSubtree` is called on the root
**Then** the root's cached child list is dropped
**And** every materialized descendant's cached child list is also dropped
**And** subsequent `Children` access re-invokes the relevant factories

### HIER-022 — Child-cache invalidation publishes property changed

**Given** a materialized `HierarchicalVM` node with a hub subscriber
**When** `InvalidateChildren` is called
**Then** a `PropertyChangedMessage` is published for the children property
**And** no `TreeStructureChangedMessage` is required for the cache refresh

### HIER-023 — Batch attachment reaches a stable child-before-parent fixpoint

**Given** an empty hierarchy root and a batch ordered `grandchild, sibling B, sibling A, parent`, where each item carries consumer-selected key and parent key
**When** the batch is attached
**Then** all four items are added without throwing
**And** the parent is below the root, both siblings are below the parent in
input order `B, A`, and the grandchild is below A
**And** existing parent, path, and structure-message invariants apply

### HIER-024 — Root sentinel attaches multiple root items in stable order

**Given** two batch items whose parent selector returns the flavor's root
sentinel (`null` / `None` or C# `BatchParentKey<TKey>.Root`)
**When** the batch is attached through any node in the hierarchy
**Then** both items become direct children of the structural root in input order

### HIER-025 — Batch keys deduplicate without replacement

**Given** same-key conflicts against a materialized node, within one batch, and
in a repeated later batch
**When** each batch is attached
**Then** the first authoritative node remains attached and identity-equal
**And** each conflict appears in `Duplicates` with
`DuplicateExistingKey` or `DuplicateBatchKey`
**And** no conflict throws, replaces a VM, or aborts later batch items

### HIER-026 — Parked orphan resolves across batches

**Given** a child whose selected parent key is not materialized
**When** it is attached with `onMissingParent = park`
**Then** it is returned as an orphan and the root's parked count increments
**When** a later batch supplies that parent
**Then** the parked child is retried before new input, attaches below the
parent, and is removed from parked state

### HIER-027 — Reject policy does not retain an orphan

**Given** a child whose selected parent key is not materialized
**When** it is attached with `onMissingParent = reject`
**Then** it is returned as an orphan with `MissingParent`
**And** it is not retained or attached when an unrelated later batch supplies
the parent

### HIER-028 — Parent-key cycles are terminal non-throwing rejections

**Given** two or more active items whose selected parent keys form a cycle
**When** the batch reaches its fixpoint
**Then** every item whose unresolved chain enters that cycle receives `Cycle`
**And** those items are neither attached, reported as missing-parent orphans,
nor parked

### HIER-029 — Batch rejection is typed and structurally atomic

**Given** an item already attached outside the target tree and a selector or
underlying attachment that fails
**When** batch attachment processes those items
**Then** it returns `AlreadyAttached`, `SelectorFailed`, or `AttachmentFailed`
as applicable instead of throwing the batch
**And** every non-added item has exactly one typed rejection
**And** an existing or partially-started parent/child link is unchanged or
rolled back before return

### HIER-030 — Root disposal clears parked batch state

**Given** a structural root with one or more parked missing-parent items
**When** the root is disposed
**Then** its parked count becomes zero
**And** repeated disposal remains safe under the general disposal invariant

## 26. DIA — IDialogService (chapter 19) — spec v2.1

### DIA-001 — `PickFileToOpen` contract

**Given** an `IDialogService` implementation
**And** an optional `FileFilter` with description and extensions, and an optional title
**When** `PickFileToOpen(filter, title)` is called
**Then** it returns an awaitable that resolves to either a non-null path string (user
selected a file) or `null` (user cancelled or no file was chosen)
**And** all parameters are optional (calling with no arguments is valid)

### DIA-002 — `PickFileToSave` contract

**Given** an `IDialogService` implementation
**And** optional `FileFilter`, optional title, and optional `suggestedName`
**When** `PickFileToSave(filter, title, suggestedName)` is called
**Then** it returns an awaitable that resolves to either a non-null path string (user
confirmed a save path) or `null` on cancel
**And** all parameters are optional (calling with no arguments is valid)

### DIA-003 — `Confirm` contract

**Given** an `IDialogService` implementation
**And** a non-null message string and an optional title
**When** `Confirm(message, title)` is called
**Then** it returns an awaitable that resolves to `true` when the user confirms
**And** resolves to `false` when the user cancels or dismisses the prompt
**And** the title parameter is optional (calling with only message is valid)

### DIA-004 — `Notify` contract

**Given** an `IDialogService` implementation
**And** a non-null message string, an optional title, and an optional severity
**When** `Notify(message, title, severity)` is called with severity in
`{Info, Warning, Error}`
**Then** it returns an awaitable that completes without error
**And** severity defaults to `Info` when not supplied
**And** all optional parameters may be omitted

### DIA-005 — `NullDialogService` null-object behavior

**Given** a `NullDialogService` instance (per ADR-0017)
**When** `PickFileToOpen()` is awaited
**Then** the result is `null`
**When** `PickFileToSave()` is awaited
**Then** the result is `null`
**When** `Confirm("any message")` is awaited
**Then** the result is `false`
**When** `Notify("any message")` is awaited
**Then** the awaitable completes without error and without side-effects

### DIA-006 — Reentrancy is implementation-defined

**Given** a queueing `IDialogService` implementation that serialises concurrent calls
**When** two `Confirm` calls are made concurrently
**Then** both awaitables eventually resolve with valid values (`true` or `false`)
**And** neither call raises an exception due to reentrancy

**Given** an immediate-rejecting `IDialogService` implementation
**When** a second `Confirm` call is made while the first is still pending
**Then** the second call resolves immediately with `false` (safe default)
**And** no exception is raised
**And** the first call continues to completion unaffected

### DIA-007 — Cancellation completes with safe default, does not throw

The `IDialogService` contract does not include a cancellation parameter; this
scenario applies to implementations that opt into a cancellation channel
(e.g., a custom subtype that adds a `CancellationToken` / `AbortSignal`
overload, or a host that disposes the awaiting context).

**Given** an opt-in cancellable dialog implementation
**And** a cancellation signal that fires before or during the dialog
**When** the file-pick await is cancelled
**Then** the awaitable completes with `null` (no file chosen)
**And** no cancellation exception is raised by the awaitable itself
**When** the confirm await is cancelled
**Then** the awaitable completes with `false`
**And** no cancellation exception is raised

### DIA-008 — `ConfirmationDecoratorCommand` integration

**Given** an `ICommand` inner command
**And** an `IDialogService` instance
**When** `innerCommand.Confirm(() => dialogService.Confirm("Proceed?"))` is called
(or the fluent `innerCommand.Confirm(dialogService, "Proceed?")` overload)
**Then** the result is a valid `ICommand` whose `CanExecute` delegates to the inner
command and whose `Execute` first awaits the dialog's `Confirm` result
**And** the inner command is only executed when `Confirm` returns `true`
**And** the inner command is NOT executed when `Confirm` returns `false`

### DIA-009 — VM-backed modal presentation returns the modal result

**Given** a modal VM with a cancellation result
**And** a modal-capable dialog service whose host chooses result `r`
**When** `Present(modal)` is awaited
**Then** the awaitable resolves to `r`
**And** the modal's `Result` is `r`

### DIA-010 — Null modal presentation resolves with cancellation result

**Given** a `NullDialogService`
**And** a modal VM with cancellation result `c`
**When** `Present(modal)` is awaited
**Then** the awaitable resolves to `c`
**And** the modal is dismissed with result `c`

### DIA-011 — Modal disposal completes with cancellation result

**Given** a modal VM with cancellation result `c`
**When** the modal is disposed before a host result is chosen
**Then** the modal's completion awaitable resolves to `c`
**And** the modal is dismissed

### DIA-012 — Modal dismissal is idempotent

**Given** a modal VM
**When** `Dismiss(first)` is called
**And** `Dismiss(second)` is called later
**Then** the modal completion resolves to `first`
**And** the stored result remains `first`

### DIA-013 — Existing dialog methods remain source-compatible

**Given** a `NullDialogService` consumed through the existing dialog-service surface
**When** `PickFileToOpen`, `PickFileToSave`, `Confirm`, and `Notify` are called
**Then** they retain their existing names, parameters, and null-object return values

## 27. FORM — FormVM (chapter 20) — spec v2.1

### FORM-001 — Snapshot captured at construct

**Given** a `FormVM<TM>` constructed with an initial model `m0` and a no-op persister
**When** `Snapshot` and `Model` are read immediately after construction
**Then** `Snapshot == m0` (structurally equal to the initial value)
**And** `Model == m0`
**And** `IsDirty == false`

### FORM-002 — Model mutation reflected in `IsDirty`

**Given** a `FormVM<TM>` with initial model `m0`
**When** `Model` is updated to a structurally different value `m1`
**Then** `IsDirty == true`
**And** `Model` equals `m1`
**And** `Snapshot` still equals `m0` (unchanged)

### FORM-003 — `IsDirty` derivation via structural inequality

**Given** a `FormVM<TM>` with initial model `m0`
**When** `Model` is updated to a value `m1` that is structurally equal to `m0`
(same fields/values, different object reference if applicable)
**Then** `IsDirty == false` (equal values are not dirty)
**When** `Model` is updated to a value `m2` that differs from `m0` in at least one field
**Then** `IsDirty == true`

**Note** (v3, ADR-0048/ADR-0077; supersedes the ADR-0037 caveat): structural
equality is evaluated by each flavor's chapter 20 §4 mechanism — `object.Equals`
(C#), `__eq__` (Python), TypeScript's default structural deep-equal, and Swift's
`==` for `Equatable` models (with injectable `equals` for custom semantics).
The pre-v3 TypeScript `JSON.stringify` comparison was key-order sensitive and
crashed on `BigInt`/circular models; the v3 default deep-equal is order-insensitive
and handles `Date`/`Map`/`Set`/`BigInt`/circular references. TypeScript binary
buffers and views compare by concrete constructor and visible bytes (ADR-0113),
so the equal-values guarantee holds for value-equality-capable models in all
full-parity flavors.
Consumers needing field-subset or reference semantics inject a custom `equals`
(TypeScript/Swift) or define their model's own equality (C#/Python).

### FORM-004 — `DenyCommand` reverts `Model` to `Snapshot`

**Given** a `FormVM<TM>` with initial model `m0`
**And** `Model` has been updated to a different value `m1` (so `IsDirty == true`)
**When** `DenyCommand.Execute()` is called
**Then** `Model` is restored to a value structurally equal to `Snapshot`
**And** `IsDirty == false`
**And** the persister is NOT invoked

### FORM-005 — `ApproveCommand` invokes persister; snapshot advances on success

**Given** a `FormVM<TM>` with initial model `m0` and a persister that records its argument
**And** `Model` has been updated to `m1`
**When** `ApproveAsync()` is awaited and the persister succeeds
**Then** the persister was called with `m1`
**And** `Snapshot` is updated to a value structurally equal to `m1`
**And** `IsDirty == false` after the approve completes

### FORM-006 — `OnApproved` fires only after successful persist

**Given** a `FormVM<TM>` with a subscriber to `OnApproved`
**And** `Model` has been updated to `m1`
**When** `ApproveAsync()` is awaited and the persister succeeds
**Then** `OnApproved` fires exactly once with the persisted value — the model
captured before the persister await (`m1`), uniform across flavors (chapter 20 §8.2;
a `SetModel` racing the in-flight persist does not change the emitted value —
ADR-0048)

**Given** a persister that throws an exception
**When** `ApproveAsync()` is awaited
**Then** `OnApproved` does NOT fire

### FORM-007 — Persist failure leaves state unchanged

**Given** a `FormVM<TM>` with a persister that throws `InvalidOperationException`
**And** `Model` has been updated to `m1` (so `IsDirty == true`)
**And** `Snapshot` equals `m0`
**When** `ApproveAsync()` is awaited and the persister throws
**Then** `Snapshot` is still `m0` (unchanged)
**And** `Model` is still `m1` (unchanged)
**And** `IsDirty` is still `true`
**And** the awaitable surfaces the exception to the caller (the exception
is observable via the awaitable entry-point only; `ApproveCommand.Execute()`
dispatches the persist call fire-and-forget per chapter 20 §2)

### FORM-008 — Hub messages on revert

**Given** a `FormVM<TM>` connected to a message hub
**And** `Model` has been updated to `m1`
**And** subscribers are recording `FormRevertedMessage` and `PropertyChangedMessage`
**When** `DenyCommand.Execute()` is called
**Then** exactly one `FormRevertedMessage` is published with `Sender == formVm`
**And** exactly one model `PropertyChangedMessage` is published after it, with
the flavor-idiomatic property name (`"Model"` in C#; `"model"` in Python,
TypeScript, Swift, and Rust)

### FORM-009 — Strict mode: `ApproveCommand.CanExecute` gates on `IsDirty`

**Given** a `FormVM<TM>` constructed with `strict = true`
**When** `IsDirty == false` (no mutations since last snapshot)
**Then** `ApproveCommand.CanExecute()` returns `false`
**When** `Model` is updated to a structurally different value (so `IsDirty == true`)
**Then** `ApproveCommand.CanExecute()` returns `true`

**Given** a `FormVM<TM>` constructed with `strict = false` (default)
**When** `IsDirty == false`
**Then** `ApproveCommand.CanExecute()` returns `true` (consumer-controlled)

### FORM-010 — Integration with `IDialogService.Confirm`

**Given** a `FormVM<TM>` with `Model` updated to `m1` (dirty)
**And** a `NullDialogService` (whose `Confirm` always returns `false`)
**And** a confirmation-decorated deny command:
`confirmedDeny = denyCommand.Confirm(() => dialogService.Confirm("Discard changes?"))`
**When** `confirmedDeny.Execute()` is called
**Then** `Confirm` on the dialog service is called
**And** because it returns `false`, `DenyCommand.Execute()` is NOT invoked
**And** `Model` is still `m1` (not reverted)
**And** `IsDirty` is still `true`

### FORM-011 — `FormVMBuilder<TM>.Build()` validates required `Initial` + `Persister`

**Given** a `FormVM<TM>.Builder()` with only `Initial(m)` set (no `Persister`)
**When** `.Build()` is called
**Then** a `BuilderValidationError` / `BuilderValidationException` is raised
**And** the exception message identifies `Persister` (or the flavor-idiomatic name)

**Given** a `FormVM<TM>.Builder()` with only `Persister(p)` set (no `Initial`)
**When** `.Build()` is called
**Then** a `BuilderValidationError` / `BuilderValidationException` is raised
**And** the exception message identifies `Initial`

### FORM-012 — `FormVMBuilder<TM>` repeated identical Build calls

**Given** a `FormVMBuilder<TM>` `b` fully configured with `Initial(m0)`, `Persister(p)`,
optional `Strict(true)`, `Hub(hub)`, `Snapshotter(s)`
**When** `formA = b.Build()` and `formB = b.Build()` are called
**Then** `formA` and `formB` are different instances
**And** `formA.Model == formB.Model == m0`, `formA.Snapshot == formB.Snapshot == s(m0)`
**And** `formA.IsDirty == formB.IsDirty == false`

### FORM-013 — `FormVMBuilder<TM>` field defaults applied when not set

**Given** a `FormVMBuilder<TM>` configured with only `Initial(m0)` + `Persister(p)`
**When** `.Build()` is called
**Then** `form.Hub == NullMessageHub` (singleton equivalent for the flavor)
**And** `form.Snapshot == m0` (the flavor default snapshotter is applied — chapter 20 §3)
**And** `form.ApproveCommand.CanExecute() == true` regardless of `IsDirty`
(strict defaults to `false`)

### FORM-014 — Disposed form is inert

**Given** a `FormVM` whose persister records its invocations, with
`Model != Snapshot` (dirty)
**When** `Dispose()` is called and then `ApproveCommand` (or the awaitable
approve entry point) and `DenyCommand` are executed
**Then** the persister is never invoked
**And** `Model` retains its pre-dispose value (no revert)
**And** no exception is raised

*(Added in v2.5.0 via ADR-0038 — the guards shipped as v2.5.0 maintenance;
this ID pins them normatively.)*

### FORM-015 — `ApproveCommand` surfaces persister failure on `ApproveErrors`

**Given** a `FormVM<TM>` whose persister rejects/throws an error `e`
**And** a subscriber to `ApproveErrors`
**And** `Model` has been updated to `m1` (so `IsDirty == true`)
**When** `ApproveCommand.Execute()` is invoked (the fire-and-forget command path)
**Then** the error `e` is emitted on `ApproveErrors` (it is not swallowed with the
discarded faulted task)
**And** no state is mutated: `Snapshot` is unchanged and `IsDirty` is still `true`
**And** `OnApproved` does not fire

*(Added in v3 via ADR-0048. The awaitable `ApproveAsync()` path keeps its
throw-to-the-awaiter behavior — FORM-007 — and emits nothing on `ApproveErrors`;
this ID pins the command-path error channel, chapter 20 §2/§8.)*

### FORM-016 — Field validator populates field error

**Given** a `FormVM<TM>` constructed with a field validator for field `f`
**When** the current model fails that validator
**Then** `FieldError(f)` returns the validator's string error
**And** `Errors[f]` contains the same error

### FORM-017 — Model validator populates errors

**Given** a `FormVM<TM>` constructed with a model validator
**When** the validator returns a field-name keyed error map
**Then** `Errors` contains those field errors

### FORM-018 — `IsValid` reflects errors

**Given** a `FormVM<TM>` whose validators produce one or more errors
**Then** `IsValid == false`
**And** when the effective `Errors` map is empty, `IsValid == true`

### FORM-019 — Invalid form blocks approval

**Given** an invalid `FormVM<TM>` whose persister records invocations
**When** `ApproveCommand.CanExecute` is queried
**Then** it returns `false`
**When** the awaitable approve entry point is called
**Then** the persister is not invoked

### FORM-020 — Validation reruns after model mutation

**Given** a `FormVM<TM>` whose current model has validation errors
**When** `SetModel` replaces it with a valid model
**Then** `Errors` becomes empty
**And** `IsValid == true`

### FORM-021 — `ErrorsChanged` fires only on effective changes

**Given** a `FormVM<TM>` with a subscriber to `ErrorsChanged`
**When** `SetModel` changes the model but produces the same effective errors
**Then** no error-change event is emitted
**When** `SetModel` changes the effective error map
**Then** exactly one fresh error map is emitted for that change

### FORM-022 — `FormVMBuilder<TM>` registers validators immutably

**Given** a configured `FormVM<TM>.Builder()`
**When** `Validator(field, fn)` is called
**Then** a new builder instance is returned
**And** the original builder is unchanged
**And** the new builder constructs a form that applies the validator

### FORM-023 — Clearing errors enables approval when other gates pass

**Given** a strict `FormVM<TM>` with validation errors
**When** `SetModel` changes the model so validation passes and the form is dirty
**Then** `ApproveCommand.CanExecute == true`

### FORM-024 — reset runs after persistence and before approval notification

**Given** a form configured with `resetOnApproved`, a recording persister, and
an `OnApproved` subscriber
**And** the model is changed from `m0` to `m1`
**When** approval succeeds
**Then** the observable order is persist `m1`, reset callback with `m1`, then
`OnApproved(m1)`
**And** the subscriber observes the live model and snapshot already equal to the
reset value with `IsDirty == false`

### FORM-025 — reset integrates with snapshotting, validation, and strict mode

**Given** a strict form with a configured snapshotter, validators, and
`resetOnApproved`
**When** approval succeeds and the callback returns reset value `r`
**Then** the snapshotter is invoked twice for `r`
**And** `Model` and `Snapshot` are independent snapshotter outputs structurally
equal to `r`
**And** validation reflects `r`, `IsDirty == false`, and approval is disabled

### FORM-026 — reset failure is post-persist, atomic, and singly observed

**Given** a reset callback that fails with error `e`
**When** the awaitable approval path is used
**Then** persistence has occurred exactly once, reset state is not committed,
`OnApproved` does not fire, `e` reaches the awaiter, and `ApproveErrors` remains
silent
**When** the same scenario is invoked through the fire-and-forget approve
command on a fresh form
**Then** `e` is emitted exactly once on `ApproveErrors` and nowhere else

### FORM-027 — reset is skipped without successful approval

**Given** forms configured with `resetOnApproved`
**When** approval is blocked by validation, persistence fails or is cancelled,
or deny/revert is invoked
**Then** the reset callback is not invoked

### FORM-028 — disposal during persistence suppresses reset

**Given** approval whose persistence is in flight
**When** the form is disposed before persistence completes
**And** persistence later succeeds
**Then** the reset callback does not run
**And** no post-persist state mutation or approval notification occurs

### FORM-029 — reset is authoritative over a racing model mutation

**Given** approval captured model `m1` and its persistence is in flight
**When** `SetModel(m2)` races before persistence completes
**And** persistence succeeds
**Then** the persister, reset callback, and `OnApproved` payload use `m1`
**And** the live model and snapshot become the reset derived from `m1`, replacing
the racing `m2`, with `IsDirty == false`

> Spec: `20-form-vm.md §5.1`, ADR-0087.

### FORM-030 — unequal model assignment publishes one settled hub message

**Given** a strict `FormVM<TM>` with observable validation/errors,
`ApproveCommand.CanExecuteChanged`, and an injected hub
**When** `SetModel` accepts a candidate unequal to the live model under the
form's configured or idiomatic equality
**Then** it installs the candidate, settles validation/errors and command state,
and publishes exactly one flavor-idiomatic model `PropertyChangedMessage`
**And** a synchronous hub subscriber observes the accepted model, errors,
validity, dirty state, and command state already settled

**When** that subscriber re-enters `SetModel` with another unequal value
**Then** each accepted call publishes exactly once and the nested value is the
final settled state
**But when** a distinct candidate is equality-equal to the live model
**Then** the current model is retained and no validator, command, or notification
work occurs

**And** assignment after disposal remains a complete no-op under `DISP-014`
**And** the null/default hub path settles an unequal edit without error
**And** deny publishes exactly `FormRevertedMessage` then one idiomatic model
property message, with no duplicate
**And** `resetOnApproved` retains its existing outcome channels without a model
property message

> Spec: `20-form-vm.md §5.2/§8`, ADR-0092.

## 28. DISC — DiscriminatorVM (chapter 22) — spec v3.1

### DISC-001 — Initial active key and `IsActive`

**Given** a `DiscriminatorVM<TKey>` constructed with initial key `k0`
**Then** `ActiveKey == k0`
**And** `IsActive(k0) == true`
**And** `IsActive(other) == false`

### DISC-002 — Changing active key emits once

**Given** a `DiscriminatorVM<TKey>` with a subscriber to `ActiveChanged`
**When** `SetActiveKey(k1)` is called with `k1 != ActiveKey`
**Then** `ActiveKey == k1`
**And** the subscriber observes exactly one emission carrying `k1`

### DISC-003 — Setting the same key is a no-op

**Given** a `DiscriminatorVM<TKey>` with active key `k0`
**And** a subscriber to `ActiveChanged`
**When** `SetActiveKey(k0)` is called
**Then** no change is emitted

### DISC-004 — Modal open activates modal key

**Given** a `DiscriminatorVM<TKey>` with active key `k0`
**When** `ModalOpen(modalKey)` is called
**Then** `ActiveKey == modalKey`
**And** `IsActive(modalKey) == true`

### DISC-005 — Modal close restores prior key

**Given** a `DiscriminatorVM<TKey>` with active key `k0`
**And** `SetActiveKey(k1)` has been called
**When** `ModalOpen(modalKey)` is called
**And** `ModalClose()` is called
**Then** `ActiveKey == k1`

### DISC-006 — Nested modal precedence restores in LIFO order

**Given** a `DiscriminatorVM<TKey>` with active key `k0`
**When** `ModalOpen(a)` then `ModalOpen(b)` are called
**And** `ModalClose()` is called once
**Then** `ActiveKey == a`
**When** `ModalClose()` is called again
**Then** `ActiveKey == k0`

## 29. THEME — Theme as a VM concern (spec v2.4 scenario contract)

The `THEME-NNN` family covers the **scenario contract** at
`spec/proposals/2026-06-02-theme-vm-scenario.md` (ADR-0036 §2.C). This contract
specifies a normative *shape* for example-app theming — a `ThemeModel` +
`ThemeVM : ComponentVM<ThemeModel>` + per-framework `ThemeAdapter` — built
from existing core primitives (`ComponentVM<M>`, `DerivedProperty<T>`,
`RelayCommand`, `MessageHub`). No new core types are introduced.

Scenarios are normative for any flavor or example app that implements the
contract; flavors that do not host an example-app theming surface are NOT
required to provide coverage. Verbatim from the proposal §6.

### THEME-001 — `setThemeCommand.execute("dark")` publishes `ThemeChangedMessage` exactly once; `currentTheme.value.name == "dark"`; `currentTheme.value.accentColor` equals the "dark" preset's accent

**Given** a `ThemeVM` constructed with the three named presets
(`"dark"`, `"light"`, `"high-contrast"`) and a hub subscriber filtered on
`ThemeChangedMessage`
**When** `setThemeCommand.execute("dark")` is called
**Then** the subscriber observes exactly one `ThemeChangedMessage` with
`curr.name == "dark"` and `curr.accentColor` equal to the configured "dark"
preset's `accentColor`
**And** `currentTheme.value.name == "dark"`

### THEME-002 — `setThemeCommand.execute("unknown-preset")` raises `BuilderValidationError` (or flavor-idiomatic exception) without publishing a message

**Given** a `ThemeVM` configured with only the three named presets and a hub
subscriber filtered on `ThemeChangedMessage`
**When** `setThemeCommand.execute("unknown-preset")` is called
**Then** a `BuilderValidationError` / `BuilderValidationException` /
`ValueError` (flavor-idiomatic) is raised
**And** the subscriber observes zero `ThemeChangedMessage` emissions
**And** `currentTheme.value` is unchanged from its pre-call value

### THEME-003 — `toggleHighContrast` toggles `currentTheme.value.highContrast` without changing accent or scale

**Given** a `ThemeVM` whose `currentTheme.value` has
`highContrast == false`, `accentColor == "#1F6FEB"`, `fontScaleFactor == 1.0`
**When** `toggleHighContrast.execute()` is called
**Then** `currentTheme.value.highContrast == true`
**And** `currentTheme.value.accentColor == "#1F6FEB"` (unchanged)
**And** `currentTheme.value.fontScaleFactor == 1.0` (unchanged)
**When** `toggleHighContrast.execute()` is called a second time
**Then** `currentTheme.value.highContrast == false` (flipped back)

### THEME-004 — `setFontScale(value)` clamps to `[0.75..1.75]` and publishes a single `ThemeChangedMessage`; values outside the range result in clamped emission, not rejection

**Given** a `ThemeVM` with `currentTheme.value.fontScaleFactor == 1.0` and a
hub subscriber filtered on `ThemeChangedMessage`
**When** `setFontScale.execute(0.5)` is called
**Then** the subscriber observes exactly one `ThemeChangedMessage`
**And** `currentTheme.value.fontScaleFactor == 0.75` (clamped to lower bound)
**When** `setFontScale.execute(3.0)` is called
**Then** the subscriber observes a second `ThemeChangedMessage`
**And** `currentTheme.value.fontScaleFactor == 1.75` (clamped to upper bound)
**When** `setFontScale.execute(1.25)` is called
**Then** `currentTheme.value.fontScaleFactor == 1.25` (in-range, unclamped)

### THEME-005 — `followSystemCommand.execute()` sets `followSystem=true` and re-reads the host's current theme; calling `setThemeCommand.execute("dark")` afterward sets `followSystem=false` automatically

**Given** a `ThemeVM` whose `currentTheme.value.followSystem == false`
**When** `followSystemCommand.execute()` is called
**Then** `currentTheme.value.followSystem == true`
**And** `currentTheme.value.name` equals the host-derived system theme name
(e.g., `"dark"` when the host reports a dark color scheme)
**When** `setThemeCommand.execute("dark")` is called afterward
**Then** `currentTheme.value.followSystem == false`
**And** `currentTheme.value.name == "dark"`

## 30. Cross-cutting disposal (`DISP-NNN`) — spec v3.4

These IDs top up the existing type-specific disposal coverage. They apply to
public VMx-owned types that expose `Dispose()` / `dispose()`; they do not add a
disposal member to types that do not otherwise own disposable resources.

### DISP-001 — VM disposal and owned cascades are observably idempotent

**Given** a parent VM with at least one child and observers of terminal lifecycle changes
**When** the parent is disposed twice
**Then** the parent and each child reach `Disposed`
**And** each publishes exactly one terminal `Disposed` transition
**And** each owned disposal hook or side effect runs at most once

### DISP-002 — command disposal cancels one in-flight operation once

**Given** an `AsyncRelayCommand` whose operation is in flight
**When** the command is disposed twice
**Then** the operation observes one cancellation
**And** the command returns to a non-executing terminal state
**And** later execution attempts are inert
**And** no terminal/error channel is completed more than once

### DISP-003 — concurrent disposal of a thread-safe hub performs terminal work once

**Given** a thread-safe notification or message hub with an in-flight waiter and terminal observer
**When** multiple callers race to dispose the hub
**Then** exactly one caller claims terminal teardown
**And** the waiter resolves with the hub's documented safe result
**And** completion or terminal snapshot publication occurs exactly once

For flavors whose hub contract is single-threaded, a re-entrant disposal call
MUST satisfy the same at-most-once observable result; this ID does not add a
thread-safety guarantee to that flavor.

### DISP-004 — interaction-owner disposal completes once and preserves the first result

**Given** disposable form, modal, or notification interaction owners
**When** an owner is disposed twice, including after an interaction already resolved
**Then** each owned completion surface completes at most once
**And** a modal or notification keeps its first terminal result
**And** a disposed form retains its documented inert post-dispose behavior

### DISP-005 — reactive-helper disposal completes once and retains documented readable state

**Given** a disposable derived property or state helper with a current value and subscriber
**When** the helper is disposed twice and its former source changes
**Then** its completion surface completes at most once
**And** it emits no post-dispose value
**And** any last-value read documented by that helper still returns the retained value

### DISP-006 — collection and projection helper disposal performs one terminal transition

**Given** a disposable batch, paging, collection, or filtered-projection helper
**When** its disposal handle or helper is disposed twice
**Then** batch exit, reset/completion, or projection freezing occurs at most once
**And** later source or suspended-load activity follows that helper's documented
post-dispose behavior without a second terminal side effect

### DISP-007 — owned resources are released in reverse registration order

**Given** a VM with at least three disposal-lifetime resources registered through
the flavor's owned-resource helper, including each accepted resource shape
**When** the VM is disposed
**Then** the resources are released exactly once in LIFO order

### DISP-008 — repeated VM disposal releases each owned resource once

**Given** a VM with one registered disposal-lifetime resource
**When** the VM is disposed more than once
**Then** the resource cleanup runs exactly once

### DISP-009 — one owned-resource cleanup failure does not escape or stop later cleanup

**Given** registered resources whose LIFO sequence contains a cleanup that fails
**When** the VM is disposed
**Then** the failure is swallowed
**And** every other registered cleanup still runs once in LIFO order

### DISP-010 — registration after disposal cleans immediately once

**Given** a disposed VM
**When** a resource is registered through the owned-resource helper
**Then** its cleanup runs immediately exactly once
**And** a later repeated VM disposal performs no second cleanup

### DISP-011 — disposal-lifetime resources survive reconstruct

**Given** a constructed VM with a registered disposal-lifetime resource
**When** the VM is reconstructed
**Then** the resource is not cleaned
**When** the VM is later disposed
**Then** the resource is cleaned exactly once

### DISP-012 — the injected hub is publicly visible and read-only

**Given** a VM built with an injected message hub
**When** a consumer reads the VM's baseline hub member
**Then** it is the same injected hub instance
**And** the baseline exposes no hub setter

### DISP-013 — VM disposal does not dispose its shared hub

**Given** a VM and another consumer sharing one injected message hub
**When** the VM is disposed
**Then** the other consumer can still send through the hub

### DISP-014 — Modeled assignment after disposal is inert

**Given** a modeled component and a form with observable equality, hinting or
validation, callbacks, retained state, and notification or command signals
**When** each VM is disposed and a late completion attempts modeled assignment
**Then** the attempt performs none of that work
**And** every retained value and signal remains unchanged

## 31. Dynamic aggregate change stream (`AGCH-NNN`) — spec v3.18

These cases verify ADR-0098 and `spec/21-collections.md` §9. Across the family,
each flavor MUST exercise normal VM collections, unkeyed serviced collections,
and keyed serviced collections. Counted selectors and subscriptions are used
instead of timing-based leak assertions.

### AGCH-001 — optional initial delivery is atomic and subscriber-local

**Given** an aggregate over current members with one observer that requests an
initial event and another that does not
**When** each observer subscribes, including a structural or item change racing
the requesting observer's registration
**Then** the requesting observer receives exactly one `Initial` before every
later change admitted for it
**And** the other observer receives no `Initial`
**And** neither observer receives replayed history or a synthetic revision,
snapshot, or global initial event

### AGCH-002 — structural delivery follows committed membership resynchronization

**Given** an aggregate whose structural source is observed before its first
snapshot
**When** a structural pulse races initial setup
**Then** reconciliation repeats as needed and construction commits the latest
complete ordered membership
**And** construction emits no replayable `Membership`; optional
subscriber-local `Initial` represents readiness
**When** Add, Remove, Replace, or another structural pulse changes membership
after construction
**Then** every current distinct identity is observed and every zero-refcount
identity is detached before exactly one `Membership` is delivered
**And** a staged synchronous value during later reconciliation is queued behind
`Membership`, while one during initial construction is discarded as
pre-existing state

### AGCH-003 — current selected changes carry item identity

**Given** an aggregate with a current member whose selector observes that
member or nested member state
**When** the selected stream emits
**Then** exactly one aggregate envelope has reason `Item`
**And** its item is the identical current member whose selected stream emitted
**And** no membership snapshot, revision, or domain value is synthesized

### AGCH-004 — zero-refcount and terminal membership epochs are silent

**Given** an aggregate observing current distinct identities with counted item
subscriptions
**When** an identity is removed or replaced until its refcount reaches zero
**Then** its item subscription is detached before the corresponding
`Membership` event and later callbacks from that epoch produce no `Item`
**But when** Replace retains the same identity at positive refcount
**Then** its existing epoch and subscription remain active
**When** a current selected stream completes, or unexpectedly errors in an Rx
flavor
**Then** only that identity's current positive-refcount epoch terminates,
without an aggregate event or failure of the aggregate or other members
**And** Move, identity-retaining Reset, and duplicate add do not resubscribe it
**And** only final removal followed by re-add creates one fresh subscription
and epoch

### AGCH-005 — Reset rebuilds membership transactionally

**Given** an aggregate whose source can replace or clear its contents with a
Reset notification
**When** Reset changes the ordered identity multiset
**Then** the aggregate resnapshots and transactionally installs every new
distinct member before one `Membership` event
**And** retained identities keep their epochs and subscriptions
**And** removed identities detach without leaks while newly current identities
are not missed

### AGCH-006 — duplicate identities share one refcounted subscription

**Given** the same reference identity, or Rust logical VM ID, appears more than
once in a source snapshot
**When** the aggregate reconciles that membership and the selected stream emits
**Then** the selector is subscribed exactly once and exactly one `Item` event is
delivered
**When** one occurrence is removed
**Then** the subscription remains active
**When** the final occurrence is removed
**Then** that one subscription is detached before `Membership`

### AGCH-007 — nested exceptional batches emit one final batch without masking failure

**Given** an aggregate with nested explicit batch scopes
**When** structural and item changes are admitted at multiple depths and the
body then fails
**Then** no intermediate aggregate envelope escapes the scopes
**And** the outermost exit emits exactly one `Batch`
**And** every batch depth is closed and the original body failure propagates
unchanged
**When** delivery of that final `Batch` also throws synchronously from a
subscriber
**Then** the delivery exception is suppressed and the original body failure
still propagates unchanged
**But when** the body succeeds and final `Batch` delivery throws
**Then** the failure follows the host reactive convention without implying
general subscriber isolation
**And** after exceptional cleanup, a later outside change with nonthrowing
delivery publishes normally

### AGCH-008 — empty batches and Move preserve silence or subscription stability

**Given** an aggregate with counted subscriptions and an explicit batch scope
**When** a batch admits no change
**Then** it emits no `Batch` or other envelope
**When** a change dirties a batch before a new subscriber joins
**Then** the early subscriber receives the final `Batch` and the late subscriber
receives no historical envelope
**But when** another change is admitted after the late subscriber joins
**Then** both still-active subscribers receive the one final `Batch`
**When** a Move reorders a current identity without changing the identity
multiset
**Then** one `Membership` event reflects the committed order
**And** the moved identity keeps its existing epoch and selected subscription
without detach or resubscribe

### AGCH-009 — reentrant FIFO delivery rejects stale epochs

**Given** an aggregate observer that performs a reentrant membership mutation
while handling an aggregate envelope
**And** an item callback from an epoch can already be queued
**When** the reentrant mutation removes that identity to zero refcount and MAY
later re-add it
**Then** reentrant work appends behind the current envelope in serialized FIFO
order and every observer sees committed membership bookkeeping
**And** queued item work from the removed epoch is discarded
**And** a re-add receives a fresh epoch, so no stale callback is attributed to
the new membership

### AGCH-010 — failure, disposal, ownership, and subscriber behavior are bounded

**Given** aggregate construction or later reconciliation encounters a null
member or a selector/subscription failure
**When** the failure occurs
**Then** counted structural, staged-item, and previously admitted-item
subscriptions all detach exactly once before construction throws or before the
existing output receives the same terminal error
**And** construction returns no aggregate, while later failure makes the
aggregate inert according to the host reactive convention
**And** no partial membership containing a live but unobserved current member is
committed
**Given** a valid aggregate with lifecycle-observable source items and multiple
output subscribers
**When** the aggregate is disposed repeatedly
**Then** structural and item subscriptions detach once, output completes at
most once where supported, and later source activity is inert
**And** no item is constructed, destructed, disposed, reparented, removed, or
otherwise owned by the aggregate
**When** an output subscriber fails
**Then** membership bookkeeping and unrelated item subscriptions remain valid
beyond only the host reactive primitive's documented subscriber behavior
**And** message-hub subscriber isolation is not implied

## 32. Async resource viewmodel (`ARES-NNN`) — spec v3.20

### ARES-001 — Initial state and command eligibility

**Given** a newly created async resource VM
**Then** its immutable state is `Idle` with no value or error
**And** load is enabled while reload and cancel are disabled
**And** no loader call or state notification occurred during construction

### ARES-002 — Successful load publishes one ready state

**Given** an idle async resource VM and observers of its ordinary local and hub
property-change surfaces
**When** load starts and the current loader succeeds with a value
**Then** state progresses from `Loading` to `Ready(value)`
**And** each visible transition publishes exactly one ordinary idiomatic state
property pair
**And** reload is enabled while load and cancel are disabled after success

### ARES-003 — Loader failure has one presentation-state route

**Given** an idle async resource VM whose loader fails with a non-cancellation
error
**When** load is awaited or invoked through its fire-and-forget command
**Then** state becomes `Error` with that host error and no value
**And** the awaitable completes normally
**And** the same loader error is not also emitted by the async command error
channel
**And** reload is enabled for retry

### ARES-004 — Retry replaces error with ready

**Given** an async resource VM in `Error` after a failed load
**When** reload starts and its current loader succeeds
**Then** state progresses through `Loading` to `Ready(newValue)`
**And** the prior error is absent from both later snapshots

### ARES-005 — Initial cancellation restores idle

**Given** an initial load in progress with observed idiomatic cancellation
**When** cancel is invoked, including through the cancel command
**Then** the loader receives cancellation and the current state returns to
`Idle`
**And** no error state or async-command error is emitted
**And** repeated cancel while idle is inert

### ARES-006 — Retained reload exposes and restores the previous value

**Given** a retain-previous VM in `Ready(oldValue)`
**When** reload starts
**Then** `Loading` carries `oldValue`
**When** that current reload is cancelled
**Then** state restores `Ready(oldValue)` without cleaning it
**When** a later reload fails
**Then** `Error` carries `oldValue` and the current host error

### ARES-007 — Discard reload relinquishes the previous value at start

**Given** a default discard-previous VM in `Ready(oldValue)` with cleanup
**When** reload starts
**Then** `oldValue` is cleaned exactly once before value-less `Loading` is
observable
**And** cancellation restores `Idle`
**And** a later current failure is a value-less `Error`

### ARES-008 — Overlapping starts are latest-start-wins

**Given** an operation in `Loading`
**When** reload admits a newer operation before the older loader settles
**Then** the older loader receives cancellation and the newer identity is current
**When** both loaders later settle in either order
**Then** only the newer success or failure determines the final state
**And** the older completion causes no state or command notification

### ARES-009 — Stale success is cleaned without publication

**Given** cleanup and an older loader that returns a value despite cancellation
**When** a newer operation has already become current or completed
**Then** the stale returned ownership unit is cleaned exactly once
**And** it is never exposed by state, installed as stable state, or represented
by a property/command notification

### ARES-010 — Replacement and disposal clean every accepted ownership unit once

**Given** cleanup and successive current successful loads
**When** a newer value replaces a retained accepted value
**Then** the older ownership unit is cleaned exactly once
**When** the VM is disposed repeatedly
**Then** the current ownership unit is cleaned exactly once
**And** without cleanup no value is reflectively or implicitly disposed

### ARES-011 — Disposal cancels and makes late work inert

**Given** an async resource VM with work in progress and counted state/command
notifications
**When** the VM is disposed one or more times
**Then** current loader and async commands receive cancellation exactly once as
their host contract permits
**And** every command and direct intent is disabled or inert
**When** the old loader later succeeds or fails despite cancellation
**Then** no state mutation, ordinary notification, command notification, or
application callback occurs
**And** a newly returned ownership unit is cleaned exactly once when cleanup is
configured
