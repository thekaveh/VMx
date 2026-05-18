"""Service protocols (message hub, dispatcher).

Concrete implementations arrive in Phase 3. Currently only the MessageHub Protocol
is exposed, moved from the legacy stub.
"""

from vmx.services.message_hub import MessageHub

__all__ = ["MessageHub"]
