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
    action:
        One of ``"add"``, ``"remove"``, ``"replace"``, ``"move"``, or
        ``"reset"``.
    new_items:
        Items added (or the replacement value on replace). Empty on remove/reset.
    old_items:
        Items removed (or the replaced value on replace). Empty on add/reset.
    index:
        Index of the change, or -1 for reset.
    old_index:
        Previous index of the item, or -1 when there is no old position.
    new_index:
        Current index of the item, or -1 when there is no new position.
    """

    sender: object
    action: str
    new_items: tuple[T, ...] = field(default_factory=tuple)
    old_items: tuple[T, ...] = field(default_factory=tuple)
    index: int = -1
    old_index: int = -1
    new_index: int = -1

    @property
    def sender_name(self) -> str:
        """Derived from the sender's runtime type name; no separate name field per spec §2.4."""
        return type(self.sender).__name__

    @property
    def sender_object(self) -> object:
        """Return the sender as an untyped object (satisfies Message protocol)."""
        return self.sender

    # ── Factories ────────────────────────────────────────────────────────────

    @classmethod
    def for_add(
        cls,
        sender: object,
        item: T,
        index: int,
    ) -> CollectionChangedMessage[T]:
        """Create an Add message."""
        return cls(
            sender=sender,
            action="add",
            new_items=(item,),
            old_items=(),
            index=index,
            old_index=-1,
            new_index=index,
        )

    @classmethod
    def for_remove(
        cls,
        sender: object,
        item: T,
        index: int,
    ) -> CollectionChangedMessage[T]:
        """Create a Remove message."""
        return cls(
            sender=sender,
            action="remove",
            new_items=(),
            old_items=(item,),
            index=index,
            old_index=index,
            new_index=-1,
        )

    @classmethod
    def for_replace(
        cls,
        sender: object,
        new_item: T,
        old_item: T,
        index: int,
    ) -> CollectionChangedMessage[T]:
        """Create a Replace message."""
        return cls(
            sender=sender,
            action="replace",
            new_items=(new_item,),
            old_items=(old_item,),
            index=index,
            old_index=index,
            new_index=index,
        )

    @classmethod
    def for_move(
        cls,
        sender: object,
        item: T,
        old_index: int,
        new_index: int,
    ) -> CollectionChangedMessage[T]:
        """Create a Move message."""
        return cls(
            sender=sender,
            action="move",
            new_items=(item,),
            old_items=(item,),
            index=new_index,
            old_index=old_index,
            new_index=new_index,
        )

    @classmethod
    def for_reset(
        cls,
        sender: object,
    ) -> CollectionChangedMessage[T]:
        """Create a Reset message."""
        return cls(
            sender=sender,
            action="reset",
            new_items=(),
            old_items=(),
            index=-1,
            old_index=-1,
            new_index=-1,
        )
