"""NotificationsView — overlay strip mirroring :class:`NotificationsVM.visible`.

Each :class:`NotificationVM` is rendered as a single ``Static`` row inside a
docked container. The Phase 4.b ``bind_collection`` bridge expects a writable
``current`` slot on the underlying collection, which the bounded mirror
provides indirectly via the ``ObservableList`` API; here we bypass that
helper and subscribe through a tiny rebuild closure routed through the
adapter — the widget class therefore touches no observables directly.

Subscription hygiene (audit round 2 Imp-5): the hub subscription returned
by ``bind_property`` is collected into a ``CompositeDisposable`` and
disposed in ``on_unmount`` so it doesn't outlive the widget.
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from notes_showcase.viewmodels.notifications_vm import NotificationsVM
from notes_showcase.views.adapter import bind_property


def _wire_bindings(view: "NotificationsView") -> CompositeDisposable:
    # ``visible`` is an ObservableList; the bounded mirror publishes a
    # PropertyChangedMessage on every sync (see NotificationsVM._sync_*),
    # so a vanilla bind_property re-reads the collection and renders a
    # compact summary string. Full rich rendering is a Phase 7 polish item.
    return CompositeDisposable(
        bind_property(
            view.query_one("#notifications_render", Static),
            "renderable",
            view._vm,
            "visible",
        ),
    )


class NotificationsView(Vertical):
    """Stack of active notification rows (toast-style overlay)."""

    def __init__(self, vm: NotificationsVM) -> None:
        super().__init__(id="notifications")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        yield Static("", id="notifications_render", classes="notification")

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_unmount(self) -> None:
        self._disposables.dispose()
