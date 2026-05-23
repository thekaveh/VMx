"""StatusTransitionError — raised when a lifecycle operation is forbidden.

See spec/02-lifecycle.md §Invariants 3 and 5.
"""

from __future__ import annotations

from vmx.lifecycle.status import ConstructionStatus


class StatusTransitionError(RuntimeError):
    """Raised when a lifecycle operation is invoked from a state that forbids it.

    Attributes
    ----------
    current_status:
        The ``ConstructionStatus`` the VM was in when the operation was attempted.
    attempted_operation:
        The name of the operation that was attempted (e.g. ``"construct"``).
    """

    def __init__(self, current_status: ConstructionStatus, attempted_operation: str) -> None:
        super().__init__(
            f"Cannot {attempted_operation} from state {current_status.name.capitalize()}."
        )
        self.current_status: ConstructionStatus = current_status
        self.attempted_operation: str = attempted_operation
