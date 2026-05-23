"""VMx builders module.

Public re-exports:

- :class:`BuilderValidationError` — raised by Build() when a required field is missing
"""

from __future__ import annotations

from vmx.builders.exceptions import BuilderValidationError

__all__ = [
    "BuilderValidationError",
]
