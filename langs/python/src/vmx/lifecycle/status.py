"""ConstructionStatus — the five states of a VMx viewmodel's lifecycle.

See spec/02-lifecycle.md for the full state-machine contract.
"""

from __future__ import annotations

from enum import IntEnum


class ConstructionStatus(IntEnum):
    """Five-state lifecycle enum.

    Values match the C# counterpart exactly so that JSON fixtures and
    wire serialisation round-trip cleanly across language boundaries.
    """

    #: Terminal state.  Once entered, cannot leave.
    DISPOSED = 0

    #: Transient state during destruct().
    DESTRUCTING = 1

    #: Initial state of a freshly built VM.
    DESTRUCTED = 2

    #: Transient state during construct().
    CONSTRUCTING = 3

    #: Ready-to-use state.
    CONSTRUCTED = 4
