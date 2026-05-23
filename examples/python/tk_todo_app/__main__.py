"""tk_todo_app — tkinter MVVM todo demo for the VMx Python library.

Architecture:
  - TodoItem            — immutable @dataclass domain model (title + done flag).
  - TodoItemVM          — subclass of ComponentVMOf[TodoItem]; adds a
                          toggle_done RelayCommand so it can live directly
                          inside a CompositeVM.
  - MainWindowViewModel — holds a CompositeVM[TodoItemVM]; exposes add/remove
                          commands and a new_item_title string.
  - MainWindow          — tkinter root window; wires Listbox + buttons to the VM.

Run with:
    uv run python -m tk_todo_app     (from examples/python/ — requires a display)
    python -m tk_todo_app            (with vmx on sys.path)

Import-only / headless check (no display needed):
    python -c "from tk_todo_app.__main__ import MainWindow, MainWindowViewModel"
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, replace

from vmx.commands.relay_command import RelayCommand
from vmx.components.component_vm import ComponentVMOf
from vmx.composites.composite_vm import CompositeVM
from vmx.messages.protocols import Message
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TodoItem:
    """Immutable domain model for a single to-do item."""

    title: str
    done: bool = False


# ---------------------------------------------------------------------------
# TodoItemVM — ComponentVMOf[TodoItem]
# ---------------------------------------------------------------------------


class TodoItemVM(ComponentVMOf[TodoItem]):
    """ViewModel for a single to-do item.

    Subclasses ``ComponentVMOf[TodoItem]`` so it can be stored directly inside
    a ``CompositeVM`` (which requires ``_ComponentVMBase`` children).

    Added on top of the base class:
      - ``toggle_done`` — RelayCommand that flips the Done flag.
      - ``display``     — formatted string for the Listbox.
    """

    def __init__(
        self,
        item: TodoItem,
        hub: MessageHub[Message],
        dispatcher: RxDispatcher,
    ) -> None:
        super().__init__(
            name=item.title,
            hint="",
            initial_model=item,
            modeled_hinter=lambda t: f"[{'x' if t.done else ' '}] {t.title}",
            on_model_changed=None,
            hub=hub,
            dispatcher=dispatcher,
        )

        self.toggle_done: RelayCommand = (
            RelayCommand.builder()
            .predicate(lambda: self.is_constructed)
            .task(self._do_toggle)
            .triggers(self.property_changed)
            .build()
        )

    def _do_toggle(self) -> None:
        self.model = replace(self.model, done=not self.model.done)

    @property
    def title(self) -> str:
        return self.model.title

    @property
    def done(self) -> bool:
        return self.model.done

    @property
    def display(self) -> str:
        """Formatted label for the Listbox (e.g. ``[x] Buy groceries``)."""
        return self.modeled_hint

    def dispose(self) -> None:
        self.toggle_done.dispose()
        super().dispose()


# ---------------------------------------------------------------------------
# MainWindowViewModel
# ---------------------------------------------------------------------------


class MainWindowViewModel:
    """Top-level ViewModel for :class:`MainWindow`.

    Holds a ``CompositeVM[TodoItemVM]`` so every child VM participates in
    the same hub, demonstrating cross-VM message flow.
    """

    def __init__(self) -> None:
        self._hub: MessageHub[Message] = MessageHub()
        self._dispatcher = RxDispatcher.immediate()

        # Non-modeled composite — children are added imperatively.
        self._composite: CompositeVM[TodoItemVM] = (
            CompositeVM.builder()
            .name("todo-list")
            .services(self._hub, self._dispatcher)
            .build()
        )
        self._composite.construct()

        # Mutable UI state (mirrors WPF's NewItemTitle two-way binding).
        self.new_item_title: str = ""

        # Commands wired to UI buttons.
        self.add_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(lambda: bool(self.new_item_title.strip()))
            .task(self._do_add)
            .build()
        )
        self.remove_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(lambda: self._composite.current is not None)
            .task(self._do_remove)
            .triggers(self._composite.property_changed)
            .build()
        )

        # Seed with a few items so the list isn't empty on launch.
        for title in ("Buy groceries", "Review pull request", "Write unit tests"):
            self._add_item(title)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def items(self) -> list[TodoItemVM]:
        return list(self._composite)

    @property
    def composite(self) -> CompositeVM[TodoItemVM]:
        return self._composite

    @property
    def hub(self) -> MessageHub[Message]:
        return self._hub

    def select_by_index(self, index: int) -> None:
        """Select the item at *index* as the composite's current child."""
        items = list(self._composite)
        if 0 <= index < len(items):
            vm = items[index]
            if self._composite.can_select_component(vm):
                self._composite.select_component(vm)

    def shutdown(self) -> None:
        """Destruct all children, dispose the composite and hub."""
        for item_vm in list(self._composite):
            item_vm.destruct()
        self._composite.destruct()
        self._composite.dispose()
        self.add_command.dispose()
        self.remove_command.dispose()
        self._hub.dispose()

    # ── Private helpers ───────────────────────────────────────────────────

    def _add_item(self, title: str) -> None:
        item_vm = TodoItemVM(TodoItem(title.strip()), self._hub, self._dispatcher)
        item_vm.construct()
        self._composite.append(item_vm)

    def _do_add(self) -> None:
        title = self.new_item_title.strip()
        if title:
            self._add_item(title)
            self.new_item_title = ""

    def _do_remove(self) -> None:
        current = self._composite.current
        if current is not None:
            current.destruct()
            self._composite.remove(current)
            current.dispose()


