"""VMx composites module.

Public re-exports:

- :class:`CompositeVMProto` — Protocol for CompositeVM<VM>
- :class:`CompositeVMOfProto` — Protocol marker for CompositeVMOf<M, VM>
- :class:`CompositeVM` — non-modeled composite VM
- :class:`CompositeVMOf` — modeled composite VM
- :class:`CompositeVMBuilder` — builder for CompositeVM
- :class:`CompositeVMOfBuilder` — builder for CompositeVMOf
- :class:`CollectionChangedEvent` — event payload for collection mutations
"""

from __future__ import annotations

from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CollectionChangedEvent, CompositeVM, CompositeVMOf
from vmx.composites.protocols import CompositeVMOfProto, CompositeVMProto

__all__ = [
    "CollectionChangedEvent",
    "CompositeVM",
    "CompositeVMBuilder",
    "CompositeVMOf",
    "CompositeVMOfBuilder",
    "CompositeVMOfProto",
    "CompositeVMProto",
]
