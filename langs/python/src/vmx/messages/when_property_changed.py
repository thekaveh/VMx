"""when_property_changed — typed observable of PropertyChangedMessage events.

Convenience helper over the message hub (VMX-017). Replaces the hand-wired
``hub.messages.pipe(ops.filter(lambda m: isinstance(m, PropertyChangedMessage)
and m.sender is x and m.property_name == "p"))`` filter that otherwise gets
copy-pasted into every cross-VM binding. Unlike
:func:`property_value_changed_messages_for` (which maps to the property *value*),
this emits the matching message — mirroring the C# ``IMessageHub.WhenPropertyChanged``
helper and the TS ``whenPropertyChanged``.

This helper is informative-only (ADR-0032); the underlying ``messages`` stream on
the hub is the conformance-tested contract.
"""

from __future__ import annotations

from typing import Any

from reactivex import Observable
from reactivex import operators as ops

from vmx.messages.property_changed import PropertyChangedMessage


def when_property_changed(
    hub: Any,
    sender: Any,
    property_name: str,
) -> Observable[PropertyChangedMessage[Any]]:
    """Return an observable of the matching :class:`PropertyChangedMessage` events.

    Each time a :class:`~vmx.messages.property_changed.PropertyChangedMessage`
    whose ``sender`` is ``sender`` (identity check) and whose ``property_name``
    matches *property_name* arrives on the hub, the helper emits that message.

    Parameters
    ----------
    hub:
        Any object whose ``.messages`` attribute is an ``Observable[Message]``.
    sender:
        The specific sender instance to watch. Identity (``is``) check is used.
    property_name:
        Name of the property to match.

    Returns
    -------
    Observable[PropertyChangedMessage[Any]]
        Cold observable; each subscription attaches a new filter to ``hub.messages``.
    """

    def _is_matching(msg: Any) -> bool:
        return (
            isinstance(msg, PropertyChangedMessage)
            and msg.sender is sender
            and msg.property_name == property_name
        )

    result: Observable[PropertyChangedMessage[Any]] = hub.messages.pipe(ops.filter(_is_matching))
    return result
