"""vmx.aggregates — fixed-arity heterogeneous component VM tuples.

Exports AggregateVM1 through AggregateVM5 and their corresponding builders.
See spec/08-aggregate-vm.md and ADR-0007.
"""

from __future__ import annotations

from vmx.aggregates.aggregate_vm import (
    AggregateVM1,
    AggregateVM2,
    AggregateVM3,
    AggregateVM4,
    AggregateVM5,
)
from vmx.aggregates.builders import (
    AggregateVMBuilder1,
    AggregateVMBuilder2,
    AggregateVMBuilder3,
    AggregateVMBuilder4,
    AggregateVMBuilder5,
)

__all__ = [
    "AggregateVM1",
    "AggregateVM2",
    "AggregateVM3",
    "AggregateVM4",
    "AggregateVM5",
    "AggregateVMBuilder1",
    "AggregateVMBuilder2",
    "AggregateVMBuilder3",
    "AggregateVMBuilder4",
    "AggregateVMBuilder5",
]
