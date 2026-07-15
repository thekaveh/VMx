# 7.3. Python

## 7.3.1. Snapshot

- Install: `pip install vmx` or `uv add vmx`
- Publication status: `vmx` is published on PyPI; the repository source tree
  may be ahead of the latest public release.
- Reactive primitive: `reactivex`
- Naming idiom: snake_case
- Hub concurrency: ordinary producers retain synchronous calling-thread
  delivery while nested cross-hub callbacks enqueue without a wait cycle

## 7.3.2. What To Reach For

Python is the most direct fit when you want a typed but lightweight VM layer
for services, CLIs, TUIs, or desktop adapters without leaving idiomatic
dataclass and protocol-based code.

## 7.3.3. Serviced Collections

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

Use `KeyedServicedObservableCollection[TKey, T]` when the same sequence needs
captured-key lookup and upsert without snapshot scans:

```python
notes_by_id = KeyedServicedObservableCollection[str, Note](
    lambda note: note.id,
    hub,
)
notes_by_id.append(first)
note = notes_by_id.get(first.id)
added = notes_by_id.upsert(revised)  # False: Replace at the same position
removed = notes_by_id.delete(first.id)
```

`contains_key` tests membership. The type retains the full `MutableSequence`
integer and slice surface; slice assignment/deletion and `reverse()` validate
and commit atomically. A key is captured per membership, so mutating `id` does
not silently rekey it; indexed replacement or delete-then-add is explicit.
Duplicate keys, projector failures, and invalid slice shapes preserve state and
emit nothing. A same mutated instance can occupy both its old and newly
projected memberships. Lookup and target discovery are expected O(1), append is
amortized O(1), and ordered middle shifts remain O(n). Local changes are
immediate even when an external hub transaction defers hub publication. Items
remain caller-owned, and the collection has no batch or VM lifecycle role.

## 7.3.4. Imperative Engine Bridge

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

## 7.3.5. Pointers

- Flavor README:
  [langs/python/README.md](../../../langs/python/README.md)
- Getting started guide:
  [Getting Started with VMx — Python](../getting-started/python.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- Textual recipe:
  [Textual Integration](../integration/textual.md)

## 7.3.6. Current Example Coverage

- Console: `examples/python/console/hello_vmx/`
- tkinter Todo app: `examples/python/tk/todo_app/`
- Textual inspector: `examples/python/textual/inspector/`
- Textual flagship: `examples/python/textual/notes_showcase/`

The flagship and inspector are the fastest way to see the hub, lifecycle, and
tree helpers under a real host.
