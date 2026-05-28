"""FormVM — snapshot/revert edit lifecycle ViewModel (chapter 20, ADR-0030).

Public API
----------
- :class:`FormVM` — wraps a mutable domain model with edit lifecycle.
"""

from __future__ import annotations

from vmx.forms.form_vm import FormVM

__all__ = ["FormVM"]
