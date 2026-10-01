# 9.7. Tkinter Integration

Wire a `ComponentVMOf[M]` to a Tkinter widget through `StringVar`,
`IntVar`, and friends. Tkinter is included with CPython — no extra
dependency.

## 9.7.1. Reactivity primitive

Tkinter variables (`StringVar`, `IntVar`, `BooleanVar`, `DoubleVar`)
are observable: any widget bound via `textvariable=` re-renders when
the variable's `.set(value)` is called. There is no collection
observable; lists need to be re-applied to a `Listbox`. Tk widgets and
variables may only be touched from the thread that runs `mainloop()`.

## 9.7.2. Mapping

| Tkinter                 | VMx                                                           |
| ----------------------- | ------------------------------------------------------------- |
| `StringVar.set(x)`      | apply a queued `property_changed` name on the Tk thread       |
| `tk.Button(command=fn)` | `command.execute(None)` inside `fn`                           |
| `Listbox.insert/delete` | `CollectionChangedMessage` handler, applied on the Tk thread  |
| `root.after(ms, fn)`    | drain a thread-safe queue that VM notifications are posted to |

## 9.7.3. Adapter skeleton

The code below is the exact module that CI runs under Xvfb
(`examples/python/tk/note_recipe`, run with `python -m note_recipe`). The run
shows the initial values, follows `model` and `status` changes made on the Tk
thread and on a worker, runs the Save command, and stops on `dispose()`.

Subscribe to the VM's own `property_changed` stream. It carries every `model`
assignment and every lifecycle `status` change, on the thread that made the
change. Tk is not thread-safe, so the binding queues each change and applies it
on the Tk thread from `root.after`:

<!-- checked-snippet: examples/python/tk/note_recipe/__init__.py#tk-binding -->

```python
import queue
import tkinter as tk
from dataclasses import dataclass

from vmx import ComponentVMOf, RelayCommand


@dataclass(frozen=True)
class Note:
    title: str


class NoteBinding:
    """Shows a borrowed note VM in Tk variables.

    Whoever created the VM constructs and disposes it; ``dispose()`` only stops
    this binding.
    """

    def __init__(self, root: tk.Misc, vm: ComponentVMOf[Note], poll_ms: int = 50) -> None:
        self.title = tk.StringVar(master=root)
        self.status = tk.StringVar(master=root)
        self._root = root
        self._vm = vm
        self._poll_ms = poll_ms
        # `property_changed` carries `model` assignments and every lifecycle
        # `status` change, on the thread that made the change. Tk is not
        # thread-safe, so queue the names and apply them on the Tk thread.
        self._changes: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._subscription = vm.property_changed.subscribe(self._changes.put)
        # Read after subscribing, so a change in between is not lost.
        self._show("model")
        self._show("status")
        self._after_id: str | None = root.after(poll_ms, self._drain)

    def _drain(self) -> None:
        while True:
            try:
                property_name = self._changes.get_nowait()
            except queue.Empty:
                break
            self._show(property_name)
        self._after_id = self._root.after(self._poll_ms, self._drain)

    def _show(self, property_name: str) -> None:
        if property_name == "model":
            self.title.set(self._vm.model.title)
        elif property_name == "status":
            self.status.set(self._vm.status.name)

    def dispose(self) -> None:
        self._subscription.dispose()
        if self._after_id is not None:
            self._root.after_cancel(self._after_id)
            self._after_id = None
```

Build the window around the binding, and stop the binding before the window
closes:

<!-- checked-snippet: examples/python/tk/note_recipe/__init__.py#tk-window -->

```python
def build_window(root: tk.Tk, vm: ComponentVMOf[Note], save_command: RelayCommand) -> NoteBinding:
    binding = NoteBinding(root, vm)
    tk.Label(root, textvariable=binding.title).pack()
    tk.Label(root, textvariable=binding.status).pack()
    tk.Button(root, text="Save", command=lambda: save_command.execute(None)).pack()

    def close() -> None:
        binding.dispose()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    return binding
```

Run it on the main thread:

<!-- checked-snippet: examples/python/tk/note_recipe/__init__.py#tk-run -->

```python
root = tk.Tk()
build_window(root, vm, save_command)
root.mainloop()
```

- **Current values at once.** The binding reads `model` and `status` right
  after subscribing, so no change in between is lost.
- **Tk thread only.** A change made on a worker reaches the variables on the
  next `after` tick, on the Tk thread.
- **Borrowed lifetime.** `dispose()` stops the subscription and the polling,
  and nothing else. The code that created the VM constructs and disposes it.

If this host also owns an asyncio loop, capture it while running before creating
`RxDispatcher.asyncio(loop)` and explicitly clean up its background pool as
shown in [Python asyncio dispatcher ownership](../primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership).

## 9.7.4. Fuller example

[`examples/python/tk/todo_app/`](../../../examples/python/tk/todo_app/) — a
working Tkinter Todo app backed by a `CompositeVM[TodoItemVM]`.
