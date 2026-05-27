"""Immutable fluent builders for CompositeVM and CompositeVMOf.

Each setter returns a NEW builder instance via ``dataclasses.replace`` (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError`` on failure
(BLD-002).

See spec/10-builders.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from typing import Generic, TypeVar

from vmx.builders import _validation
from vmx.builders.exceptions import BuilderValidationError
from vmx.components.base import _ComponentVMBase
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

VM = TypeVar("VM", bound=_ComponentVMBase)
M = TypeVar("M")


# ---------------------------------------------------------------------------
# CompositeVMBuilder — non-modeled CompositeVM
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class CompositeVMBuilder(Generic[VM]):
    """Immutable fluent builder for :class:`~vmx.composites.composite_vm.CompositeVM`.

    Required fields: ``name``, ``services(hub, dispatcher)``.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _async_selection: bool = dataclasses.field(default=False)
    _auto_construct_on_add: bool = dataclasses.field(default=False)
    _children_factory: Callable[[], Iterable[VM]] | None = dataclasses.field(default=None)
    _on_construct: Callable[[], None] | None = dataclasses.field(default=None)
    _on_destruct: Callable[[], None] | None = dataclasses.field(default=None)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def name(self, value: str) -> CompositeVMBuilder[VM]:
        """Set the required ``name`` field."""
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> CompositeVMBuilder[VM]:
        """Set the optional ``hint`` field (default: empty string)."""
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> CompositeVMBuilder[VM]:
        """Set the required hub and dispatcher."""
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def async_selection(self, value: bool) -> CompositeVMBuilder[VM]:
        """Enable/disable async selection dispatch (default: False)."""
        return dataclasses.replace(self, _async_selection=value)

    def auto_construct_on_add(self, value: bool) -> CompositeVMBuilder[VM]:
        """When True, children added after the composite is Constructed are auto-constructed."""
        return dataclasses.replace(self, _auto_construct_on_add=value)

    def children(self, factory: Callable[[], Iterable[VM]]) -> CompositeVMBuilder[VM]:
        """Set the optional children factory evaluated lazily on construct()."""
        return dataclasses.replace(self, _children_factory=factory)

    def on_construct(self, callback: Callable[[], None]) -> CompositeVMBuilder[VM]:
        """Set the optional on_construct lifecycle callback."""
        return dataclasses.replace(self, _on_construct=callback)

    def on_destruct(self, callback: Callable[[], None]) -> CompositeVMBuilder[VM]:
        """Set the optional on_destruct lifecycle callback."""
        return dataclasses.replace(self, _on_destruct=callback)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> CompositeVM[VM]:
        """Validate and construct a :class:`~vmx.composites.composite_vm.CompositeVM`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        from vmx.composites.composite_vm import CompositeVM

        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)

        return CompositeVM(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            async_selection=self._async_selection,
            auto_construct_on_add=self._auto_construct_on_add,
            children_factory=self._children_factory,
            on_construct=self._on_construct,
            on_destruct=self._on_destruct,
        )


# ---------------------------------------------------------------------------
# CompositeVMOfBuilder — modeled CompositeVMOf
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class CompositeVMOfBuilder(Generic[M, VM]):
    """Immutable fluent builder for :class:`~vmx.composites.composite_vm.CompositeVMOf`.

    Required fields: ``name``, ``services(hub, dispatcher)``,
    ``children_models``, ``child_model_to_child_view_model``.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _async_selection: bool = dataclasses.field(default=False)
    _auto_construct_on_add: bool = dataclasses.field(default=False)
    _children_models: Callable[[], Iterable[M]] | None = dataclasses.field(default=None)
    _child_model_to_child_vm: Callable[[M], VM] | None = dataclasses.field(default=None)
    _on_construct: Callable[[], None] | None = dataclasses.field(default=None)
    _on_destruct: Callable[[], None] | None = dataclasses.field(default=None)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def name(self, value: str) -> CompositeVMOfBuilder[M, VM]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> CompositeVMOfBuilder[M, VM]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> CompositeVMOfBuilder[M, VM]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def async_selection(self, value: bool) -> CompositeVMOfBuilder[M, VM]:
        return dataclasses.replace(self, _async_selection=value)

    def auto_construct_on_add(self, value: bool) -> CompositeVMOfBuilder[M, VM]:
        """When True, children added after the composite is Constructed are auto-constructed."""
        return dataclasses.replace(self, _auto_construct_on_add=value)

    def children_models(self, factory: Callable[[], Iterable[M]]) -> CompositeVMOfBuilder[M, VM]:
        """Set the required model factory."""
        return dataclasses.replace(self, _children_models=factory)

    def child_model_to_child_view_model(
        self, mapper: Callable[[M], VM]
    ) -> CompositeVMOfBuilder[M, VM]:
        """Set the required model→VM mapper."""
        return dataclasses.replace(self, _child_model_to_child_vm=mapper)

    def on_construct(self, callback: Callable[[], None]) -> CompositeVMOfBuilder[M, VM]:
        return dataclasses.replace(self, _on_construct=callback)

    def on_destruct(self, callback: Callable[[], None]) -> CompositeVMOfBuilder[M, VM]:
        return dataclasses.replace(self, _on_destruct=callback)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> CompositeVMOf[M, VM]:
        """Validate and construct a :class:`~vmx.composites.composite_vm.CompositeVMOf`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        from vmx.composites.composite_vm import CompositeVMOf

        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
        if self._children_models is None:
            raise BuilderValidationError("children_models")
        if self._child_model_to_child_vm is None:
            raise BuilderValidationError("child_model_to_child_view_model")

        return CompositeVMOf(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            async_selection=self._async_selection,
            auto_construct_on_add=self._auto_construct_on_add,
            children_models=self._children_models,
            child_model_to_child_vm=self._child_model_to_child_vm,
            on_construct=self._on_construct,
            on_destruct=self._on_destruct,
        )


# Forward references
from vmx.composites.composite_vm import CompositeVM, CompositeVMOf  # noqa: E402

__all__ = [
    "CompositeVMBuilder",
    "CompositeVMOfBuilder",
]
