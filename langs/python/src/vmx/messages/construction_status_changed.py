"""ConstructionStatusChangedMessage — emitted on every legal lifecycle transition.

See spec/03-messages.md §ConstructionStatusChangedMessage and spec/02-lifecycle.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from vmx.lifecycle.status import ConstructionStatus


@dataclass(frozen=True, slots=True)
class ConstructionStatusChangedMessage:
    """Immutable message emitted on every legal ConstructionStatus transition.

    Parameters
    ----------
    sender:
        Runtime sender instance (untyped — the VM that transitioned).
    sender_name:
        Human-readable sender identifier (typically ``sender.name``).
    status:
        The new :class:`~vmx.lifecycle.status.ConstructionStatus` after the transition.
    """

    sender: object
    sender_name: str
    status: ConstructionStatus

    @property
    def sender_object(self) -> object:
        """Return the sender object (satisfies Message protocol)."""
        return self.sender

    @classmethod
    def create(
        cls,
        sender: object,
        sender_name: str,
        status: ConstructionStatus,
    ) -> ConstructionStatusChangedMessage:
        """Factory method — equivalent to direct construction."""
        return cls(sender=sender, sender_name=sender_name, status=status)
