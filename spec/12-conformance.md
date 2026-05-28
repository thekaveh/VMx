# 12 — Conformance test catalog

This document enumerates every stable conformance test identifier in the form
`XXX-NNN`. Every language flavor MUST implement a passing test for each ID in its
`langs/<lang>/tests/conformance/` directory before it can be marked stable. CI
verifies this via `tools/check-conformance-coverage.py`.

## 1. Identifier prefixes

| Prefix          | Area                                              | File                                          |
| --------------- | ------------------------------------------------- | --------------------------------------------- |
| `LIFE-NNN`      | Lifecycle state machine                           | `02-lifecycle.md`                             |
| `HUB-NNN`       | Message hub                                       | `03-messages.md`                              |
| `PROP-NNN`      | Property change notifications                     | `03-messages.md`                              |
| `CMD-NNN`       | Commands                                          | `04-commands.md`                              |
| `CVM-NNN`       | ComponentVM (incl. modeled, readonly)             | `05-component-vm.md`                          |
| `COMP-NNN`      | CompositeVM                                       | `06-composite-vm.md`                          |
| `GRP-NNN`       | GroupVM                                           | `07-group-vm.md`                              |
| `AGG-NNN`       | AggregateVM                                       | `08-aggregate-vm.md`                          |
| `FWD-NNN`       | Forwarding decorators                             | `09-forwarding.md`                            |
| `BLD-NNN`       | Builders                                          | `10-builders.md`                              |
| `THR-NNN`       | Threading & schedulers                            | `11-threading.md`                             |
| `UTIL-NNN`      | Tree utilities (spec v1.1)                        | `13-tree-utilities.md`                        |
| `CAP-NNN`       | Capability micro-interfaces                       | `14-capabilities.md`                          |
| `NULL-NNN`      | Null-object service variants                      | `03-messages.md` + `11-threading.md`          |
| `DPROP-NNN`     | Derived properties                                | `15-derived-properties.md`                    |
| `CMDD-NNN`      | Command decorators (spec v2.0)                    | `04-commands.md`                              |
| `NOTIF-NNN`     | Notification sub-package                          | `16-notifications.md`                         |
| `EXP-NNN`       | Expand / collapse state                           | `05-component-vm.md` + `13-tree-utilities.md` |
| `COMP-014..024` | CompositeVM v2.0 additions (search, modeled CRUD) | `06-composite-vm.md`                          |
| `GRP-007..010`  | GroupVM v2.0 additions (search)                   | `07-group-vm.md`                              |
| `LOC-NNN`       | Localization hooks                                | `17-localization.md`                          |

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

**Given** a `CompositeVM<VM>` in `Constructed` state with N children all `Constructed`,
each child itself a `CompositeVM<VM>` with M grand-children all `Constructed`
**When** `parent.dispose()` is called
**Then** when it returns, every child and every grand-child has `Status == Disposed`
**And** the disposal order is depth-first (grand-children before children before parent)

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

______________________________________________________________________

## 5. Property change (`PROP-NNN`)

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
**Then** a `BuilderValidationError` / `InvalidOperationException` is raised
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

## 15. Capability micro-interfaces (`CAP-NNN`) — spec v2.0

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
spec/04-commands.md §Decorators.

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

______________________________________________________________________

## 19. Notification sub-package (`NOTIF-NNN`) — spec v2.0

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

______________________________________________________________________

## 20. CompositeVM v2.0 additions (`COMP-014..024`)

Search/filter (COMP-014..018, see ADR-0014) and modeled CRUD (COMP-019..024,
see ADR-0016) additions to chapter 06.

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
**When** the items source is updated to `["one", "two"]` and the helper is
notified (via `search()` / explicit refresh)
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

______________________________________________________________________

## 21. GroupVM v2.0 additions (`GRP-007..010`)

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
