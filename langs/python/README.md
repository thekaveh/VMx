# vmx — Python

Hierarchical lifecycle-aware MVVM viewmodel framework for Python,
spec-compatible with the C# and TypeScript flavors.

## 1. Status

**v2.2.0** — implements `spec-v2.2.0` end-to-end. 220/220 conformance IDs
pass. Supports Python 3.10–3.13.
`mypy --strict` clean. Opt-in `vmx.notifications` subpackage ships an
`INotificationHub` for async confirmations.

## 2. Install

```bash
pip install vmx
# or
uv add vmx
```

## 3. Quick start

```python
from dataclasses import dataclass

from vmx import (
    ComponentVMOf,
    CompositeVM,
    MessageHub,
    RxDispatcher,
)

hub = MessageHub()
dispatcher = RxDispatcher.immediate()


@dataclass
class TabModel:
    title: str


home: ComponentVMOf[TabModel] = (
    ComponentVMOf.builder()
    .name("home")
    .model(TabModel("Home"))
    .services(hub, dispatcher)
    .build()
)

settings: ComponentVMOf[TabModel] = (
    ComponentVMOf.builder()
    .name("settings")
    .model(TabModel("Settings"))
    .services(hub, dispatcher)
    .build()
)

tabs = (
    CompositeVM[ComponentVMOf[TabModel]]
    .builder()
    .name("tab-bar")
    .services(hub, dispatcher)
    .children(lambda: [home, settings])
    .build()
)

tabs.construct()

tabs.current = settings
print(tabs.current.model.title)  # "Settings"

tabs.dispose()
hub.dispose()
```

> **Tips:**
>
> * `.modeled_hinter(...)` is optional on every modeled builder; the default
>   is `lambda _m: ""`. Pass a callable when you want to derive a display
>   hint from the model.
> * For tests, samples, and headless code, `NULL_MESSAGE_HUB` and
>   `NULL_DISPATCHER` are safe no-op singletons. Annotate variables as
>   `MessageHubProto[Message]` (the structural `Protocol`) to keep
>   `mypy --strict` happy, or use the generic
>   `null_message_hub_of(MyMessage)` factory for a narrower message type.

See [docs/getting-started/python.md](../../docs/getting-started/python.md)
for the full walkthrough.

## 4. API surface

The public API is re-exported from a single entry point:

```python
from vmx import ...  # see vmx/__init__.py for the full list
```

| Export                          | Description                                       |
| ------------------------------- | ------------------------------------------------- |
| `ComponentVM`                   | Leaf viewmodel (no model)                         |
| `ComponentVMOf[M]`              | Leaf viewmodel with a typed model                 |
| `ReadonlyComponentVMOf[M]`      | Leaf VM with read-only model                      |
| `CompositeVM[VM]` / `CompositeVMOf[M,VM]` | Ordered collection + current slot     |
| `GroupVM[VM]`                   | Collection without current selection              |
| `AggregateVM1..5[…]`            | Fixed-arity named component slots                 |
| `ForwardingComponentVM`         | Decorator for `ComponentVMOfProto`                |
| `ForwardingCompositeVM`         | Decorator for composites                          |
| `RelayCommand` / `RelayCommandOf[T]` | Executable command with `can_execute` predicate |
| `CompositeCommand`              | Aggregate N inner commands (spec v2.0)            |
| `DecoratorCommand`              | Wrap a command with pre/post + can-execute gate   |
| `ConfirmationDecoratorCommand`  | Wrap a command with an async confirm coroutine    |
| `ModeledCrudCommands[M,VM]`     | Create / UpdateCurrent / DeleteCurrent helper     |
| `MessageHub`                    | Pub/sub hub backed by `reactivex` `Subject`       |
| `NullMessageHub` / `NULL_MESSAGE_HUB` | Null-object variant per ADR-0017            |
| `RxDispatcher`                  | Foreground/background scheduler pair              |
| `NullDispatcher` / `NULL_DISPATCHER` | Null-object variant per ADR-0017             |
| `ConstructionStatus`            | 5-state lifecycle enum                            |
| `StatusTransitionError`         | Raised on illegal lifecycle operations            |
| `BuilderValidationError`        | Raised when a builder is missing required fields  |
| `walk(root)`                    | DFS pre-order tree traversal generator            |
| `walk_expanded(root)`           | DFS walk gated on `IExpandable.is_expanded` (v2.0) |
| `find(root, predicate)`         | Short-circuit tree search                         |
| `DerivedProperty[TValue]` / `from_sources(...)` | N-source computed value (spec v2.0) |
| `ExpandableState`               | `IExpandable`+`ICollapsible` helper (spec v2.0)   |
| `SearchableState[T]`            | Debounced filter helper (spec v2.0)               |
| `ILocalizer` / `NullLocalizer` / `NULL_LOCALIZER` | i18n hook + null-default (v2.0) |
| 22× capability ABCs             | `vmx.capabilities.*` — opt-in (spec v2.0+)        |
| `HierarchicalVM[TModel, TVM]`   | Recursive tree-structured VM (spec v2.1)          |
| `TreeStructureChangedMessage`   | Tree-structural-change notification (spec v2.1)   |
| `FormVM[TM]`                    | Snapshot/revert form lifecycle (spec v2.1)        |
| `DialogService` / `NullDialogService` | File/confirm/notify dialogs + null (spec v2.1) |
| `ServicedObservableCollection[T]` | Hub-aware observable collection (spec v2.1)     |
| `ObservableList[T]`             | Granular per-mutation events (spec v2.1)          |
| `ObservableDictionary[K1, K2, V]` | Multi-key observable dictionary (spec v2.1)     |
| `PagedComposition[TVM]`         | Pageable iterable decorator (spec v2.1)           |
| Fluent command helpers          | `confirm` / `precede_with` / `succeed_with` / `wrap_with` over commands (spec v2.1) |
| `property_value_changed_messages_for` | Hub helper yielding an observable of property-value snapshots (spec v2.1) |

The opt-in `vmx.notifications` subpackage (spec v2.0+) adds:

| Export                                                            | Description                            |
| ----------------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`      | Notification primitives                |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub` / `NULL_NOTIFICATION_HUB` | Async notification hub + null variant |
| `make_confirm(hub, prompt)`                                       | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                                  | Render-side VM for `Notification` (spec v2.1) |
| `ConfirmationVM`                                                  | Render-side VM with Approve/Reject (spec v2.1) |

## 5. Conformance

All 220 conformance IDs from `spec/12-conformance.md` are covered.

```
v1.x   LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
       CVM-001..006   COMP-001..013 GRP-001..006   AGG-001..005
       FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
v2.0   CAP-001..020   NULL-001..003 DPROP-001..012 CMDD-001..009
       NOTIF-001..010 COMP-014..024 GRP-007..010   EXP-001..005
       LOC-001..003
v2.1   HIER-001..014  DIA-001..008  FORM-001..010  NOTIF-011..016
       COL-001..023   CMD-008..011  CAP-021..022
v2.2   AGG-006
```

Run the suite:

```bash
uv run pytest
```

## 6. Development

```bash
# From this directory
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

The `lifecycle-transitions.json` fixture from `spec/fixtures/` is shipped
inside the wheel via hatchling's `force-include` mapping in
[`pyproject.toml`](pyproject.toml) and consumed at runtime by
`vmx.lifecycle.transition_validator`.

## 7. License

MIT — see [`LICENSE`](../../LICENSE).