# ---------------------------------------------------------------------------
# MainWindow — tkinter view
# ---------------------------------------------------------------------------


class MainWindow:
    """Tkinter root window wired to :class:`MainWindowViewModel`.

    Layout::

        ┌─────────────────────────────────┐
        │ [Listbox of todo items]         │
        ├─────────────────────────────────┤
        │ [Entry: new item title] [Add]   │
        │ [Toggle Done]  [Remove]         │
        └─────────────────────────────────┘
    """

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._vm = MainWindowViewModel()

        root.title("VMx Todo App")
        root.resizable(True, True)

        self._build_ui()
        self._refresh_list()

        # Subscribe to composite collection changes to keep the Listbox in sync.
        self._collection_sub = self._vm.composite.on_collection_changed.subscribe(
            on_next=lambda _: self._refresh_list()
        )

        # Subscribe to hub messages to catch model changes (e.g. toggle done).
        self._hub_sub = self._vm.hub.messages.subscribe(
            on_next=lambda _: self._refresh_list()
        )

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self._root

        # ── Listbox frame ────────────────────────────────────────────────
        list_frame = tk.Frame(root)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self._listbox = tk.Listbox(
            list_frame,
            width=48,
            height=12,
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self._listbox.yview)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # ── Add-item row ─────────────────────────────────────────────────
        add_frame = tk.Frame(root)
        add_frame.pack(fill=tk.X, padx=8, pady=2)

        self._entry_var = tk.StringVar()
        self._entry_var.trace_add("write", self._on_entry_changed)
        entry = tk.Entry(add_frame, textvariable=self._entry_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda _e: self._on_add())

        self._add_btn = tk.Button(add_frame, text="Add", command=self._on_add)
        self._add_btn.pack(side=tk.LEFT, padx=(4, 0))

        # ── Action row ───────────────────────────────────────────────────
        action_frame = tk.Frame(root)
        action_frame.pack(fill=tk.X, padx=8, pady=(2, 8))

        self._toggle_btn = tk.Button(
            action_frame, text="Toggle Done", command=self._on_toggle
        )
        self._toggle_btn.pack(side=tk.LEFT)

        self._remove_btn = tk.Button(
            action_frame, text="Remove", command=self._on_remove
        )
        self._remove_btn.pack(side=tk.LEFT, padx=(4, 0))

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_entry_changed(self, *_: object) -> None:
        self._vm.new_item_title = self._entry_var.get()
        self._add_btn.config(
            state=tk.NORMAL if self._vm.add_command.can_execute() else tk.DISABLED
        )

    def _on_listbox_select(self, _event: object) -> None:
        sel = self._listbox.curselection()
        if sel:
            self._vm.select_by_index(sel[0])
        self._refresh_button_states()

    def _on_add(self) -> None:
        self._vm.add_command.execute()
        self._entry_var.set("")

    def _on_toggle(self) -> None:
        current = self._vm.composite.current
        if current is not None:
            current.toggle_done.execute()

    def _on_remove(self) -> None:
        self._vm.remove_command.execute()

    def _on_close(self) -> None:
        self._collection_sub.dispose()
        self._hub_sub.dispose()
        self._vm.shutdown()
        self._root.destroy()

    # ── UI refresh ────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        """Rebuild the Listbox from the VM's items list."""
        prev_sel = self._listbox.curselection()
        self._listbox.delete(0, tk.END)
        for item_vm in self._vm.items:
            self._listbox.insert(tk.END, item_vm.display)
        # Restore selection if still valid.
        if prev_sel:
            idx = prev_sel[0]
            if idx < self._listbox.size():
                self._listbox.selection_set(idx)
        self._refresh_button_states()

    def _refresh_button_states(self) -> None:
        has_selection = self._vm.composite.current is not None
        state = tk.NORMAL if has_selection else tk.DISABLED
        self._toggle_btn.config(state=state)
        self._remove_btn.config(state=state)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
