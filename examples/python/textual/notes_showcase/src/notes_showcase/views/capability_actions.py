"""CapabilityActionsView — bottom strip of focus-derived capability buttons.

The ``actions`` accessor on :class:`CapabilityActionsVM` is a
:class:`DerivedProperty[list[ActionVM]]` (one source: the focus subject).
The view re-renders the button row whenever the projection changes; the
subscription is routed through ``on_derived_change`` so the widget class
itself never imports :mod:`reactivex` (Phase 6 grep stays green).

Subscription hygiene (audit round 2 Imp-5): both the derived-change
subscription and every per-button ``bind_command`` Disposable are tracked
on the widget's ``_bindings`` CompositeDisposable and disposed in
``on_unmount`` so subscriptions don't outlive the widget.
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button

from notes_showcase.viewmodels.action_vm import ActionVM
from notes_showcase.viewmodels.capability_actions_vm import CapabilityActionsVM
from notes_showcase.views.adapter import bind_command, on_derived_change


def _rebuild_buttons(view: "CapabilityActionsView", actions: list[ActionVM]) -> None:
    """Dispose prior per-button command bindings, then mount fresh buttons.

    Each new ``bind_command`` Disposable is tracked on ``view._button_bindings``
    so the next rebuild (or ``on_unmount``) tears them all down.
    """
    view._button_bindings.dispose()
    view._button_bindings = CompositeDisposable()
    for child in list(view.children):
        child.remove()
    for action in actions:
        button = Button(
            action.label,
            id=f"action_{action.label.lower().replace(' ', '_')}",
        )
        view.mount(button)
        view._button_bindings.add(bind_command(button, action.command))


def _dispose_all(view: "CapabilityActionsView") -> None:
    """Tear down both the derived-change subscription and the latest
    generation of per-button command bindings.
    """
    view._disposables.dispose()
    view._button_bindings.dispose()


def _wire_bindings(view: "CapabilityActionsView") -> CompositeDisposable:
    """Subscribe to ``vm.actions`` and seed the first button render."""
    return CompositeDisposable(
        on_derived_change(
            view._vm.actions, lambda actions: _rebuild_buttons(view, actions)
        ),
    )


class CapabilityActionsView(Horizontal):
    """Action-bar strip that mirrors the focused VM's capabilities."""

    def __init__(self, vm: CapabilityActionsVM) -> None:
        super().__init__(id="capability_actions")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()
        self._button_bindings: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        # Buttons are mounted in on_mount via _render_actions; nothing yielded.
        return iter([])

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_unmount(self) -> None:
        _dispose_all(self)
