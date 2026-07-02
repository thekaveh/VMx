"""GlobalSearchView — token-paged search across all notes."""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static

from notes_showcase.viewmodels.global_search_vm import GlobalSearchVM
from notes_showcase.views.adapter import (
    bind_command,
    bind_property_two_way,
    on_vm_property_change,
)


def _results_text(vm: GlobalSearchVM) -> str:
    if not vm.results:
        return ""
    return "  |  ".join(
        f"{note.title} ({note.model.notebook_id})" for note in vm.results
    )


def _wire_bindings(view: "GlobalSearchView") -> CompositeDisposable:
    vm = view._vm
    results = view.query_one("#global_search_results", Static)
    results.update(_results_text(vm))
    return CompositeDisposable(
        bind_property_two_way(
            view.query_one("#global_search_input", Input),
            "value",
            vm,
            "search_term",
        ),
        bind_command(
            view.query_one("#global_search_refresh", Button), vm.refresh_command
        ),
        bind_command(
            view.query_one("#global_search_more", Button), vm.load_more_command
        ),
        on_vm_property_change(
            vm,
            {"results", "has_more"},
            lambda _name: results.update(_results_text(vm)),
        ),
    )


class GlobalSearchView(Vertical):
    """Compact search band with accumulated token-paged results."""

    def __init__(self, vm: GlobalSearchVM) -> None:
        super().__init__(id="global_search")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        yield Static("Global search", classes="pane_title")
        yield Horizontal(
            Input(placeholder="Search all notes…", id="global_search_input"),
            Button("Search", id="global_search_refresh"),
            Button("Load more", id="global_search_more"),
            id="global_search_controls",
        )
        yield Static("", id="global_search_results")

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "global_search_input":
            self._vm.search()

    def on_unmount(self) -> None:
        self._disposables.dispose()
