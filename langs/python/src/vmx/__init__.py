"""VMx — hierarchical, lifecycle-aware MVVM viewmodel framework (Python flavor).

Public API is organised by responsibility under sub-packages: ``vmx.lifecycle``,
``vmx.messages``, ``vmx.services``, ``vmx.commands``, ``vmx.components``,
``vmx.composites``, ``vmx.groups``, ``vmx.aggregates``, ``vmx.forwarding``,
``vmx.builders``, ``vmx.tree``, ``vmx.collections``. The full set of public
types is re-exported here so ``from vmx import ...`` reaches every primitive.
"""

from vmx.__about__ import __min_spec_version__, __version__
from vmx.aggregates import (
    AggregateVM1,
    AggregateVM1Builder,
    AggregateVM2,
    AggregateVM2Builder,
    AggregateVM3,
    AggregateVM3Builder,
    AggregateVM4,
    AggregateVM4Builder,
    AggregateVM5,
    AggregateVM5Builder,
    AggregateVMBuilder1,
    AggregateVMBuilder2,
    AggregateVMBuilder3,
    AggregateVMBuilder4,
    AggregateVMBuilder5,
)
from vmx.builders import BuilderValidationError
from vmx.capabilities import (
    ExpandableState,
    IApprovable,
    ICancelable,
    IClosable,
    ICollapsible,
    IConstructable,
    ICurrentDeletable,
    ICurrentUpdatable,
    IDeletable,
    IDeselectable,
    IDestructable,
    IExpandable,
    IExpansionTogglable,
    IManagable,
    INewCreatable,
    IReconstructable,
    ISavable,
    ISearchable,
    ISelectable,
    ISelectionTogglable,
    IUpdatable,
    SearchableState,
)
from vmx.collections import BatchUpdateHandle, CollectionChangedEvent
from vmx.commands import (
    Command,
    CompositeCommand,
    ConfirmationDecoratorCommand,
    DecoratorCommand,
    ModeledCrudCommands,
    ParameterizedCommand,
    RelayCommand,
    RelayCommandBuilder,
    RelayCommandOf,
    RelayCommandOfBuilder,
    RelayCommandOfT,
)
from vmx.components import (
    ComponentVM,
    ComponentVMBuilder,
    ComponentVMOf,
    ComponentVMOfBuilder,
    ReadonlyComponentVMOf,
    ReadonlyComponentVMOfBuilder,
    ViewModelType,
)
from vmx.composites import (
    CompositeVM,
    CompositeVMBuilder,
    CompositeVMOf,
    CompositeVMOfBuilder,
)
from vmx.forwarding import ForwardingComponentVM, ForwardingCompositeVM
from vmx.groups import GroupVM, GroupVMBuilder
from vmx.lifecycle import ConstructionStatus, StatusTransitionError
from vmx.localization import NULL_LOCALIZER, ILocalizer, NullLocalizer
from vmx.messages import (
    ConstructionStatusChangedMessage,
    Message,
    PropertyChangedMessage,
)
from vmx.properties import DerivedProperty, from_sources
from vmx.services import (
    NULL_DISPATCHER,
    NULL_MESSAGE_HUB,
    MessageHub,
    NullDispatcher,
    NullMessageHub,
    RxDispatcher,
)
from vmx.tree import find, walk, walk_expanded

__all__ = [
    "NULL_DISPATCHER",
    "NULL_LOCALIZER",
    "NULL_MESSAGE_HUB",
    "AggregateVM1",
    "AggregateVM1Builder",
    "AggregateVM2",
    "AggregateVM2Builder",
    "AggregateVM3",
    "AggregateVM3Builder",
    "AggregateVM4",
    "AggregateVM4Builder",
    "AggregateVM5",
    "AggregateVM5Builder",
    "AggregateVMBuilder1",
    "AggregateVMBuilder2",
    "AggregateVMBuilder3",
    "AggregateVMBuilder4",
    "AggregateVMBuilder5",
    "BatchUpdateHandle",
    "BuilderValidationError",
    "CollectionChangedEvent",
    "Command",
    "ComponentVM",
    "ComponentVMBuilder",
    "ComponentVMOf",
    "ComponentVMOfBuilder",
    "CompositeCommand",
    "CompositeVM",
    "CompositeVMBuilder",
    "CompositeVMOf",
    "CompositeVMOfBuilder",
    "ConfirmationDecoratorCommand",
    "ConstructionStatus",
    "ConstructionStatusChangedMessage",
    "DecoratorCommand",
    "DerivedProperty",
    "ExpandableState",
    "ForwardingComponentVM",
    "ForwardingCompositeVM",
    "GroupVM",
    "GroupVMBuilder",
    "IApprovable",
    "ICancelable",
    "IClosable",
    "ICollapsible",
    "IConstructable",
    "ICurrentDeletable",
    "ICurrentUpdatable",
    "IDeletable",
    "IDeselectable",
    "IDestructable",
    "IExpandable",
    "IExpansionTogglable",
    "ILocalizer",
    "IManagable",
    "INewCreatable",
    "IReconstructable",
    "ISavable",
    "ISearchable",
    "ISelectable",
    "ISelectionTogglable",
    "IUpdatable",
    "Message",
    "MessageHub",
    "ModeledCrudCommands",
    "NullDispatcher",
    "NullLocalizer",
    "NullMessageHub",
    "ParameterizedCommand",
    "PropertyChangedMessage",
    "ReadonlyComponentVMOf",
    "ReadonlyComponentVMOfBuilder",
    "RelayCommand",
    "RelayCommandBuilder",
    "RelayCommandOf",
    "RelayCommandOfBuilder",
    "RelayCommandOfT",
    "RxDispatcher",
    "SearchableState",
    "StatusTransitionError",
    "ViewModelType",
    "__min_spec_version__",
    "__version__",
    "find",
    "from_sources",
    "walk",
    "walk_expanded",
]

# Lifecycle capabilities are baseline: every core VM trivially satisfies them.
# See spec/14-capabilities.md rule 2 and CAP-020.
IConstructable.register(ComponentVM)
IConstructable.register(ComponentVMOf)
IConstructable.register(ReadonlyComponentVMOf)
IDestructable.register(ComponentVM)
IDestructable.register(ComponentVMOf)
IDestructable.register(ReadonlyComponentVMOf)
IReconstructable.register(ComponentVM)
IReconstructable.register(ComponentVMOf)
IReconstructable.register(ReadonlyComponentVMOf)
