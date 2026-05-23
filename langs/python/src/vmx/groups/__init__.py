"""VMx groups module.

Public re-exports:

- :class:`GroupVM` — ordered peer-child container viewmodel (no selection slot)
- :class:`GroupVMBuilder` — immutable fluent builder for GroupVM

The shared :class:`vmx.collections.CollectionChangedEvent` payload is emitted
on ``GroupVM.on_collection_changed``.
"""

from __future__ import annotations

from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM

__all__ = [
    "GroupVM",
    "GroupVMBuilder",
]
