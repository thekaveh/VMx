"""Canonical sender identity for the chapter 03 §7 hub subscription helpers.

A sender-filter helper keeps the messages whose sender is the VM it was given.
A forwarding decorator sends no message of its own: the wrapped VM is the sender
of each message the decorator causes (ADR-0221), and nested decorators resolve to
the same innermost VM (ADR-0124). The helpers therefore compare against this
identity, not against the object they were given (spec/03-messages.md §7, ADR-0233).
"""

from __future__ import annotations

from typing import Any

from vmx.components.base import _ComponentVMBase


def canonical_sender(sender: Any) -> Any:
    """Return the canonical ownership identity of *sender*.

    Only a VMx component (a :class:`_ComponentVMBase` subclass, which includes the
    forwarding decorators) can have an identity other than itself. The check reads
    the object's type, not its attributes: a ``unittest.mock`` object, or any other
    duck-typed object, synthesizes every attribute, so an attribute lookup would
    report a false identity. Such an object is its own identity. A forwarding
    decorator resolves through its wrapped component, which may be an object that
    is not a VM (spec/09-forwarding.md §1); that object is then the identity. Each
    helper calls this once, when it subscribes.
    """
    # Imported here: vmx.forwarding imports vmx.components.protocols, which loads
    # the messages package that imports this module, so a top-level import cycles.
    from vmx.forwarding._membership import _ForwardingMembership

    if not issubclass(type(sender), _ComponentVMBase):
        return sender
    if issubclass(type(sender), _ForwardingMembership):
        return canonical_sender(sender._wrapped_component)
    return sender._ownership_identity
