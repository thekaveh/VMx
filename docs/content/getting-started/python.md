# 3.3. Getting Started with VMx — Python

This tutorial walks you through building viewmodels with the VMx Python library.
You will build a `ComponentVMOf[UserModel]`, a `RelayCommand` with a reactive
trigger, and a `CompositeVM[TabVM]` with tab selection — all in a Python REPL,
script, or test.

> For the normative contracts behind each type, see `spec/05-component-vm.md`,
> `spec/04-commands.md`, and `spec/06-composite-vm.md`.

______________________________________________________________________

## 3.3.1. Install

```bash
# Using uv (recommended)
uv add vmx

# Using pip
pip install vmx
```

For local development from a checked-out clone:

```bash
uv add --editable path/to/VMx/langs/python
# or
pip install -e path/to/VMx/langs/python
```

______________________________________________________________________

## 3.3.2. Wire up `MessageHub` and `RxDispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that knows about your event loop or UI thread.

### 3.3.2.1. 2.1 Option A — immediate (console / synchronous tests)

```python
from vmx.services import MessageHub, RxDispatcher

hub = MessageHub()
dispatcher = RxDispatcher.immediate()
# Both foreground and background schedulers are ImmediateScheduler — safe for
# console scripts and pytest suites where there is no event loop.
```

### 3.3.2.2. 2.2 Option B — asyncio-based UI (Textual, etc.)

```python
import asyncio
from vmx.services import MessageHub, RxDispatcher

async def main() -> None:
    loop = asyncio.get_running_loop()
    hub = MessageHub()
    dispatcher = RxDispatcher.asyncio(loop)
    # foreground → AsyncIOScheduler(loop)
    # background → ThreadPoolScheduler
    ...

asyncio.run(main())
```

`asyncio.get_running_loop()` is preferred over `asyncio.get_event_loop()`,
which has been a `DeprecationWarning` since Python 3.10 when no loop is
running.

You can also inject the two schedulers directly if you need a custom pairing:

```python
from reactivex.scheduler import ImmediateScheduler, ThreadPoolScheduler
from vmx.services import RxDispatcher

dispatcher = RxDispatcher(
    foreground=ImmediateScheduler(),
    background=ThreadPoolScheduler(),
)
```

______________________________________________________________________

## 3.3.3. Build a `ComponentVMOf[UserModel]`

`ComponentVMOf[M]` is the primary leaf viewmodel. It holds a typed model,
fires `PropertyChangedMessage` on the hub when the model changes, and
participates in the lifecycle state machine
(`DESTRUCTED → CONSTRUCTING → CONSTRUCTED → DESTRUCTING → DESTRUCTED`).

```python
from dataclasses import dataclass

from vmx.components import ComponentVMOf
from vmx.messages import PropertyChangedMessage
from vmx.services import MessageHub, RxDispatcher

# A simple domain model — use your own real types here.
@dataclass(frozen=True)
class UserModel:
    name: str
    email: str

hub = MessageHub()
dispatcher = RxDispatcher.immediate()

# Build the viewmodel — every builder setter returns a NEW builder (immutable).
user_vm: ComponentVMOf[UserModel] = (
    ComponentVMOf.builder()
    .name("user-card")
    .model(UserModel("Alice", "alice@example.com"))
    .services(hub, dispatcher)
    # Derive a display hint from the model.
    .modeled_hinter(lambda m: m.name)
    # Optional: callback when model is set to a new value.
    .on_model_changed(lambda m: print(f"Model updated → {m.name}"))
    .on_construct(lambda: print("user-card constructed"))
    .on_destruct(lambda: print("user-card destructed"))
    .build()
)

# Subscribe to hub messages BEFORE constructing so you don't miss any.
# reactivex.operators has no OfType; filter by isinstance directly in the
# subscriber.
hub.messages.subscribe(
    lambda msg: (
        isinstance(msg, PropertyChangedMessage)
        and msg.sender is user_vm
        and print(f"Property '{msg.property_name}' changed on {msg.sender_name}")
    )
)

# Alternatively, subscribe via the VM's own property_changed observable,
# which emits property name strings (snake_case).
user_vm.property_changed.subscribe(
    lambda prop: print(f"  [property_changed] {prop}")
)

# construct() transitions DESTRUCTED → CONSTRUCTING → CONSTRUCTED.
# This is when the VM fires its on_construct callback and begins accepting
# model updates.
user_vm.construct()
# stdout: "user-card constructed"

# Update the model — triggers on_model_changed and publishes
# PropertyChangedMessage for "model" (and "modeled_hint" if it changed).
user_vm.model = UserModel("Alice Smith", "asmith@example.com")
# stdout: "Property 'model' changed on user-card"
# stdout: "Model updated → Alice Smith"

print(user_vm.modeled_hint)  # "Alice Smith"  (modeled_hinter result)
print(user_vm.status)        # ConstructionStatus.CONSTRUCTED
```

