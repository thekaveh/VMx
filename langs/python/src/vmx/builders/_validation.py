"""Shared builder field-validation helpers.

Private to the vmx.builders package — used by every concrete builder to centralize
the required-field checks invoked from .build().

The helpers return their input narrowed from ``T | None`` to ``T`` so that
callers can assign the result back and have both runtime safety AND mypy flow
narrowing without resorting to ``assert`` (which is stripped under ``python -O``).
"""

from __future__ import annotations

from typing import TypeVar

from vmx.builders.exceptions import BuilderValidationError

T = TypeVar("T")
H = TypeVar("H")
D = TypeVar("D")


def require_field(value: T | None, field_name: str) -> T:
    """Return ``value`` if non-None; otherwise raise BuilderValidationError."""
    if value is None:
        raise BuilderValidationError(field_name)
    return value


def require_services(hub: H | None, dispatcher: D | None) -> tuple[H, D]:
    """Validate ``.services(hub, dispatcher)`` was called; return the narrowed pair."""
    return require_field(hub, "hub"), require_field(dispatcher, "dispatcher")
