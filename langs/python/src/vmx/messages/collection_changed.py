"""CollectionChangedMessage — emitted when a ServicedObservableCollection mutates.

See spec/21-collections.md §2 and ADR-0024.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CollectionChangedMessage(Generic[T]):
    """Immutable message published to the hub on collection mutations.

    Parameters
    ----------
    sender:
        The collection that changed.
    sender_name:
        Human-readable sender identifier.
    action:
        One of ``"add"``, ``"remove"``, ``"replace"``, or ``"reset"``.
    new_items:
        Items added (or the replacement value on replace). Empty on remove/reset.
    old_items:
        Items removed (or the replaced value on replace). Empty on add/reset.
    index:
        Index of the change, or -1 for reset.
    """

    sender: object
    sender_name: str
    action: str
    new_items: tuple[T, ...] = field(default_factory=tuple)
    old_items: tuple[T, ...] = field(default_factory=tuple)
    index: int = -1

    @property
    def sender_object(self) -> object:
        """Return the sender as an untyped object (satisfies Message protocol)."""
        return self.sender

    # ── Factories ────────────────────────────────────────────────────────────

    @classmethod
    def for_add(
        cls,
        sender: object,
        sender_name: str,
        item: T,
        index: int,
    ) -> CollectionChangedMessage[T]:
        """Create an Add message."""
        return cls(
            sender=sender,
            sender_name=sender_name,
            action="add",
            new_items=(item,),
            old_items=(),
            index=index,
        )

    @classmethod
    def for_remove(
        cls,
        sender: object,
        sender_name: str,
        item: T,
        index: int,
    ) -> CollectionChangedMessage[T]:
        """Create a Remove message."""
        return cls(
            sender=sender,
            sender_name=sender_name,
            action="remove",
            new_items=(),
            old_items=(item,),
            index=index,
        )

    @classmethod
    def for_replace(
        cls,
        sender: object,
        sender_name: str,
        new_item: T,
        old_item: T,
        index: int,
    ) -> CollectionChangedMessage[T]:
        """Create a Replace message."""
        return cls(
            sender=sender,
            sender_name=sender_name,
            action="replace",
            new_items=(new_item,),
            old_items=(old_item,),
            index=index,
        )

    @classmethod
    def for_reset(
        cls,
        sender: object,
        sender_name: str,
    ) -> CollectionChangedMessage[T]:
        """Create a Reset message."""
        return cls(
            sender=sender,
            sender_name=sender_name,
            action="reset",
            new_items=(),
            old_items=(),
            index=-1,
        )
