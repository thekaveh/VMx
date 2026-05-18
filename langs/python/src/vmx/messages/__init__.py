"""Message protocols and concrete messages.

Concrete message types arrive in Phase 3; this module currently only re-exports the
Protocols moved over from the legacy stub.
"""

from vmx.messages.protocols import Message, TypedMessage

__all__ = ["Message", "TypedMessage"]