> See `spec/05-component-vm.md` for the full `ComponentVMOfProto[M]` contract and
> `spec/03-messages.md` for the `PropertyChangedMessage` schema.

______________________________________________________________________

## 3.3.4. Build a `RelayCommand`

`RelayCommand` wraps an optional callable task, an optional predicate that
gates execution, and a set of `Observable` triggers that signal `can_execute`
may have changed.

```python
from reactivex.subject import Subject

from vmx.commands import RelayCommand

# A Subject you fire whenever the predicate outcome may have changed.
can_save_trigger: Subject[object] = Subject()

is_dirty = False

def save_task() -> None:
    global is_dirty
    print("Saving…")
    is_dirty = False
    can_save_trigger.on_next(None)  # re-evaluate can_execute

save_command = (
    RelayCommand.builder()
    .task(save_task)
    .predicate(lambda: is_dirty)
    .triggers(can_save_trigger)
    .build()
)

# can_execute is False until is_dirty is True.
print(save_command.can_execute())   # False

is_dirty = True
can_save_trigger.on_next(None)      # fires can_execute_changed

# Subscribe to re-evaluation notifications.
save_command.can_execute_changed.subscribe(
    lambda _: print(f"  can_execute is now {save_command.can_execute()}")
)

print(save_command.can_execute())   # True
save_command.execute()              # prints "Saving…"
print(save_command.can_execute())   # False again

# Dispose to unsubscribe all trigger subscriptions.
save_command.dispose()
```

> See `spec/04-commands.md` for the full command contract, including the
> "predicate-false gates execute" rule (CMD-003).

______________________________________________________________________

## 3.3.5. Build a `CompositeVM[TabVM]`

`CompositeVM[VM]` owns an ordered child collection and a `current` selection.
Children are provided by a factory callable that runs lazily on the first
`construct()` call.

```python
from dataclasses import dataclass

from vmx.components import ComponentVMOf
from vmx.composites import CompositeVM
from vmx.messages import PropertyChangedMessage
from vmx.services import MessageHub, RxDispatcher

@dataclass(frozen=True)
class TabModel:
    title: str

hub = MessageHub()
dispatcher = RxDispatcher.immediate()

# Build two tab children — they share the same hub and dispatcher.
tab1: ComponentVMOf[TabModel] = (
    ComponentVMOf.builder()
    .name("home-tab")
    .model(TabModel("Home"))
    .services(hub, dispatcher)
    .build()
)

tab2: ComponentVMOf[TabModel] = (
    ComponentVMOf.builder()
    .name("settings-tab")
    .model(TabModel("Settings"))
    .services(hub, dispatcher)
    .build()
)

# Build the composite. The children factory is evaluated on construct().
tabs: CompositeVM[ComponentVMOf[TabModel]] = (
    CompositeVM.builder()
    .name("tab-bar")
    .services(hub, dispatcher)
    .children(lambda: [tab1, tab2])
    .on_construct(lambda: print("tab-bar ready"))
    .build()
)

# Watch for current-selection changes via the hub.
hub.messages.subscribe(
    lambda msg: (
        isinstance(msg, PropertyChangedMessage)
        and msg.sender is tabs
        and msg.property_name == "current"
        and print(
            f"Selected tab: {tabs.current.model.title if tabs.current else '(none)'}"
        )
    )
)

# construct() cascades: the composite constructs itself then each child.
tabs.construct()
# stdout: "tab-bar ready"

# Select a tab — publishes PropertyChangedMessage for "current" and
# sets child.is_current.
tabs.current = tab2   # stdout: "Selected tab: Settings"
tabs.current = tab1   # stdout: "Selected tab: Home"

print([child.name for child in tabs])  # ['home-tab', 'settings-tab']
print(tab2.is_current)                 # False
```

