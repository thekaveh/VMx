"""VMx groups module.

Public re-exports:

- :class:`GroupVM` — ordered peer-child container viewmodel (no selection slot)
- :class:`CollectionChangedEvent` — collection-change notification payload
- :class:`GroupVMBuilder` — immutable fluent builder for GroupVM
"""

from __future__ import annotations

from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import CollectionChangedEvent, GroupVM

__all__ = [
    "CollectionChangedEvent",
    "GroupVM",
    "GroupVMBuilder",
]
