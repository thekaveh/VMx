"""VMx components module.

Public re-exports:

- :class:`ViewModelType` — role discriminator enum
- :class:`ComponentVMProto` — baseline VM Protocol
- :class:`ComponentVMOfProto` — modeled VM Protocol
- :class:`ReadonlyComponentVMOfProto` — readonly modeled VM Protocol
- :class:`ComponentVM` — non-modeled leaf VM
- :class:`ComponentVMOf` — modeled leaf VM (settable model)
- :class:`ReadonlyComponentVMOf` — readonly modeled leaf VM
- :class:`ComponentVMBuilder` — builder for ComponentVM
- :class:`ComponentVMOfBuilder` — builder for ComponentVMOf
- :class:`ReadonlyComponentVMOfBuilder` — builder for ReadonlyComponentVMOf
"""

from __future__ import annotations

from vmx.components.builders import (
    ComponentVMBuilder,
    ComponentVMOfBuilder,
    ReadonlyComponentVMOfBuilder,
)
from vmx.components.component_vm import ComponentVM, ComponentVMOf
from vmx.components.protocols import (
    ComponentVMOfProto,
    ComponentVMProto,
    ReadonlyComponentVMOfProto,
    ViewModelType,
)
from vmx.components.readonly_component_vm import ReadonlyComponentVMOf

__all__ = [
    "ComponentVM",
    "ComponentVMBuilder",
    "ComponentVMOf",
    "ComponentVMOfBuilder",
    "ComponentVMOfProto",
    "ComponentVMProto",
    "ReadonlyComponentVMOf",
    "ReadonlyComponentVMOfBuilder",
    "ReadonlyComponentVMOfProto",
    "ViewModelType",
]
