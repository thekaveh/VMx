"""Shared builder field-validation helpers.

Private to the vmx.builders package — used by every concrete builder to centralize
the required-field checks invoked from .build().
"""

from __future__ import annotations

from typing import Any

from vmx.builders.exceptions import BuilderValidationError


def require_field(value: Any, field_name: str) -> None:
    """Raise BuilderValidationError(field_name) if `value` is None."""
    if value is None:
        raise BuilderValidationError(field_name)


def require_services(hub: Any, dispatcher: Any) -> None:
    """Validate that .services(hub, dispatcher) was called on the builder."""
    require_field(hub, "hub")
    require_field(dispatcher, "dispatcher")
