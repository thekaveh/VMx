# 9.5. Textual Integration

Wire a `ComponentVMOf[M]` to a [Textual](https://textual.textualize.io/)
TUI widget through Textual's `reactive` descriptors.

## 9.5.1. Reactivity primitive

Textual widgets re-render when a `reactive(...)` attribute changes. A VMx VM
reports its own changes on `property_changed`, an observable of snake_case
property names: a setter such as `model` publishes a `PropertyChangedMessage`
to the hub and then emits its name there, and every lifecycle transition
publishes a `ConstructionStatusChangedMessage` and then emits `status`. The hub
never carries a `PropertyChangedMessage` for `status`.

## 9.5.2. Mapping

| Textual                | VMx                                                |
| ---------------------- | -------------------------------------------------- |
| `reactive("value")`    | `vm.property_changed` (VM-local names)             |
| `Binding` + `action_*` | `RelayCommand.execute()`                           |
| `ListView` items       | `ObservableList[T]` + `CollectionChangedMessage`   |
| `DataTable` rows       | a projection's items by key, selected by key       |
| `post_message`         | thread-safe hand-off of a change to the App thread |

## 9.5.3. Adapter skeleton

The widget below is the exact module that the Textual Notes-Showcase tests run
on a live App (`examples/python/textual/notes_showcase/tests/views/`), including
a change made on a worker thread.

<!-- checked-snippet: examples/python/textual/notes_showcase/tests/views/textual_recipe.py -->

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from reactivex.abc import DisposableBase
from textual.app import RenderResult
from textual.binding import Binding, BindingType
from textual.message import Message as TextualMessage
from textual.reactive import reactive
from textual.widget import Widget
from vmx import ComponentVMOf, RelayCommand


@dataclass
class Note:
    title: str


class NoteWidget(Widget, can_focus=True):
    """Shows a borrowed note VM; whoever created the VM constructs and disposes it."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("s", "save", "Save")]

    title: reactive[str] = reactive("")
    status_text: reactive[str] = reactive("")

    class VmChanged(TextualMessage):
        """Carries one VM-local property change onto the App thread."""

        def __init__(self, property_name: str) -> None:
            super().__init__()
            self.property_name = property_name

    def __init__(self, vm: ComponentVMOf[Note], save_command: RelayCommand) -> None:
        super().__init__()
        self._vm = vm
        self._save_command = save_command
        self._subscription: DisposableBase | None = None

    def on_mount(self) -> None:
        # `property_changed` is the VM-local stream: it carries `model`
        # assignments and every lifecycle `status` change, on the thread that
        # made the change. `post_message` is thread-safe and queues each change
        # for this widget on the App thread.
        self._subscription = self._vm.property_changed.subscribe(self._forward)
        # Read after subscribing, so a change in between is not lost.
        self._show("model")
        self._show("status")

    def _forward(self, property_name: str) -> None:
        self.post_message(self.VmChanged(property_name))

    def on_note_widget_vm_changed(self, message: NoteWidget.VmChanged) -> None:
        self._show(message.property_name)

    def _show(self, property_name: str) -> None:
        if property_name == "model":
            self.title = self._vm.model.title
        elif property_name == "status":
            self.status_text = self._vm.status.name

    def render(self) -> RenderResult:
        return f"{self.title} · {self.status_text}"

    def action_save(self) -> None:
        self._save_command.execute(None)

    def on_unmount(self) -> None:
        if self._subscription is not None:
            self._subscription.dispose()
            self._subscription = None
```

- **One notification path.** Subscribe to `property_changed` only. Also
  handling the hub's `PropertyChangedMessage` notifies `model` twice, and the
  hub never carries `status`.
- **Current values at once.** `on_mount` subscribes, then reads the VM, so the
  first render shows the current title and status and a change made in between
  is not lost.
- **App thread only.** `property_changed` emits on the thread that made the
  change. `post_message` is thread-safe, so the widget reads the VM and assigns
  its reactive attributes only on the App thread. Each handled message shows
  the VM's current value, so a transient status such as `CONSTRUCTING` may be
  skipped when it is already over.
- **Borrowed lifetime.** `on_unmount` disposes the subscription and nothing
  else. The code that created the VM constructs and disposes it.

A host that runs VMx work on its own threads owns that dispatcher and its
teardown. Follow the
[Python asyncio dispatcher ownership](../primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership)
sequence. The Notes-Showcase `TextualDispatcher` is an example of such a host
dispatcher. It is in
`examples/python/textual/notes_showcase/src/notes_showcase/views/adapter/dispatcher.py`
and is not part of `vmx`.

## 9.5.4. Grids With DataTable

A `ListView` binds to a `CompositeVM`. A `DataTable` grid has a different
shape: its rows usually come from a paged or filtered projection, such as
`PagedComposition.items`, and its selection is a cursor coordinate rather than
a child VM. Textual also moves that cursor itself. `clear()` resets it, the
first row added is highlighted, and turning `show_cursor` on highlights again.
A binding that treats every highlight as a choice would select a row each time
the grid repaints.

The Textual Notes-Showcase adapter ships `bind_data_table` for this shape
(`examples/python/textual/notes_showcase/src/notes_showcase/views/adapter/data_table.py`).
It keys every row by a stable string and selects by that key:

- Moving the cursor to another row, by keys or a click, calls `select(key)`
  once. Enter, or a click on the highlighted row, selects that row as well, so
  a single-row table can still be chosen.
- Rebuilding the rows, Textual's own highlights, and a selection changed by the
  VM never call `select`.
- After each render the cursor rests on the selected key's row. If that row
  was removed or filtered out, no other row is selected until the operator
  acts.
- `changes` may emit on any thread. The bridge renders on the App thread, and
  disposing the binding removes its hooks from the table.

The grid below is the module that the Notes-Showcase tests run on a live App,
including a change made on a worker thread.

<!-- checked-snippet: examples/python/textual/notes_showcase/tests/views/data_table_recipe.py -->

```python
from __future__ import annotations

from dataclasses import dataclass

import reactivex as rx
from reactivex.abc import DisposableBase
from textual.widgets import DataTable
from vmx import ComponentVMOf, Message, MessageHub, ObservableList, PagedComposition, RxDispatcher

from notes_showcase.views.adapter import bind_data_table


@dataclass(frozen=True)
class Instance:
    id: str
    name: str
    status: str


class InstanceGrid:
    """A paged, filtered projection of instances; the selection is held by key."""

    def __init__(self, hub: MessageHub[Message], page_size: int = 0) -> None:
        dispatcher = RxDispatcher.immediate()
        self.instances: ObservableList[Instance] = ObservableList()
        self.filter = (
            ComponentVMOf[str].builder().name("filter").model("").services(hub, dispatcher).build()
        )
        self.selection = (
            ComponentVMOf[str | None]
            .builder()
            .name("selection")
            .model(None)
            .services(hub, dispatcher)
            .build()
        )
        self.page = PagedComposition(self._visible, page_size)
        # A factory source sends no change signal, so the page index is not
        # re-clamped when the rows shrink. Re-clamp it here. The table renders
        # later on the App loop, so it reads the re-clamped page.
        self._reclamp = rx.merge(
            self.instances.on_property_changed, self.filter.property_changed
        ).subscribe(lambda _: self._reclamp_page())
        # Everything that can change the visible rows or the selection.
        self.changes = rx.merge(
            self.instances.on_property_changed,
            self.filter.property_changed,
            self.page.on_property_changed,
            self.selection.property_changed,
        )
        self.filter.construct()
        self.selection.construct()

    def _visible(self) -> list[Instance]:
        return [instance for instance in self.instances if self.filter.model in instance.name]

    def _reclamp_page(self) -> None:
        # The setter clamps the index to the current page count.
        self.page.current_page_index = self.page.current_page_index

    def select(self, key: str) -> None:
        self.selection.model = key

    def dispose(self) -> None:
        self._reclamp.dispose()
        self.page.dispose()
        self.filter.dispose()
        self.selection.dispose()
        self.instances.dispose()


class InstanceTable(DataTable[str]):
    """Shows a borrowed grid; whoever created the grid disposes it."""

    def __init__(self, grid: InstanceGrid) -> None:
        super().__init__(cursor_type="row")
        self._grid = grid
        self._binding: DisposableBase | None = None

    def on_mount(self) -> None:
        self.add_columns("Name", "Status")
        # Rows are keyed by instance id. Moving the cursor to a row, or
        # pressing Enter on it, selects that key; rebuilding the rows never does.
        self._binding = bind_data_table(
            self,
            rows=lambda: self._grid.page.items,
            key=lambda instance: instance.id,
            cells=lambda instance: (instance.name, instance.status),
            selected_key=lambda: self._grid.selection.model,
            select=self._grid.select,
            changes=self._grid.changes,
        )

    def on_unmount(self) -> None:
        if self._binding is not None:
            self._binding.dispose()
            self._binding = None
```

`changes` merges every stream that can change the rows or the selection:
the source list, the filter, the page, and the selection itself.

## 9.5.5. Fuller example

- [`examples/python/textual/inspector/`](../../../examples/python/textual/inspector/) —
  a Textual viewer for any VMx tree, demonstrating the hub-subscription
  pattern at scale.
- [`examples/python/textual/notes_showcase/`](../../../examples/python/textual/notes_showcase/) —
  the Notes-Showcase Textual flagship: full `WorkspaceVM` and `ThemeVM` with
  `bind_property` / `bind_command` helpers and the `bind_data_table` grid
  bridge.
