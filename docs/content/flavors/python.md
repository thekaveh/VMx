# 7.3. Python

## Snapshot

- Install: `pip install vmx` or `uv add vmx`
- Publication status: `vmx` is published on PyPI; the repository source tree
  may be ahead of the latest public release.
- Reactive primitive: `reactivex`
- Naming idiom: snake_case

## What To Reach For

Python is the most direct fit when you want a typed but lightweight VM layer
for services, CLIs, TUIs, or desktop adapters without leaving idiomatic
dataclass and protocol-based code.

## Serviced Collections

`ServicedObservableCollection[T]` exposes local
`on_collection_changed` events and optionally forwards the same change to a
hub:

```python
notes = ServicedObservableCollection[Note](hub)
notes.append(first)
notes.append(second)
removed = notes.remove_at(-1)      # negative list index is accepted
old = notes.replace(-1, revised)   # returns the former item
notes.append(second)
notes.move(0, len(notes) - 1)      # move indices are strict and nonnegative
notes.replace_all(server_snapshot) # one Reset
```

List-style `remove(value)` returns `None` and raises `ValueError` when missing.
`remove_at` and `replace` accept normal negative indices, return the removed or
old item, and report a resolved nonnegative message position. `move` rejects
negative and out-of-range positions with `IndexError`. Empty Clear is a no-op,
and the caller retains item lifecycle ownership.

## Imperative Engine Bridge

`subscribe_value` returns Reactivex's `DisposableBase` and uses `==` unless an
`equality=` callable is supplied:

```python
from reactivex.abc import DisposableBase

from vmx import subscribe_value


def apply_exposure(exposure: float, _previous_exposure: float) -> None:
    material.uniforms.exposure.value = exposure


exposure_subscription: DisposableBase = subscribe_value(
    camera_vm,
    lambda vm: vm.model.exposure,
    apply_exposure,
    fire_immediately=True,
)

# Host adapter disposal:
exposure_subscription.dispose()
```

The callback receives `(current, previous)`; immediate delivery uses the
initial value for both. The host adapter owns the handle, and the selector
reevaluates after every property message from this fixed VM rather than on
every engine frame.

## Pointers

- Flavor README:
  [langs/python/README.md](../../../langs/python/README.md)
- Getting started guide:
  [docs/getting-started/python.md](../../getting-started/python.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- Textual recipe:
  [docs/integration/textual.md](../../integration/textual.md)

## Current Example Coverage

- Console: `examples/python/console/hello_vmx/`
- tkinter Todo app: `examples/python/tk/todo_app/`
- Textual inspector: `examples/python/textual/inspector/`
- Textual flagship: `examples/python/textual/notes_showcase/`

The flagship and inspector are the fastest way to see the hub, lifecycle, and
tree helpers under a real host.
