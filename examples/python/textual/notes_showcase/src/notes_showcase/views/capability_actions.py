"""CapabilityActionsView — bottom strip of focus-derived capability buttons.

The ``actions`` accessor on :class:`CapabilityActionsVM` is a
:class:`DerivedProperty[list[ActionVM]]` (one source: the focus subject).
The view re-renders the button row whenever the projection changes; the
subscription is routed through ``on_derived_change`` so the widget class
itself never imports :mod:`reactivex` (Phase 6 grep stays green).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button

from notes_showcase.viewmodels.action_vm import ActionVM
from notes_showcase.viewmodels.capability_actions_vm import CapabilityActionsVM
from notes_showcase.views.adapter import bind_command, on_derived_change


def _render_actions(host: Horizontal, actions: list[ActionVM]) -> None:
    for child in list(host.children):
        child.remove()
    for action in actions:
        button = Button(
            action.label,
            id=f"action_{action.label.lower().replace(' ', '_')}",
        )
        host.mount(button)
        bind_command(button, action.command)


class CapabilityActionsView(Horizontal):
    """Action-bar strip that mirrors the focused VM's capabilities."""

    def __init__(self, vm: CapabilityActionsVM) -> None:
        super().__init__(id="capability_actions")
        self._vm = vm

    def compose(self) -> ComposeResult:
        # Buttons are mounted in on_mount via _render_actions; nothing yielded.
        return iter([])

    def on_mount(self) -> None:
        on_derived_change(
            self._vm.actions, lambda actions: _render_actions(self, actions)
        )
