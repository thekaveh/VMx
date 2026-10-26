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
