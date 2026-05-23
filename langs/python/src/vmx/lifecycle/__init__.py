"""VMx lifecycle module.

Public re-exports:

- :class:`ConstructionStatus` — five-state IntEnum
- :class:`StatusTransitionError` — raised when an operation is forbidden
- :func:`is_legal` — predicate; does not raise
- :func:`require` — raises :exc:`StatusTransitionError` if illegal
- :func:`final_state` — returns the post-operation :class:`ConstructionStatus`
"""

from __future__ import annotations

from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import final_state, is_legal, require

__all__ = [
    "ConstructionStatus",
    "StatusTransitionError",
    "final_state",
    "is_legal",
    "require",
]
