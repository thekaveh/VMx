"""vmx.aggregates — fixed-arity heterogeneous component VM tuples.

Exports AggregateVM1 through AggregateVM6 and their corresponding builders.

Builder naming
--------------
The builder names are ``AggregateVM1Builder`` through ``AggregateVM6Builder``
(matching the TypeScript flavor and the C# nested
``AggregateVM2.AggregateVM2Builder`` shape). The legacy v1.0.0
``AggregateVMBuilder1`` through ``AggregateVMBuilder6`` identity aliases were
removed in vmx v3.0.0 (ADR-0052; deferral originally recorded in ADR-0009).

See spec/08-aggregate-vm.md and ADR-0007 (arity 6 added per ADR-0034).
"""

from __future__ import annotations

from vmx.aggregates.aggregate_vm import (
    AggregateVM1,
    AggregateVM2,
    AggregateVM3,
    AggregateVM4,
    AggregateVM5,
    AggregateVM6,
)
from vmx.aggregates.builders import (
    AggregateVM1Builder,
    AggregateVM2Builder,
    AggregateVM3Builder,
    AggregateVM4Builder,
    AggregateVM5Builder,
    AggregateVM6Builder,
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
    "AggregateVM6",
    "AggregateVM6Builder",
]
