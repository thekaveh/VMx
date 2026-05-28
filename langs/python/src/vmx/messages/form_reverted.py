"""FormRevertedMessage — emitted when a FormVM reverts its Model to Snapshot.

See spec/20-form-vm.md §7 — Hub messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class FormRevertedMessage:
    """Immutable message published when a :class:`~vmx.forms.FormVM` reverts
    its model to the snapshot via ``deny_command``.

    Parameters
    ----------
    sender:
        The :class:`~vmx.forms.FormVM` instance that was reverted.
    sender_name:
        Human-readable type name of the sender (typically ``"FormVM"``).
    """

    sender: object
    sender_name: str

    @property
    def sender_object(self) -> object:
        """Return the sender as an untyped object (satisfies Message protocol)."""
        return self.sender
