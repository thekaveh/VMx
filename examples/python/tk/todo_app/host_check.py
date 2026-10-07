"""Runs the Tk todo app on a real Tk root and checks its host lifecycle.

CI runs it under Xvfb::

    xvfb-run --auto-servernum uv run python -m todo_app.host_check

Every wait runs the Tk event loop through ``after`` timers and
``wait_variable`` with a bounded timeout, never a fixed delay. It prints every
step it checked, so a failure shows where it stopped.
"""

from __future__ import annotations

import gc
import tkinter as tk
import weakref
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from vmx.lifecycle.status import ConstructionStatus

from .__main__ import MainWindow


class HostCheckError(AssertionError):
    """A host lifecycle check failed."""


TRACE: list[str] = []


@runtime_checkable
class Tracked(Protocol):
    """reactivex types subscriptions as DisposableBase; the concrete ones track disposal."""

    is_disposed: bool


def disposed(subscription: object) -> bool:
    return isinstance(subscription, Tracked) and subscription.is_disposed


def expect(condition: bool, description: str) -> None:
    TRACE.append(("ok   " if condition else "FAIL ") + description)
    if not condition:
        raise HostCheckError(description)


def wait_until(root: tk.Tk, condition: Callable[[], bool], timeout_ms: int = 5_000) -> None:
    """Runs the Tk event loop until ``condition()`` holds or the timeout passes."""
    done = tk.BooleanVar(master=root, value=False)
    timed_out = False
    pending: list[str] = []

    def poll() -> None:
        if condition():
            done.set(True)
        else:
            pending[:] = [root.after(10, poll)]

    def expire() -> None:
        nonlocal timed_out
        timed_out = True
        done.set(True)

    timer = root.after(timeout_ms, expire)
    pending.append(root.after_idle(poll))
    root.wait_variable(done)
    root.after_cancel(timer)
    for identifier in pending:
        root.after_cancel(identifier)
    if timed_out:
        raise HostCheckError(f"timed out after {timeout_ms} ms waiting for the Tk loop")


def rows(window: MainWindow) -> list[str]:
    listbox = window._listbox
    return [str(listbox.get(index)) for index in range(listbox.size())]


def check_bindings_and_commands(root: tk.Tk) -> None:
    window = MainWindow(root)
    root.update_idletasks()
    expect(
        rows(window) == ["[ ] Buy groceries", "[ ] Review pull request", "[ ] Write unit tests"],
        "the Listbox shows the three seeded items",
    )
    expect(str(window._add_btn["state"]) == tk.DISABLED, "Add starts disabled for an empty title")

    window._entry_var.set("Ship the release")
    root.update_idletasks()
    expect(str(window._add_btn["state"]) == tk.NORMAL, "typing a title enables Add")
    window._add_btn.invoke()
    root.update_idletasks()
    expect(rows(window)[-1] == "[ ] Ship the release", "Add appends the typed item")
    expect(window._entry_var.get() == "", "Add clears the entry")

    window._listbox.selection_set(0)
    window._listbox.event_generate("<<ListboxSelect>>")
    wait_until(root, lambda: str(window._toggle_btn["state"]) == tk.NORMAL)
    expect(window._vm.composite.current is window._vm.items[0], "selecting a row selects its VM")
    window._toggle_btn.invoke()
    root.update_idletasks()
    expect(rows(window)[0] == "[x] Buy groceries", "Toggle Done updates the bound row")
    selection: tuple[int, ...] = window._listbox.curselection()  # type: ignore[no-untyped-call]
    expect(selection == (0,), "the selection survives the rebuild")

    window._remove_btn.invoke()
    root.update_idletasks()
    expect("[x] Buy groceries" not in rows(window), "Remove deletes the selected row")
    expect(str(window._remove_btn["state"]) == tk.DISABLED, "Remove disables with no selection")


def check_close_releases_subscriptions(root: tk.Tk) -> None:
    window = MainWindow(root)
    root.update_idletasks()
    subscriptions = [window._collection_sub, window._hub_sub, window._add_command_sub]
    vm = window._vm
    item = vm.items[0]
    vm_ref = weakref.ref(vm)
    expect(not any(disposed(sub) for sub in subscriptions), "the window holds live subscriptions")

    # The window manager's close button runs the registered protocol handler.
    root.tk.call(root.protocol("WM_DELETE_WINDOW"))
    expect(all(disposed(sub) for sub in subscriptions), "closing disposes every subscription")
    expect(vm.composite.status == ConstructionStatus.DISPOSED, "closing disposes the composite")
    # Shutdown destructs each item, then the composite's dispose cascade
    # (LIFE-013) disposes it.
    expect(item.status == ConstructionStatus.DISPOSED, "closing disposes each child item")
    expect(not item.toggle_done.can_execute(), "closing disposes each item's command")
    expect(not vm.add_command.can_execute(), "closing disposes the add command")

    del window, vm, item, subscriptions
    gc.collect()
    expect(vm_ref() is None, "no reference keeps the window's view-model alive")


def main() -> None:
    checks = [check_bindings_and_commands, check_close_releases_subscriptions]
    try:
        for check in checks:
            root = tk.Tk()
            root.withdraw()
            try:
                check(root)
            finally:
                try:
                    root.destroy()
                except tk.TclError:
                    pass  # the close check already destroyed it
    finally:
        print("\n".join(TRACE))
    print(f"Tk todo app host check: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
