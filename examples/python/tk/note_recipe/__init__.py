"""Tkinter integration recipe.

The regions between ``docs-snippet`` markers are the exact code shown in
docs/content/integration/tkinter.md; ``make docs-check`` keeps the page
identical to them. ``python -m note_recipe`` executes the recipe on a real Tk
root (CI runs it under Xvfb).
"""

from __future__ import annotations

# docs-snippet:start tk-binding
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
        # docs-snippet:end tk-binding


# docs-snippet:start tk-window
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
    # docs-snippet:end tk-window


def run(vm: ComponentVMOf[Note], save_command: RelayCommand) -> None:
    """Shows the window until it is closed. Type-checked, not executed in CI."""
    # docs-snippet:start tk-run
    root = tk.Tk()
    build_window(root, vm, save_command)
    root.mainloop()
    # docs-snippet:end tk-run
