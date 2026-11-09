"""Services — message hub and dispatcher.

Public API re-exports:
- ``MessageHubProto`` — structural Protocol for hot pub/sub hub
- ``MessageHub``      — concrete Subject-backed implementation
- ``Dispatcher``      — structural Protocol for fg/bg scheduler pair
- ``RxDispatcher``    — concrete Rx-backed dispatcher
- ``DelayedTask``     — at most one delayed action on a scheduler
"""

from vmx.services.delayed_task import DelayedTask
from vmx.services.dispatcher import Dispatcher, RxDispatcher
from vmx.services.message_hub import MessageHub, MessageHubProto, TransactionalMessageHubProto
from vmx.services.null_dispatcher import NULL_DISPATCHER, NullDispatcher
from vmx.services.null_message_hub import (
    NULL_MESSAGE_HUB,
    NullMessageHub,
    null_message_hub_of,
)

__all__ = [
    "NULL_DISPATCHER",
    "NULL_MESSAGE_HUB",
    "DelayedTask",
    "Dispatcher",
    "MessageHub",
    "MessageHubProto",
    "NullDispatcher",
    "NullMessageHub",
    "RxDispatcher",
    "TransactionalMessageHubProto",
    "null_message_hub_of",
]
