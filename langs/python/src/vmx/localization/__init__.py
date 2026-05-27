"""VMx localization hooks. See spec/17-localization.md and ADR-0019."""

from __future__ import annotations

from vmx.localization.localizer import ILocalizer
from vmx.localization.null_localizer import NULL_LOCALIZER, NullLocalizer

__all__ = [
    "NULL_LOCALIZER",
    "ILocalizer",
    "NullLocalizer",
]
