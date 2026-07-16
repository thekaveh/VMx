"""ActionVM — pure record for one capability-derived action.

Used by :class:`~notes_showcase.viewmodels.capability_actions_vm.CapabilityActionsVM`
to project a focused VM's capability surface into a flat list of
``(label, command)`` tuples bound by the view.
"""

from __future__ import annotations

from dataclasses import dataclass

from vmx.commands.protocols import Command


@dataclass(frozen=True, slots=True)
class ActionVM:
    """Pair of a human-readable label and the command it invokes.

    ``command`` is typed as the :class:`~vmx.commands.protocols.Command`
    protocol so the action-bar can reuse decorated commands such as
    :class:`~vmx.commands.ConfirmationDecoratorCommand` (e.g. the wrapped
    ``NoteVM.delete_command``) — shared delete-command behavior.
    """

    label: str
    command: Command
