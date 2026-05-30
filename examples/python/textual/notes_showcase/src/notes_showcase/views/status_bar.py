"""StatusBarView — footer-style strip with three Derived-driven slots.

Each slot is a ``Static`` whose ``renderable`` is bound to a
:class:`DerivedProperty[str]` exposed by :class:`StatusBarVM`. The bridge
subscribes directly to ``value_changed`` (Phase 5.b binding-gap #3 fix), so
status text updates as soon as the upstream VM emits.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from notes_showcase.viewmodels.status_bar_vm import StatusBarVM
from notes_showcase.views.adapter import bind_derived_property


class StatusBarView(Horizontal):
    """Three-slot status strip (note count / starred / editing)."""

    def __init__(self, vm: StatusBarVM) -> None:
        super().__init__(id="status_bar")
        self._vm = vm

    def compose(self) -> ComposeResult:
        yield Static("", id="status_note_count")
        yield Static(" · ")
        yield Static("", id="status_starred")
        yield Static(" · ")
        yield Static("", id="status_editing")

    def on_mount(self) -> None:
        bind_derived_property(
            self.query_one("#status_note_count", Static),
            "renderable",
            self._vm.note_count_text,
        )
        bind_derived_property(
            self.query_one("#status_starred", Static),
            "renderable",
            self._vm.starred_text,
        )
        bind_derived_property(
            self.query_one("#status_editing", Static),
            "renderable",
            self._vm.editing_text,
        )
