# vmx — Python

[![PyPI](https://img.shields.io/pypi/v/vmx.svg)](https://pypi.org/project/vmx/)
[![Python versions](https://img.shields.io/pypi/pyversions/vmx.svg)](https://pypi.org/project/vmx/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/thekaveh/VMx/blob/main/LICENSE)

Hierarchical lifecycle-aware MVVM viewmodel framework for Python,
spec-compatible with the C#, TypeScript, and Swift flavors.

## 1. Status

**v3.15.0** — implements `spec-v3.15.0` end-to-end. 346/346 library conformance IDs
pass. Supports Python 3.10–3.13.
`mypy --strict` clean. Opt-in `vmx.notifications` subpackage ships an
`INotificationHub` for async confirmations. The Swift flavor is at total
parity; see `../swift/README.md` §5 for the current conformance matrix.

## 2. Install

The source tree currently implements v3.15.0. The latest public PyPI package may
lag this source tree; pin a version when reproducing released behavior.

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
    MessageHub,
    RxDispatcher,
)


@dataclass
class TabModel:
    title: str


# 1. Services (a hub + a dispatcher).
hub = MessageHub()
dispatcher = RxDispatcher.immediate()

# 2. Build leaves: name, model, services, optional modeled_hinter.
home: ComponentVMOf[TabModel] = (
    ComponentVMOf.builder()
    .name("home")
    .model(TabModel("Home"))
    .modeled_hinter(lambda m: m.title)  # optional — defaults to lambda _m: ""
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

See [docs/getting-started/python.md](https://github.com/thekaveh/VMx/blob/main/docs/getting-started/python.md)
for the full walkthrough.

### 3.1 Cross-language naming

The conceptual surface is identical across the four flavors; identifier
casing follows the per-language idiom (see ADR-0006).

| Concept            | C#                        | Python             | TypeScript                | Swift                     |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- |
| Unmodeled VM       | `ComponentVM`             | `ComponentVM`      | `ComponentVM`             | `ComponentVM`             |
| Modeled VM         | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        |
| Status property    | `Status`                  | `status`           | `status`                  | `status`                  |
| Builder entrypoint | `Builder()`               | `builder()`        | `builder()`               | `builder()`               |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` |

C# uses PascalCase, Python uses snake_case, TypeScript and Swift use
camelCase. The single substantive divergence is that C# names the modeled
variant with a generic-parameter suffix (`ComponentVM<M>`), while Python,
TypeScript, and Swift use a separate `ComponentVMOf` type because their
generics syntax cannot overload an unparameterised name.

## 4. API surface

The public API is re-exported from a single entry point:

```python
from vmx import ...  # see vmx/__init__.py for the full list
```

| Export                                            | Description                                                                         |
| ------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `ComponentVM`                                     | Leaf viewmodel (no model)                                                           |
| `ComponentVMOf[M]`                                | Leaf viewmodel with a typed model                                                   |
| `ReadonlyComponentVMOf[M]`                        | Leaf VM with read-only model                                                        |
| `CompositeVM[VM]` / `CompositeVMOf[M,VM]`         | Ordered collection + current slot                                                   |
| `GroupVM[VM]`                                     | Collection without current selection                                                |
| `VmCollectionProto[VM]`                           | Shared group/composite collection + atomic move                                     |
| `SelectableVmCollectionProto[VM]`                 | Composite-only current-selection extension                                          |
| `AggregateVM1..6[…]`                              | Fixed-arity named component slots (arity 6 added in spec v2.2.0 — see ADR-0034)     |
| `ForwardingComponentVM`                           | Decorator for `ComponentVMOfProto`                                                  |
| `ForwardingCompositeVM`                           | Decorator for composites                                                            |
| `RelayCommand` / `RelayCommandOf[T]`              | Executable command with `can_execute` predicate                                     |
| `CompositeCommand`                                | Aggregate N inner commands (spec v2.0)                                              |
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
| `walk_expanded(root)`                             | DFS walk gated on `IExpandable.is_expanded` (v2.0)                                  |
| `find(root, predicate)`                           | Short-circuit tree search                                                           |
| `DerivedProperty[TValue]` / `from_sources(...)`   | N-source computed value (spec v2.0)                                                 |
| `ExpandableState`                                 | `IExpandable`+`ICollapsible` helper (spec v2.0)                                     |
| `SearchableState[T]`                              | Debounced filter helper (spec v2.0)                                                 |
| `ILocalizer` / `NullLocalizer` / `NULL_LOCALIZER` | i18n hook + null-default (v2.0)                                                     |
| 22× capability ABCs                               | `vmx.capabilities.*` — opt-in (spec v2.0+)                                          |
| `HierarchicalVM[TModel, TVM]`                     | Recursive tree VM with key-aware `attach_many`                                      |
| `TreeStructureChangedMessage`                     | Tree-structural-change notification (spec v2.1)                                     |
| `FormVM[TM]`                                      | Snapshot/revert form lifecycle (spec v2.1)                                          |
| `DialogService` / `NullDialogService`             | File/confirm/notify dialogs + null (spec v2.1)                                      |
| `ServicedObservableCollection[T]`                 | Hub-aware observable collection (spec v2.1)                                         |
| `ObservableList[T]`                               | Granular events + atomic `replace_all`                                               |
| `ObservableDictionary[K1, K2, V]`                 | Multi-key observable dictionary (spec v2.1)                                         |
| `PagedComposition[TVM]`                           | Pageable iterable decorator (spec v2.1)                                             |
| Fluent command helpers                            | `confirm` / `precede_with` / `succeed_with` / `wrap_with` over commands (spec v2.1) |
| `property_value_changed_messages_for`             | Hub helper yielding an observable of property-value snapshots (spec v2.1)           |

The opt-in `vmx.notifications` subpackage (spec v2.0+) adds:

| Export                                                                                   | Description                                    |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`                             | Notification primitives                        |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub` / `NULL_NOTIFICATION_HUB` | Async notification hub + null variant          |
| `make_confirm(hub, prompt)`                                                              | Bridge to `ConfirmationDecoratorCommand`       |
| `NotificationVM`                                                                         | Render-side VM for `Notification` (spec v2.1)  |
| `ConfirmationVM`                                                                         | Render-side VM with Approve/Reject (spec v2.1) |

## 5. Conformance

All 346 library conformance IDs from `spec/12-conformance.md` are covered (the 5 THEME scenario IDs live in the flagship example apps — see CONTRIBUTING §2.5). Test-layout conventions for the conformance tree are documented in [`tests/conformance/README.md`](tests/conformance/README.md).

```
v1.x   LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
       CVM-001..010   COMP-001..013 GRP-001..006   AGG-001..005
       FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
v2.0   CAP-001..020   NULL-001..003 DPROP-001..012 CMDD-001..009
       NOTIF-001..010 COMP-014..024 GRP-007..010   EXP-001..005
       LOC-001..003
v2.1   HIER-001..014  DIA-001..008  FORM-001..010  NOTIF-011..016
       COL-001..023   CMD-008..011  CAP-021..022
v2.2   AGG-006
v2.3   BLD-005        FORM-011..013 HIER-015..017
v2.4   THEME-001..005
v2.5   HIER-018       NOTIF-017     FORM-014
v2.6   COMP-025..026
v3.0   LIFE-014       FORM-015      CMDD-010      COMP-027      CMD-012
v3.1   CMD-013        COL-024..031  COMP-028..037 FORM-016..023
       DIA-009..013   HIER-019..022 DISC-001..006 BLD-006 GRP-011
v3.2   HUB-008..013
v3.3   CVM-007..009
v3.4   DISP-001..006
v3.5   COL-032..039
v3.6   CMD-014..019
v3.7   FORM-024..029
v3.8   HIER-023..030
v3.9   COL-040..047
v3.10  DISP-007..013
v3.11  DISP-014
v3.12  FORM-030
v3.13  CVM-010
v3.15  SUBV-001..004
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

The `lifecycle-transitions.json` fixture from `spec/fixtures/` is tracked under
`src/vmx/lifecycle/_data/` and shipped inside the wheel. The
`vmx.lifecycle.transition_validator` module loads it via `importlib.resources`
with a repo-relative fallback for diagnostics. `tools/check-python-fixture-sync.py`
keeps the package copy byte-identical to the spec fixture.

## 7. Releasing

See [`RELEASING.md`](RELEASING.md) for the PyPI release pipeline runbook.

## 8. License

Apache-2.0 — see [`LICENSE`](https://github.com/thekaveh/VMx/blob/main/LICENSE) and [`NOTICE`](https://github.com/thekaveh/VMx/blob/main/NOTICE).
