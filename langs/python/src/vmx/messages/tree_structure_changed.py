"""TreeStructureChangedMessage (ADR-0028, chapter 18).

Published on the message hub when a HierarchicalVM subtree changes
structurally (add / remove / reparent of a child node).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TreeStructureChange(Enum):
    """Discriminated enum for the structural mutation that occurred."""

    ADDED = "added"
    REMOVED = "removed"
    REPARENTED = "reparented"


@dataclass(frozen=True, slots=True)
class TreeStructureChangedMessage:
    """Immutable message emitted on structural mutations in a HierarchicalVM subtree.

    Parameters
    ----------
    sender:
        The node whose ``children`` collection changed.
    sender_name:
        Human-readable identifier for ``sender``.
    change:
        The kind of structural mutation (ADDED / REMOVED / REPARENTED).
    affected:
        The node that was added, removed, or reparented.
    index:
        Position in ``children`` at which the change occurred.
        ``-1`` when not applicable (e.g. REPARENTED).
    """

    sender: Any
    sender_name: str
    change: TreeStructureChange
    affected: Any
    index: int

    @property
    def sender_object(self) -> object:
        """Return the sender as an untyped object (satisfies Message protocol)."""
        return self.sender

    @classmethod
    def create(
        cls,
        sender: Any,
        sender_name: str,
        change: TreeStructureChange,
        affected: Any,
        index: int,
    ) -> TreeStructureChangedMessage:
        """Factory method — equivalent to direct construction."""
        return cls(
            sender=sender,
            sender_name=sender_name,
            change=change,
            affected=affected,
            index=index,
        )
