"""StatusBarView — footer-style strip with three Derived-driven slots.

Each slot is a ``Static`` whose ``renderable`` is bound to a
:class:`DerivedProperty[str]` exposed by :class:`StatusBarVM`. The bridge
subscribes directly to ``value_changed`` (Phase 5.b binding-gap #3 fix), so
status text updates as soon as the upstream VM emits.

Subscription hygiene (subscription ownership): every ``bind_*`` returns a
``Disposable`` that this widget collects into a ``CompositeDisposable`` and
disposes from ``on_unmount`` so subscriptions don't outlive the widget and
emit into a dead receiver.
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from notes_showcase.viewmodels.status_bar_vm import StatusBarVM
from notes_showcase.views.adapter import bind_derived_property


def _wire_bindings(view: "StatusBarView") -> CompositeDisposable:
    return CompositeDisposable(
        bind_derived_property(
            view.query_one("#status_note_count", Static),
            "renderable",
            view._vm.note_count_text,
        ),
        bind_derived_property(
            view.query_one("#status_starred", Static),
            "renderable",
            view._vm.starred_text,
        ),
        bind_derived_property(
            view.query_one("#status_editing", Static),
            "renderable",
            view._vm.editing_text,
        ),
    )


class StatusBarView(Horizontal):
    """Three-slot status strip (note count / starred / editing)."""

    def __init__(self, vm: StatusBarVM) -> None:
        super().__init__(id="status_bar")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        yield Static("", id="status_note_count")
        yield Static(" · ")
        yield Static("", id="status_starred")
        yield Static(" · ")
        yield Static("", id="status_editing")

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_unmount(self) -> None:
        self._disposables.dispose()
