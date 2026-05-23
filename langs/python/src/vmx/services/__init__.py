"""Services — message hub and dispatcher.

Public API re-exports:
- ``MessageHubProto`` — structural Protocol for hot pub/sub hub
- ``MessageHub``      — concrete Subject-backed implementation
- ``Dispatcher``      — structural Protocol for fg/bg scheduler pair
- ``RxDispatcher``    — concrete Rx-backed dispatcher
"""

from vmx.services.dispatcher import Dispatcher, RxDispatcher
from vmx.services.message_hub import MessageHub, MessageHubProto

__all__ = [
    "Dispatcher",
    "MessageHub",
    "MessageHubProto",
    "RxDispatcher",
]
