"""vmx.aggregates — fixed-arity heterogeneous component VM tuples.

Exports AggregateVM1 through AggregateVM5 and their corresponding builders.

Builder naming
--------------
The canonical builder names from v1.2.0 are ``AggregateVM1Builder`` through
``AggregateVM5Builder`` (matching the TypeScript flavor). The historical
``AggregateVMBuilder1`` through ``AggregateVMBuilder5`` names remain as identity
aliases for backward compatibility and will be removed in vmx v2.0.0.

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
    AggregateVM1Builder,
    AggregateVM2Builder,
    AggregateVM3Builder,
    AggregateVM4Builder,
    AggregateVM5Builder,
    AggregateVMBuilder1,
    AggregateVMBuilder2,
    AggregateVMBuilder3,
    AggregateVMBuilder4,
    AggregateVMBuilder5,
)

__all__ = [
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
]
