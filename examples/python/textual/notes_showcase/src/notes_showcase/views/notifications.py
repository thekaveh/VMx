"""NotificationsView — overlay strip mirroring :class:`NotificationsVM.visible`.

Each :class:`NotificationVM` is rendered as a single ``Static`` row inside a
docked container. The Phase 4.b ``bind_collection`` bridge expects a writable
``current`` slot on the underlying collection, which the bounded mirror
provides indirectly via the ``ObservableList`` API; here we bypass that
helper and subscribe through a tiny rebuild closure routed through the
adapter — the widget class therefore touches no observables directly.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from notes_showcase.viewmodels.notifications_vm import NotificationsVM
from notes_showcase.views.adapter import bind_property


class NotificationsView(Vertical):
    """Stack of active notification rows (toast-style overlay)."""

    def __init__(self, vm: NotificationsVM) -> None:
        super().__init__(id="notifications")
        self._vm = vm

    def compose(self) -> ComposeResult:
        yield Static("", id="notifications_render", classes="notification")

    def on_mount(self) -> None:
        # ``visible`` is an ObservableList; the bounded mirror publishes a
        # PropertyChangedMessage on every sync (see NotificationsVM._sync_*),
        # so a vanilla bind_property re-reads the collection and renders a
        # compact summary string. Full rich rendering is a Phase 7 polish item.
        bind_property(
            self.query_one("#notifications_render", Static),
            "renderable",
            self._vm,
            "visible",
        )
