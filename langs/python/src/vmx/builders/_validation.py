"""Shared builder field-validation helpers.

Private to the vmx.builders package — used by every concrete builder to centralize
the required-field checks invoked from .build().

These helpers are pure null-checks; the parameter type is intentionally ``object``
(rather than a Hub/Dispatcher Protocol) so they can be reused unchanged across every
builder regardless of the field's declared type, including fields whose declared
type already excludes ``None`` at the type-checker level.
"""

from __future__ import annotations

from vmx.builders.exceptions import BuilderValidationError


def require_field(value: object | None, field_name: str) -> None:
    """Raise BuilderValidationError(field_name) if `value` is None."""
    if value is None:
        raise BuilderValidationError(field_name)


def require_services(hub: object | None, dispatcher: object | None) -> None:
    """Validate that .services(hub, dispatcher) was called on the builder."""
    require_field(hub, "hub")
    require_field(dispatcher, "dispatcher")
