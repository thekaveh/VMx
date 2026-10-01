"""Executes the Tkinter integration recipe on a real Tk root.

Run with ``python -m note_recipe`` from examples/python. It needs a display;
CI runs it under ``xvfb-run``. Each check raises ``RecipeCheckError`` on a
mismatch, so a failure exits non-zero.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from collections.abc import Callable

from vmx import ComponentVMOf, Message, MessageHub, RelayCommand, RxDispatcher

from . import Note, NoteBinding, build_window


class RecipeCheckError(AssertionError):
    """A recipe behavior did not match the documented contract."""


def expect(condition: bool, description: str) -> None:
    if not condition:
        raise RecipeCheckError(description)


def pump(root: tk.Tk, until: Callable[[], bool], timeout_s: float = 5.0) -> None:
    """Runs the Tk loop until ``until()`` holds or the timeout passes."""
    deadline = time.monotonic() + timeout_s
    while not until():
        if time.monotonic() > deadline:
            raise RecipeCheckError("timed out waiting for the Tk loop")
        root.update()
        time.sleep(0.01)


def make_vm(hub: MessageHub[Message]) -> ComponentVMOf[Note]:
    return (
        ComponentVMOf[Note]
        .builder()
        .name("note")
        .model(Note("draft"))
        .services(hub, RxDispatcher.immediate())
        .build()
    )


def check_initial_values_and_lifecycle(root: tk.Tk) -> None:
    hub: MessageHub[Message] = MessageHub()
    vm = make_vm(hub)
    binding = NoteBinding(root, vm)
    expect(binding.title.get() == "draft", "the title shows the current model at once")
    expect(binding.status.get() == "DESTRUCTED", "the status shows the current status at once")

    vm.construct()
    pump(root, lambda: binding.status.get() == "CONSTRUCTED")
    vm.destruct()
    pump(root, lambda: binding.status.get() == "DESTRUCTED")
    binding.dispose()
    vm.dispose()


def check_changes_reach_the_tk_thread(root: tk.Tk) -> None:
    hub: MessageHub[Message] = MessageHub()
    vm = make_vm(hub)
    vm.construct()
    binding = NoteBinding(root, vm)
    tk_thread = threading.get_ident()
    writes: list[int] = []
    binding.title.trace_add("write", lambda *_: writes.append(threading.get_ident()))

    vm.model = Note("edited on the Tk thread")
    pump(root, lambda: binding.title.get() == "edited on the Tk thread")

    worker = threading.Thread(target=lambda: setattr(vm, "model", Note("edited on a worker")))
    worker.start()
    worker.join()
    expect(
        binding.title.get() == "edited on the Tk thread", "a worker change waits for the Tk loop"
    )
    pump(root, lambda: binding.title.get() == "edited on a worker")
    expect(writes == [tk_thread, tk_thread], "each change is written once, on the Tk thread")
    binding.dispose()
    vm.dispose()


def check_window_command_and_cleanup(root: tk.Tk) -> None:
    hub: MessageHub[Message] = MessageHub()
    vm = make_vm(hub)
    vm.construct()
    saved: list[str] = []
    save_command = RelayCommand.builder().task(lambda: saved.append(vm.model.title)).build()
    binding = build_window(root, vm, save_command)

    buttons = [child for child in root.winfo_children() if isinstance(child, tk.Button)]
    expect(len(buttons) == 1, "the window has one Save button")
    buttons[0].invoke()
    expect(saved == ["draft"], "Save runs the supplied command once")
    expect(vm.is_constructed, "Save leaves the VM's lifecycle to its owner")

    binding.dispose()
    vm.model = Note("after dispose")
    for _ in range(10):
        root.update()
        time.sleep(0.01)
    expect(binding.title.get() == "draft", "a disposed binding stops showing changes")
    expect(vm.is_constructed, "dispose() leaves the VM to its owner")
    vm.dispose()


def main() -> None:
    checks = [
        check_initial_values_and_lifecycle,
        check_changes_reach_the_tk_thread,
        check_window_command_and_cleanup,
    ]
    for check in checks:
        root = tk.Tk()
        root.withdraw()
        try:
            check(root)
        finally:
            root.destroy()
    print(f"Tkinter recipe: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
