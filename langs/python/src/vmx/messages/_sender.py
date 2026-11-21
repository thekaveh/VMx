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
    report a false identity. Such an object is its own identity. Each helper calls
    this once, when it subscribes.
    """
    if issubclass(type(sender), _ComponentVMBase):
        return sender._ownership_identity
    return sender
