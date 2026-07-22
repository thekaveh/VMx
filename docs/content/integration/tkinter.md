# 9.7. Tkinter Integration

Wire a `ComponentVMOf[M]` to a Tkinter widget through `StringVar`,
`IntVar`, and friends. Tkinter is included with CPython — no extra
dependency.

## 9.7.1. Reactivity primitive

Tkinter variables (`StringVar`, `IntVar`, `BooleanVar`, `DoubleVar`)
are observable: any widget bound via `textvariable=` re-renders when
the variable's `.set(value)` is called. There is no collection
observable; lists need to be re-applied to a `Listbox`.

## 9.7.2. Mapping

| Tkinter                   | VMx                                               |
| ------------------------- | ------------------------------------------------- |
| `StringVar.set(x)`        | `PropertyChangedMessage[str]` handler             |
| `tk.Button(command=fn)`   | `command.execute(None)` inside `fn`               |
| `Listbox.insert / delete` | `CollectionChangedMessage` handler                |
| `widget.after(...)`       | `RxDispatcher.asyncio(loop)` (or run-loop bridge) |

## 9.7.3. Adapter skeleton

```python
from collections.abc import Callable

import tkinter as tk
import reactivex.operators as ops
from vmx import ComponentVMOf, Message, MessageHubProto, PropertyChangedMessage, RelayCommand

def bind_string(var: tk.StringVar, vm: ComponentVMOf[Note],
                hub: MessageHubProto[Message], property_name: str = "model"
                ) -> Callable[[], None]:
    var.set(vm.model.title)

    def _on_msg(msg: PropertyChangedMessage[object]) -> None:
        if msg.property_name == property_name:
            var.set(vm.model.title)

    sub = hub.messages.pipe(
        ops.filter(lambda m: isinstance(m, PropertyChangedMessage) and m.sender is vm),
    ).subscribe(_on_msg)
    return sub.dispose

# Usage:
root = tk.Tk()
title_var = tk.StringVar()
save_command = RelayCommand.builder().task(save_note).build()
tk.Entry(root, textvariable=title_var).pack()
tk.Button(root, text="Save",
          command=lambda: save_command.execute(None)).pack()
dispose = bind_string(title_var, vm, hub)
root.protocol("WM_DELETE_WINDOW", lambda: (dispose(), root.destroy()))
root.mainloop()
```

## 9.7.4. Fuller example

[`examples/python/tk/todo_app/`](../../../examples/python/tk/todo_app/) — a
working Tkinter Todo app backed by a `CompositeVM[TodoItemVM]`.
