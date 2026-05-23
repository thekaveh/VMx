"""VMx — hierarchical, lifecycle-aware MVVM viewmodel framework (Python flavor).

Public API is organised by responsibility under sub-packages: ``vmx.lifecycle``,
``vmx.messages``, ``vmx.services``, ``vmx.commands``, ``vmx.components``,
``vmx.composites``, ``vmx.groups``, ``vmx.aggregates``, ``vmx.forwarding``,
``vmx.builders``, ``vmx.tree``. The most common types are re-exported here for
convenience.
"""

from vmx.__about__ import __min_spec_version__, __version__
from vmx.commands import RelayCommand
from vmx.components import ComponentVMOf, ReadonlyComponentVMOf
from vmx.composites import CompositeVM, CompositeVMOf
from vmx.groups import GroupVM
from vmx.lifecycle import ConstructionStatus, StatusTransitionError
from vmx.messages import (
    ConstructionStatusChangedMessage,
    Message,
    PropertyChangedMessage,
)
from vmx.services import MessageHub, RxDispatcher

__all__ = [
    "ComponentVMOf",
    "CompositeVM",
    "CompositeVMOf",
    "ConstructionStatus",
    "ConstructionStatusChangedMessage",
    "GroupVM",
    "Message",
    "MessageHub",
    "PropertyChangedMessage",
    "ReadonlyComponentVMOf",
    "RelayCommand",
    "RxDispatcher",
    "StatusTransitionError",
    "__min_spec_version__",
    "__version__",
]
