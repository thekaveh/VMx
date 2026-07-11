"""Hierarchical (recursive tree) ViewModels — chapter 18.

See spec/18-hierarchical-vm.md and ADR-0028.
"""

from __future__ import annotations

from vmx.hierarchical.builders import HierarchicalVMBuilder
from vmx.hierarchical.hierarchical_vm import (
    BatchAttachRejection,
    BatchAttachRejectionReason,
    BatchAttachResult,
    HierarchicalVM,
    MissingParentPolicy,
)

__all__ = [
    "BatchAttachRejection",
    "BatchAttachRejectionReason",
    "BatchAttachResult",
    "HierarchicalVM",
    "HierarchicalVMBuilder",
    "MissingParentPolicy",
]