> See `spec/06-composite-vm.md` for the full `CompositeVMProto[VM]` contract,
> including the `MutableSequence` semantics and `CollectionChangedEvent`.

______________________________________________________________________

## 3.3.6. Lifecycle and cleanup

Every VM follows a five-state lifecycle:
`DESTRUCTED → CONSTRUCTING → CONSTRUCTED → DESTRUCTING → DESTRUCTED`, plus the
terminal `DISPOSED`.

```python
from vmx.lifecycle.status import ConstructionStatus

print(user_vm.status)    # ConstructionStatus.CONSTRUCTED  (after construct())

# reconstruct() is destruct() + construct() in a single call. It is only valid
# from CONSTRUCTED (can_reconstruct() is True iff status == CONSTRUCTED); it
# round-trips through DESTRUCTED and back to CONSTRUCTED.
user_vm.reconstruct()
print(user_vm.status)    # ConstructionStatus.CONSTRUCTED

# destruct() transitions back to DESTRUCTED and runs on_destruct.
user_vm.destruct()
print(user_vm.status)    # ConstructionStatus.DESTRUCTED

# dispose() is terminal and idempotent. Calling construct() or destruct() on a
# disposed VM raises StatusTransitionError.
user_vm.dispose()
print(user_vm.status)    # ConstructionStatus.DISPOSED

# CompositeVM.dispose() disposes children, then itself.
tabs.dispose()

# MessageHub.dispose() completes the underlying Rx Subject.
hub.dispose()
```

> See `spec/02-lifecycle.md` for the full transition table and the
> `StatusTransitionError` rules (LIFE-001 through LIFE-014).

______________________________________________________________________

## 3.3.7. Threading

`RxDispatcher` pairs two Rx schedulers:

| Scheduler               | Typical mapping                            |
| ----------------------- | ------------------------------------------ |
| `dispatcher.foreground` | UI thread / asyncio event loop             |
| `dispatcher.background` | Thread-pool (blocking I/O, CPU-bound work) |

All hub observations delivered on `foreground` are safe to bind to UI controls.
Use `observe_on` from `reactivex.operators` to marshal:

```python
import reactivex.operators as ops

hub.messages.pipe(
    ops.filter(lambda msg: isinstance(msg, PropertyChangedMessage)),
    ops.observe_on(dispatcher.foreground),   # marshal to UI scheduler
).subscribe(lambda msg: update_label(msg))   # safe to touch UI here
```

For background work before constructing a VM:

```python
import reactivex as rx
import reactivex.operators as ops

def apply_remote_data(data: UserModel) -> None:
    user_vm.model = data
    user_vm.construct()

rx.from_callable(lambda: load_from_database(), scheduler=dispatcher.background).pipe(
    ops.observe_on(dispatcher.foreground),
).subscribe(apply_remote_data)
```

When using `RxDispatcher.asyncio(loop)`, the foreground scheduler posts work
back to the given asyncio event loop, keeping VM mutations on the loop thread.

> See `spec/11-threading.md` for the `THR-001..THR-004` conformance rules.

______________________________________________________________________

## 3.3.8. Where to go next

| Resource                      | Path                                 |
| ----------------------------- | ------------------------------------ |
| Spec overview                 | `spec/00-overview.md`                |
| Lifecycle contract            | `spec/02-lifecycle.md`               |
| Message schema                | `spec/03-messages.md`                |
| Commands                      | `spec/04-commands.md`                |
| ComponentVM contract          | `spec/05-component-vm.md`            |
| CompositeVM contract          | `spec/06-composite-vm.md`            |
| Builder spec                  | `spec/10-builders.md`                |
| Threading rules               | `spec/11-threading.md`               |
| Tree utilities (`walk/find`)  | `spec/13-tree-utilities.md`          |
| Architecture decision records | `spec/ADRs/`                         |
| Console example               | `examples/python/console/hello_vmx/` |
| Tkinter todo example          | `examples/python/tk/todo_app/`       |
| Textual TUI inspector example | `examples/python/textual/inspector/` |
| Conformance test suite        | `langs/python/tests/conformance/`    |
