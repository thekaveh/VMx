"""Forwarding decorators for ComponentVM and CompositeVM.

These decorators delegate every member of the wrapped VM to the wrapped instance
by default. Subclasses override individual members to customise behaviour.

See spec/09-forwarding.md.
"""

from __future__ import annotations

from vmx.forwarding.component import ForwardingComponentVM
from vmx.forwarding.composite import ForwardingCompositeVM

__all__ = ["ForwardingComponentVM", "ForwardingCompositeVM"]
