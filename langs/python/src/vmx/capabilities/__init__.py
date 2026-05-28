"""VMx capability micro-interfaces.

Opt-in contracts that describe what a VM can do. See spec/14-capabilities.md
and ADR-0010. None of these are implemented by default by any core VM type;
implementers explicitly inherit.

Lifecycle capabilities (IConstructable, IDestructable, IReconstructable) are
the sole exception: per spec rule 2, they are baseline and trivially satisfied
by every VM.
"""

from __future__ import annotations

from vmx.capabilities.crud import IDeletable, INewCreatable, ISavable, IUpdatable
from vmx.capabilities.current_crud import ICurrentDeletable, ICurrentUpdatable
from vmx.capabilities.dialog import IApprovable, ICancelable, IClosable
from vmx.capabilities.expandable_state import ExpandableState
from vmx.capabilities.expansion import ICollapsible, IExpandable, IExpansionTogglable
from vmx.capabilities.filter import Filterable
from vmx.capabilities.lifecycle_capabilities import (
    IConstructable,
    IDestructable,
    IReconstructable,
)
from vmx.capabilities.management import IManagable
from vmx.capabilities.search import ISearchable
from vmx.capabilities.searchable_state import SearchableState
from vmx.capabilities.selection import IDeselectable, ISelectable, ISelectionTogglable

__all__ = [
    "ExpandableState",
    "Filterable",
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
    "IManagable",
    "INewCreatable",
    "IReconstructable",
    "ISavable",
    "ISearchable",
    "ISelectable",
    "ISelectionTogglable",
    "IUpdatable",
    "SearchableState",
]
