# vmx — Python

[![PyPI](https://img.shields.io/pypi/v/vmx.svg)](https://pypi.org/project/vmx/)
[![Python versions](https://img.shields.io/pypi/pyversions/vmx.svg)](https://pypi.org/project/vmx/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/thekaveh/VMx/blob/main/LICENSE)

Hierarchical lifecycle-aware MVVM viewmodel framework for Python,
spec-compatible with the C#, TypeScript, Swift, and Rust flavors.

## 1. Status

**v3.30.0 source** — implements `spec-v3.30.0` end-to-end. 444/444 library conformance IDs
pass. Supports Python 3.10–3.14.
`mypy --strict` clean. Opt-in `vmx.notifications` subpackage ships an
`INotificationHub` for async confirmations.

## 2. Install

VMx 3.23.0 is on PyPI and implements spec 3.23.0. The 3.30.0 source line is
not published; pin 3.23.0 when reproducing released behavior.

```bash
pip install vmx
# or
uv add vmx
```

## 3. Quick start

The minimum-viable shape is `imports → services → builder (name + model + services + optional modeled_hinter) → construct() → read status`:

```python
from dataclasses import dataclass

from vmx import (
    ComponentVMOf,
    CompositeVM,
    Message,
    MessageHub,
    RxDispatcher,
)


@dataclass
class TabModel:
    title: str


# 1. Services (a hub + a dispatcher).
hub: MessageHub[Message] = MessageHub()
dispatcher = RxDispatcher.immediate()

# 2. Build leaves: name, model, services, optional modeled_hinter.
home: ComponentVMOf[TabModel] = (
    ComponentVMOf[TabModel]
    .builder()
    .name("home")
    .model(TabModel("Home"))
    .modeled_hinter(lambda m: m.title)  # optional — defaults to lambda _m: ""
    .services(hub, dispatcher)
    .build()
)

settings: ComponentVMOf[TabModel] = (
    ComponentVMOf[TabModel]
    .builder()
    .name("settings")
    .model(TabModel("Settings"))
    .services(hub, dispatcher)
    .build()
)

# 3. Build a composite over the leaves.
tabs = (
    CompositeVM[ComponentVMOf[TabModel]]
    .builder()
    .name("tab-bar")
    .services(hub, dispatcher)
    .children(lambda: [home, settings])
    .build()
)

# 4. Transition the lifecycle from DESTRUCTED → CONSTRUCTED before use.
tabs.construct()
print(tabs.status)  # ConstructionStatus.CONSTRUCTED

tabs.current = settings
print(tabs.current.model.title)  # "Settings"

tabs.dispose()
hub.dispose()
```

> **Tips:**
>
> - `.modeled_hinter(...)` is optional on every modeled builder; the default
>   is `lambda _m: ""`. Pass a callable when you want to derive a display
>   hint from the model.
> - For tests, samples, and headless code, `NULL_MESSAGE_HUB` and
>   `NULL_DISPATCHER` are safe no-op singletons. Annotate variables as
>   `MessageHubProto[Message]` (the structural `Protocol`) to keep
>   `mypy --strict` happy, or use the generic
>   `null_message_hub_of(MyMessage)` factory (imported from `vmx.services`) for
>   a narrower message type.

The C# and TypeScript flavors mirror this shape: see
[C# Quick start](https://github.com/thekaveh/VMx/blob/main/langs/csharp/README.md#3-quick-start) and
[TypeScript Quick start](https://github.com/thekaveh/VMx/blob/main/langs/typescript/README.md#3-quick-start) — only the
identifier casing differs.

See [Getting Started with VMx — Python](https://github.com/thekaveh/VMx/blob/main/docs/content/getting-started/python.md)
for the full walkthrough.

### 3.1 Cross-language naming

The concepts are identical across the five flavors; identifier casing follows
each language idiom (ADR-0006). See the
[cross-language naming table](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/cross-language-naming.md).

## 4. API surface

The public API is re-exported from a single entry point:

```python
from vmx import ComponentVM, ConstructionStatus, MessageHub, RelayCommand, RxDispatcher
```

| Export                                            | Description                                                                         |
| ------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `ComponentVM`                                     | Leaf viewmodel (no model)                                                           |
| `ComponentVMOf[M]`                                | Leaf viewmodel with a typed model                                                   |
| `ReadonlyComponentVMOf[M]`                        | Leaf VM with read-only model                                                        |
| `CompositeVM[VM]` / `CompositeVMOf[M,VM]`         | Ordered collection + current slot                                                   |
| `GroupVM[VM]`                                     | Collection without current selection                                                |
| `ChildOrder`                                      | Group/composite `destruct_order(...)` option: `INSERTION` (default) or `REVERSE`    |
| `VmCollectionProto[VM]`                           | Shared group/composite collection + atomic move                                     |
| `SelectableVmCollectionProto[VM]`                 | Composite-only current-selection extension                                          |
| `AggregateVM1..6[…]`                              | Fixed-arity named component slots (ADR-0034)     |
| `ForwardingComponentVM`                           | Decorator for `ComponentVMOfProto`                                                  |
| `ForwardingCompositeVM`                           | Decorator for composites                                                            |
| `RelayCommand` / `RelayCommandOf[T]`              | Executable command with `can_execute` predicate                                     |
| `CompositeCommand`                                | Aggregate N inner commands                                              |
| `DecoratorCommand`                                | Wrap a command with pre/post + can-execute gate                                     |
| `ConfirmationDecoratorCommand`                    | Wrap a command with an async confirm coroutine                                      |
| `ModeledCrudCommands[M,VM]`                       | Create / UpdateCurrent / DeleteCurrent helper                                       |
| `MessageHub`                                      | Pub/sub hub backed by `reactivex` `Subject`                                         |
| `NullMessageHub` / `NULL_MESSAGE_HUB`             | Null-object variant per ADR-0017                                                    |
| `RxDispatcher`                                    | Foreground/background scheduler pair                                                |
| `NullDispatcher` / `NULL_DISPATCHER`              | Null-object variant per ADR-0017                                                    |
| `ConstructionStatus`                              | 5-state lifecycle enum                                                              |
| `StatusTransitionError`                           | Raised on illegal lifecycle operations                                              |
| `BuilderValidationError`                          | Raised when a builder is missing required fields                                    |
| `walk(root)`                                      | DFS pre-order tree traversal generator                                              |
| `walk_expanded(root)`                             | DFS walk gated on `IExpandable.is_expanded`                                  |
| `find(root, predicate)`                           | Short-circuit tree search                                                           |
| `DerivedProperty[TValue]` / `from_sources(...)`   | N-source computed value                                                 |
| `ExpandableState`                                 | Expansion helper + expand/collapse/toggle commands                      |
| `SearchableState[T]`                              | Debounced filter + optional source signal                              |
| `AsyncResourceVM[T]`                             | Cancellable latest-wins async value state                              |
| `ILocalizer` / `NullLocalizer` / `NULL_LOCALIZER` | i18n hook + null-default                                                     |
| 22× capability ABCs                               | `vmx.capabilities.*` — opt-in                                          |
| `HierarchicalVM[TModel, TVM]`                     | Recursive tree VM with key-aware `attach_many`                                      |
| `TreeSelection[TVM]`                              | One current node per tree; clears when the node leaves the tree         |
| `TreeStructureChangedMessage`                     | Tree-structural-change notification                                     |
| `FormVM[TM]`                                      | Snapshot/revert form lifecycle                                          |
| `DialogService` / `NullDialogService`             | File/confirm/notify dialogs + null                                      |
| `ServicedObservableCollection[T]`                 | Complete local-before-hub mutation surface                              |
| `KeyedServicedObservableCollection[TKey, T]`      | Ordered serviced surface plus captured-key index                        |
| `ObservableMembershipSource[T]` / `AggregateChangeStream[T]` | Dynamic membership-and-item fan-in with provenance          |
| `ObservableList[T]`                               | Granular events + atomic `replace_all`                                               |
| `ObservableDictionary[K1, K2, V]`                 | Multi-key observable dictionary                                         |
| `PagedComposition[TVM]`                           | Pageable iterable decorator                                             |
| Fluent command helpers                            | `confirm` / `precede_with` / `succeed_with` / `wrap_with` over commands |
| `property_value_changed_messages_for`             | Hub helper yielding an observable of property-value snapshots           |
| `subscribe_value`                                 | Fixed-VM selected-state bridge returning `DisposableBase`              |

### 4.1 Serviced collections

`ServicedObservableCollection[T]` is a caller-owned sequence with local
`on_collection_changed` delivery and optional hub publication.
`KeyedServicedObservableCollection[TKey, T]` adds a captured stable-key index
(`get`, `upsert`, `delete`, `contains_key`) and keeps the full
`MutableSequence` surface.

Empty Clear and empty-to-empty replacement are no-ops. Messages expose `index`,
`old_index`, and `new_index`. Use `ObservableList[T]` when you need batch scopes
and the `Count` channel. See
[Python serviced collections](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/python.md#733-serviced-collections).

### 4.2 Imperative engine bridge

`subscribe_value` pushes a selected value from one fixed VM into an imperative
host as `(current, previous)`. It returns a `DisposableBase` that the host owns;
VMx does not attach it to the observed VM's lifetime. See
[Python imperative engine bridge](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/python.md#734-imperative-engine-bridge).

### 4.3 Async resource operation loops

A synchronous caller without a running asyncio loop can start `AsyncResourceVM`
with `load_command.execute()`; VMx runs the operation on its shared daemon loop.
Application-owned loops must stay runnable until resource work is cancelled and
drained. See
[Python async resource operation loops](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/python.md#735-async-resource-operation-loops)
and the
[asyncio ownership guidance](https://github.com/thekaveh/VMx/blob/main/docs/content/primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership).

## 5. Notifications

The opt-in `vmx.notifications` subpackage adds:

| Export                                                                                   | Description                                    |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`                             | Notification primitives                        |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub` / `NULL_NOTIFICATION_HUB` | Async notification hub + null variant          |
| `make_confirm(hub, prompt)`                                                              | Bridge to `ConfirmationDecoratorCommand`       |
| `NotificationVM`                                                                         | Render-side VM for `Notification`              |
| `ConfirmationVM`                                                                         | Render-side VM with Approve/Reject             |

## 6. Conformance

Implements all 444 library conformance IDs; THEME scenario IDs live in the
example apps. See [`spec/12-conformance.md`](https://github.com/thekaveh/VMx/blob/main/spec/12-conformance.md).
[`tests/conformance/README.md`](https://github.com/thekaveh/VMx/blob/main/langs/python/tests/conformance/README.md)
documents the test-layout conventions.

Run the suite:

```bash
uv run pytest
```

## 7. Development

```bash
# From this directory
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

The `lifecycle-transitions.json` fixture from `spec/fixtures/` is tracked under
`src/vmx/lifecycle/_data/` and shipped inside the wheel. The
`vmx.lifecycle.transition_validator` module loads it via `importlib.resources`
with a repo-relative fallback for diagnostics. `tools/check-python-fixture-sync.py`
keeps the package copy byte-identical to the spec fixture.

See [`CONTRIBUTING.md`](https://github.com/thekaveh/VMx/blob/main/CONTRIBUTING.md) for the contributor workflow and
[`RELEASING.md`](https://github.com/thekaveh/VMx/blob/main/langs/python/RELEASING.md) for the PyPI release runbook.

## 8. License

Apache-2.0 — see [`LICENSE`](https://github.com/thekaveh/VMx/blob/main/LICENSE) and [`NOTICE`](https://github.com/thekaveh/VMx/blob/main/NOTICE).
