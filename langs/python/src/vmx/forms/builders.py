"""Immutable fluent builder for :class:`~vmx.forms.form_vm.FormVM`.

Each setter returns a NEW builder instance via ``dataclasses.replace`` (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError`` on failure
(BLD-002). Per ADR-0035 §2 FV1 / FV2.

See spec/10-builders.md §3 (the FormVM required-fields row) and
spec/20-form-vm.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from vmx.builders.exceptions import BuilderValidationError
from vmx.services.message_hub import MessageHubProto

TM = TypeVar("TM")

_SENTINEL = object()  # marker for "initial not set"


@dataclasses.dataclass(frozen=True, slots=True)
class FormVMBuilder(Generic[TM]):
    """Immutable fluent builder for :class:`FormVM`.

    Required fields: ``initial(TM)``, ``persister(Callable[[TM], Awaitable[None]])``.
    Optional fields: ``hub``, ``strict``, ``snapshotter``.

    Usage::

        form = (
            FormVMBuilder()
            .initial(note)
            .persister(repo.save)
            .strict(True)
            .build()
        )
    """

    _initial: object = dataclasses.field(default=_SENTINEL)
    _initial_set: bool = dataclasses.field(default=False)
    _persister: Callable[[Any], Awaitable[None]] | None = dataclasses.field(default=None)
    _hub: MessageHubProto[Any] | None = dataclasses.field(default=None)
    _strict: bool = dataclasses.field(default=False)
    _snapshotter: Callable[[Any], Any] | None = dataclasses.field(default=None)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def initial(self, value: TM) -> FormVMBuilder[TM]:
        """Set the required initial domain model."""
        return dataclasses.replace(self, _initial=value, _initial_set=True)

    def persister(self, value: Callable[[TM], Awaitable[None]]) -> FormVMBuilder[TM]:
        """Set the required async persister callable ``(model) -> Awaitable[None]``."""
        return dataclasses.replace(self, _persister=value)

    def hub(self, value: MessageHubProto[Any]) -> FormVMBuilder[TM]:
        """Set the optional message hub (default: ``NULL_MESSAGE_HUB``)."""
        return dataclasses.replace(self, _hub=value)

    def strict(self, value: bool) -> FormVMBuilder[TM]:
        """Enable strict mode (``approve_command.can_execute()`` gates on ``is_dirty``).

        Default: ``False``.
        """
        return dataclasses.replace(self, _strict=value)

    def snapshotter(self, value: Callable[[TM], TM]) -> FormVMBuilder[TM]:
        """Set a custom snapshot function (default: ``copy.deepcopy``)."""
        return dataclasses.replace(self, _snapshotter=value)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> FormVM[TM]:
        """Validate required fields and construct a :class:`FormVM`.

        Raises
        ------
        BuilderValidationError
            If ``initial`` or ``persister`` is not set (per spec/10 §3).
        """
        from vmx.forms.form_vm import FormVM

        if not self._initial_set:
            raise BuilderValidationError("initial")
        if self._persister is None:
            raise BuilderValidationError("persister")

        # The sentinel-narrowing case: _initial is typed `object` so the
        # _SENTINEL marker can live in the field; the _initial_set guard above
        # proves it's a real TM at this point.
        return FormVM[TM](
            initial=self._initial,  # type: ignore[arg-type]
            persister=self._persister,
            hub=self._hub,
            strict=self._strict,
            snapshotter=self._snapshotter,
        )


# Deferred import to avoid circular references.
from vmx.forms.form_vm import FormVM  # noqa: E402

__all__ = ["FormVMBuilder"]
