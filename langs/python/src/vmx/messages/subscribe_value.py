"""Imperative selected-state bridge over a fixed VM's message hub."""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from reactivex.abc import DisposableBase

from vmx.messages.property_changed import PropertyChangedMessage

if TYPE_CHECKING:
    from vmx.components.protocols import ComponentVMProto

TSource = TypeVar("TSource", bound="ComponentVMProto")
TValue = TypeVar("TValue")


def subscribe_value(
    source: TSource,
    selector: Callable[[TSource], TValue],
    callback: Callable[[TValue, TValue], None],
    *,
    equality: Callable[[TValue, TValue], bool] | None = None,
    fire_immediately: bool = False,
) -> DisposableBase:
    """Subscribe an imperative callback to selected state from one fixed VM."""
    current = selector(source)
    if fire_immediately:
        callback(current, current)
    equality_fn: Callable[[TValue, TValue], bool] = equality or operator.eq

    def on_message(message: object) -> None:
        nonlocal current
        if not isinstance(message, PropertyChangedMessage) or message.sender is not source:
            return
        next_value = selector(source)
        if equality_fn(current, next_value):
            return
        previous = current
        current = next_value
        callback(next_value, previous)

    return source.hub.messages.subscribe(on_message)
