"""property_value_changed_messages_for — value-returning observable over PropertyChangedMessage.

Convenience helper over the message hub. Instead of filtering the full message stream and
extracting the sender attribute manually, this function returns ``Observable[Any]`` that emits
the *current value* of the named property on the sender each time a matching
``PropertyChangedMessage`` arrives.

This helper is informative-only (ADR-0032); the underlying ``messages`` stream on the hub
is the conformance-tested contract.
"""

from __future__ import annotations

from typing import Any

from reactivex import Observable
from reactivex import operators as ops

from vmx.messages.property_changed import PropertyChangedMessage


def property_value_changed_messages_for(
    hub: Any,
    source: Any,
    property_name: str,
) -> Observable[Any]:
    """Return an observable that emits the current value of *property_name* on *source*.

    Each time a :class:`~vmx.messages.property_changed.PropertyChangedMessage` whose
    ``sender`` is ``source`` (identity check) and whose ``property_name`` matches
    *property_name* arrives on the hub, the helper reads ``getattr(source, property_name)``
    and emits it.

    Parameters
    ----------
    hub:
        Any object whose ``.messages`` attribute is an ``Observable[Message]``.
    source:
        The specific sender instance to watch.  Identity (``is``) check is used.
    property_name:
        Name of the property to observe (must be gettable via ``getattr``).

    Returns
    -------
    Observable[Any]
        Cold observable; each subscription attaches a new filter to ``hub.messages``.
    """

    def _is_matching(msg: Any) -> bool:
        return (
            isinstance(msg, PropertyChangedMessage)
            and msg.sender is source
            and msg.property_name == property_name
        )

    result: Observable[Any] = hub.messages.pipe(
        ops.filter(_is_matching),
        ops.map(lambda _: getattr(source, property_name)),
    )
    return result
