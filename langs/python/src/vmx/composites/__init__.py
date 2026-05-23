"""VMx composites module.

Public re-exports:

- :class:`CompositeVMProto` — Protocol for CompositeVM<VM>
- :class:`CompositeVMOfProto` — Protocol marker for CompositeVMOf<M, VM>
- :class:`CompositeVM` — non-modeled composite VM
- :class:`CompositeVMOf` — modeled composite VM
- :class:`CompositeVMBuilder` — builder for CompositeVM
- :class:`CompositeVMOfBuilder` — builder for CompositeVMOf

The shared :class:`vmx.collections.CollectionChangedEvent` payload is emitted
on ``CompositeVM.on_collection_changed``.
"""

from __future__ import annotations

from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM, CompositeVMOf
from vmx.composites.protocols import CompositeVMOfProto, CompositeVMProto

__all__ = [
    "CompositeVM",
    "CompositeVMBuilder",
    "CompositeVMOf",
    "CompositeVMOfBuilder",
    "CompositeVMOfProto",
    "CompositeVMProto",
]
