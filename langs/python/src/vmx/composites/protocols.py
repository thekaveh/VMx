"""CompositeVM Protocols.

See spec/06-composite-vm.md §Members.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from vmx.collections.protocols import SelectableVmCollectionProto

VM_co = TypeVar("VM_co", covariant=True)
M_co = TypeVar("M_co", covariant=True)


@runtime_checkable
class CompositeVMProto(SelectableVmCollectionProto[VM_co], Protocol, Generic[VM_co]):
    """Protocol for CompositeVM<VM> (non-modeled).

    Extends ComponentVMProto with:
    - ``current`` property (with getter returning VM_co | None)
    - ``select_component`` / ``deselect_component`` / ``can_select_component``
    - the complete shared ``VmCollectionProto`` surface

    Note: Because ``VM_co`` is covariant, the ``current`` setter and the
    vm-typed selection methods use ``Any``/``object`` to satisfy the Protocol
    variance rules. Concrete implementations enforce the correct types.
    """

    pass


@runtime_checkable
class CompositeVMOfProto(CompositeVMProto[VM_co], Protocol, Generic[M_co, VM_co]):
    """Marker Protocol for CompositeVMOf<M, VM> (modeled composite).

    No additional members beyond CompositeVMProto — the model type parameter
    is a compile-time constraint only.
    """
