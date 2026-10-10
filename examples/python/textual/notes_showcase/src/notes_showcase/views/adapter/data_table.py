"""DataTableBridge — a list-shaped projection → Textual :class:`DataTable` rows.

:func:`bind_collection` binds a ``ListView`` to a ``CompositeVM``. A grid is a
different shape: its rows come from a paged or filtered projection (for
example :class:`vmx.PagedComposition.items`), and its selection is a cursor
coordinate. This bridge keys every row by a stable string and selects by that
key, so the VM never sees a row index.

Who selects:

* The operator. Moving the cursor to another row (arrow keys, paging keys, a
  click) calls ``select(key)`` once. Enter, or a click on the highlighted
  row, posts Textual's ``RowSelected`` and selects that row too, so a
  single-row table can still be chosen.
* Nobody else. Rebuilding the rows resets and restores the cursor, and
  Textual highlights the first row added and re-highlights when
  ``show_cursor`` turns on. None of that calls ``select``: the bridge watches
  the cursor reactive itself and ignores every change it makes. A selection
  changed by the VM moves the cursor without echoing back.

After each render the cursor rests on the selected key's row. When that row
was removed or filtered out, the cursor stays where Textual left it and no
other row is selected until the operator acts.

Threading: bind on the App thread (for example in ``on_mount``). A change
signalled on any thread is rendered on the App thread, in the App's context.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Generic, TypeVar

import reactivex as rx
from reactivex.abc import DisposableBase
from textual.coordinate import Coordinate
from textual.message import Message as TextualMessage
from textual.widgets import DataTable

from notes_showcase.views.adapter.property import _invoke_class_watcher

T = TypeVar("T")

_Entry = tuple[str, tuple[object, ...]]


def bind_data_table(
    table: DataTable[Any],
    *,
    rows: Callable[[], Sequence[T]],
    key: Callable[[T], str],
    cells: Callable[[T], Sequence[object]],
    selected_key: Callable[[], str | None],
    select: Callable[[str], None],
    changes: rx.Observable[Any],
) -> DisposableBase:
    """Bind ``table``'s rows to ``rows()`` and its cursor to a selection by key.

    Parameters
    ----------
    table:
        A mounted :class:`~textual.widgets.DataTable` whose columns are already
        added. The bridge owns its rows.
    rows:
        Returns the projection to show, read fresh on every render.
    key:
        Maps an item to its row key. Keys must be unique within ``rows()``.
    cells:
        Maps an item to its cell values, one per column.
    selected_key:
        Returns the key the VM currently selects, or ``None``.
    select:
        Called with a row's key when the operator chooses that row. It is
        never called with ``None`` and never for a row the bridge moved to.
    changes:
        Emits whenever ``rows()`` or ``selected_key()`` may have changed, on
        any thread. Merge every stream that can change either one.

    Returns a disposable. Disposing it stops rendering and selecting and
    removes the bridge's hooks from ``table``; the rows stay as they are.
    """
    return _DataTableBinding(table, rows, key, cells, selected_key, select, changes)


class _DataTableBinding(DisposableBase, Generic[T]):
    def __init__(
        self,
        table: DataTable[Any],
        rows: Callable[[], Sequence[T]],
        key: Callable[[T], str],
        cells: Callable[[T], Sequence[object]],
        selected_key: Callable[[], str | None],
        select: Callable[[str], None],
        changes: rx.Observable[Any],
    ) -> None:
        self._table = table
        self._rows = rows
        self._key = key
        self._cells = cells
        self._selected_key = selected_key
        self._select = select
        self._loop = asyncio.get_running_loop()
        self._context = contextvars.copy_context()
        self._rendered: list[_Entry] | None = None
        self._applying = 0
        self._disposed = False
        self._hook(table)
        self._render()
        self._subscription = changes.subscribe(on_next=lambda _: self._schedule())

    # ── Table hooks ───────────────────────────────────────────────────────

    def _hook(self, table: DataTable[Any]) -> None:
        widget: Any = table
        class_watcher = getattr(type(table), "watch_cursor_coordinate", None)
        post_message = widget.post_message

        def _watch_cursor_coordinate(old: Coordinate, new: Coordinate) -> None:
            # Chain Textual's own watcher: it repaints and posts RowHighlighted.
            if class_watcher is not None:
                _invoke_class_watcher(class_watcher, table, old, new)
            if new.row != old.row:
                self._operator_chose(self._key_at(new.row))

        def _post_message(message: TextualMessage) -> bool:
            if isinstance(message, DataTable.RowSelected) and message.data_table is table:
                self._operator_chose(str(message.row_key.value))
            elif isinstance(message, DataTable.CellSelected) and message.data_table is table:
                self._operator_chose(str(message.cell_key.row_key.value))
            return bool(post_message(message))

        # Instance attributes shadow the class methods: Textual looks both up
        # by name, as the ListView bridge's ``watch_index`` override relies on.
        widget.watch_cursor_coordinate = _watch_cursor_coordinate
        widget.post_message = _post_message

    def _key_at(self, row: int) -> str | None:
        if self._rendered is None or not 0 <= row < len(self._rendered):
            return None
        return self._rendered[row][0]

    def _operator_chose(self, key: str | None) -> None:
        if self._disposed or self._applying or key is None:
            return
        if key != self._selected_key():
            self._select(key)

    # ── Rendering ─────────────────────────────────────────────────────────

    @contextmanager
    def _bridge_changes(self) -> Iterator[None]:
        self._applying += 1
        try:
            yield
        finally:
            self._applying -= 1

    def _schedule(self) -> None:
        if self._disposed:
            return
        try:
            self._loop.call_soon_threadsafe(self._render, context=self._context)
        except RuntimeError:
            pass  # the App's loop has closed; there is nothing left to render

    def _render(self) -> None:
        if self._disposed or not self._table.is_attached:
            return
        entries = [(self._key(item), tuple(self._cells(item))) for item in self._rows()]
        with self._bridge_changes():
            if entries != self._rendered:
                self._table.clear()
                for row_key, row_cells in entries:
                    self._table.add_row(*row_cells, key=row_key)
                self._rendered = entries
            self._restore_cursor()

    def _restore_cursor(self) -> None:
        selected = self._selected_key()
        keys = [row_key for row_key, _ in self._rendered or []]
        if selected in keys:
            row = keys.index(selected)
            if self._table.cursor_row != row:
                self._table.move_cursor(row=row, animate=False)

    # ── Disposal ──────────────────────────────────────────────────────────

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._subscription.dispose()
        hooks = vars(self._table)
        for name in ("watch_cursor_coordinate", "post_message"):
            hooks.pop(name, None)
