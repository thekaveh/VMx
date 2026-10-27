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
    *property_names: str,
) -> Observable[PropertyChangedMessage[Any]]:
    """Return an observable of the matching :class:`PropertyChangedMessage` events.

    Each time a :class:`~vmx.messages.property_changed.PropertyChangedMessage`
    whose ``sender`` is ``sender`` (identity check) and whose ``property_name``
    matches *property_name* arrives on the hub, the helper emits that message.

    Pass more names to watch several properties of one sender (spec/03 §7.2,
    ADR-0160): ``when_property_changed(hub, chart, "plot", "range")``, or
    ``when_property_changed(hub, chart, *names)`` for a sequence. A message
    matches when its ``property_name`` equals any of the names. Each matching
    message is emitted once, in hub order, even when its name is passed more
    than once. At least one name is required: a call with none raises
    :class:`TypeError`. The single-name form is unchanged.

    Parameters
    ----------
    hub:
        Any object whose ``.messages`` attribute is an ``Observable[Message]``.
    sender:
        The specific sender instance to watch. Identity (``is``) check is used.
    property_name:
        Name of the property to match.
    *property_names:
        Further property names to match.

    Returns
    -------
    Observable[PropertyChangedMessage[Any]]
        Cold observable; each subscription attaches one filter to ``hub.messages``.
    """
    names = (property_name, *property_names)

    def _is_matching(msg: Any) -> bool:
        return (
            isinstance(msg, PropertyChangedMessage)
            and msg.sender is sender
            and msg.property_name in names
        )

    result: Observable[PropertyChangedMessage[Any]] = hub.messages.pipe(ops.filter(_is_matching))
    return result
