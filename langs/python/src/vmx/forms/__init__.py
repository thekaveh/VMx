"""FormVM — snapshot/revert edit lifecycle ViewModel (chapter 20, ADR-0030).

Public API
----------
- :class:`FormVM` — wraps a mutable domain model with edit lifecycle.
- :class:`FormVMBuilder` — immutable fluent builder for :class:`FormVM`
  (ADR-0035 §2 FV1).
"""

from __future__ import annotations

from vmx.forms.builders import FormVMBuilder
from vmx.forms.form_vm import FormVM

__all__ = ["FormVM", "FormVMBuilder"]
