"""Builder validation exceptions.

See spec/10-builders.md §Validation.
"""

from __future__ import annotations


class BuilderValidationError(ValueError):
    """Raised by a builder's ``build()`` method when a required field is missing.

    Attributes
    ----------
    missing_field:
        The name of the first missing required field that caused the failure.
    """

    def __init__(self, missing_field: str) -> None:
        self.missing_field: str = missing_field
        super().__init__(f"Required field '{missing_field}' was not set on the builder.")
