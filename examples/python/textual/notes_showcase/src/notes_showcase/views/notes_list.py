"""NotesListView — centre pane (search + filter + list of notes).

Bindings (Phase 4.b adapter primitives only):

* ``#search_input`` ↔ ``notes_view.search_term`` (two-way).
* ``#starred_filter`` ↔ ``notes_view.show_starred_only`` (two-way).
* ``ListView`` rows ← ``notes_view.visible_items`` (the paged + filtered
  view) via :func:`on_vm_property_change` — binding the raw ``inner`` list
  left search / starred-filter / paging without any visible effect
  (real-wiring audit, pass 5).
* ``ListView`` selection → ``notes_view.current`` via
  ``on_list_view_selected`` (drives the right-pane editor binding).
* Pagination buttons ↔ ``move_to_*_page_command`` via :func:`bind_command`.

Widget-class discipline: ``compose()`` + ``on_mount()`` + ``on_unmount()``
only; helper logic lives in module-level functions.

Subscription hygiene (audit round 2 Imp-5): every ``bind_*`` returns a
``Disposable`` that we collect into a ``CompositeDisposable`` and dispose
in ``on_unmount`` so subscriptions don't outlive the widget.
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, ListItem, ListView, Static

from notes_showcase.viewmodels.note_vm import NoteVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM
from notes_showcase.views.adapter import (
    bind_command,
    bind_derived_property,
    bind_property_two_way,
    on_vm_property_change,
)

# Every NotesViewVM signal that changes which rows are visible (or their
# labels): filter/search recomputes and page moves.
_ROW_SIGNALS = {"visible_items", "current_page_index", "page_count", "page_size"}


def _note_list_item(note_vm: NoteVM) -> ListItem:
    """Build one list row; the row remembers its VM for selection forwarding."""
    marker = "★ " if note_vm.starred else "  "
    item = ListItem(Label(f"{marker}{note_vm.title}"))
    item.note_vm = note_vm
    return item


def _rebuild_rows(view: "NotesListView") -> None:
    list_view = view.query_one("#notes_list", ListView)
    list_view.clear()
    for note_vm in view._vm.visible_items:
        list_view.append(_note_list_item(note_vm))


def _forward_selection(vm: NotesViewVM, event: ListView.Selected) -> None:
    note_vm = getattr(event.item, "note_vm", None)
    if note_vm is not None:
        vm.current = note_vm


def _wire_bindings(view: "NotesListView") -> CompositeDisposable:
    vm = view._vm
    return CompositeDisposable(
        bind_property_two_way(
            view.query_one("#search_input", Input), "value", vm, "search_term"
        ),
        bind_property_two_way(
            view.query_one("#starred_filter", Checkbox),
            "value",
            vm,
            "show_starred_only",
        ),
        on_vm_property_change(vm, _ROW_SIGNALS, lambda _name: _rebuild_rows(view)),
        bind_command(
            view.query_one("#page_first", Button), vm.move_to_first_page_command
        ),
        bind_command(
            view.query_one("#page_prev", Button), vm.move_to_previous_page_command
        ),
        bind_command(
            view.query_one("#page_next", Button), vm.move_to_next_page_command
        ),
        bind_command(
            view.query_one("#page_last", Button), vm.move_to_last_page_command
        ),
        # ``page_label`` is a DerivedProperty[str] → bind via the derived bridge.
        bind_derived_property(
            view.query_one("#page_label", Static), "renderable", vm.page_label
        ),
    )


class NotesListView(Vertical):
    """Centre pane: search input, starred filter, paged list, pagination row."""

    def __init__(self, vm: NotesViewVM) -> None:
        super().__init__(id="notes_pane")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        yield Static("Notes", classes="pane_title")
        yield Input(placeholder="Search notes…", id="search_input")
        yield Checkbox("Starred only", id="starred_filter")
        yield ListView(id="notes_list")
        yield Horizontal(
            Button("«", id="page_first"),
            Button("‹", id="page_prev"),
            Static("", id="page_label"),
            Button("›", id="page_next"),
            Button("»", id="page_last"),
            id="pagination_row",
        )

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        _forward_selection(self._vm, event)

    def on_unmount(self) -> None:
        self._disposables.dispose()
