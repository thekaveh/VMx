"""Internal: the hub message a VM collection publishes after each local event.

``CompositeVM`` and ``GroupVM`` follow every effective local
:class:`CollectionChangedEvent` with exactly one
:class:`~vmx.messages.collection_changed.CollectionChangedMessage` sent to
their own hub, with the container as sender and the same action, positions,
and items (spec ch. 01 §1.4, ch. 21 §2.4, ADR-0142).
"""

from __future__ import annotations

from vmx.collections.collection_changed import CollectionChangedEvent
from vmx.messages.collection_changed import CollectionChangedMessage


def collection_changed_message_for(
    sender: object, event: CollectionChangedEvent
) -> CollectionChangedMessage[object]:
    """Map one local container event to its hub message.

    ``index`` follows the :class:`CollectionChangedMessage` factories: the old
    position for a removal, the new position for an add or move, and ``-1``
    for a reset.
    """
    index = event.old_index if event.action == "remove" else event.new_index
    return CollectionChangedMessage(
        sender=sender,
        action=event.action,
        new_items=event.new_items,
        old_items=event.old_items,
        index=index,
        old_index=event.old_index,
        new_index=event.new_index,
    )
