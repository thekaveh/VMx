# vmx — Python

Hierarchical lifecycle-aware MVVM viewmodel framework for Python,
spec-compatible with the C# and TypeScript flavors.

## Status

**v1.1.0** — implements `spec-v1.1.0` end-to-end. 75/75 conformance IDs pass
(385 tests total across unit + conformance). Supports Python 3.10–3.13.
`mypy --strict` clean.

## Install

```bash
pip install vmx
# or
uv add vmx
```

## Quick start

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


home = (
    ComponentVMOf[TabModel]
    .builder()
    .name("home")
    .model(TabModel("Home"))
    .services(hub, dispatcher)
    .build()
)

settings = (
    ComponentVMOf[TabModel]
    .builder()
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

See [docs/getting-started/python.md](../../docs/getting-started/python.md)
for the full walkthrough.

## API surface

The public API is re-exported from a single entry point:

```python
from vmx import ...  # see vmx/__init__.py for the full list
```

| Export                          | Description                                       |
| ------------------------------- | ------------------------------------------------- |
| `ComponentVM`                   | Leaf viewmodel (no model)                         |
| `ComponentVMOf[M]`              | Leaf viewmodel with a typed model                 |
| `ReadonlyComponentVMOf[M]`      | Leaf VM with read-only model                      |
| `CompositeVM[VM]`               | Ordered collection of children + current slot     |
| `CompositeVMOf[M, VM]`          | Model-driven composite                            |
| `GroupVM[VM]`                   | Collection without current selection              |
| `AggregateVM1..5[…]`            | Fixed-arity named component slots                 |
| `ForwardingComponentVM`         | Decorator for `ComponentVMOfProto`                |
| `ForwardingCompositeVM`         | Decorator for composites                          |
| `RelayCommand`                  | Executable command with `can_execute` predicate   |
| `RelayCommandOfT[T]`            | Typed command with an argument                    |
| `MessageHub`                    | Pub/sub hub backed by `reactivex` `Subject`       |
| `RxDispatcher`                  | Foreground/background scheduler pair              |
| `ConstructionStatus`            | 5-state lifecycle enum                            |
| `StatusTransitionError`         | Raised on illegal lifecycle operations            |
| `BuilderValidationError`        | Raised when a builder is missing required fields  |
| `walk(root)`                    | DFS pre-order tree traversal generator            |
| `find(root, predicate)`         | Short-circuit tree search                         |

## Conformance

All 75 conformance IDs from `spec/12-conformance.md` are covered.

```
LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
CVM-001..006   COMP-001..013 GRP-001..006   AGG-001..005
FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
```

Run the suite:

```bash
uv run pytest
```

## Development

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

## License

MIT — see [`LICENSE`](../../LICENSE).
