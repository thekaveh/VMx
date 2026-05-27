"""Immutable fluent builders for ComponentVM, ComponentVMOf, ReadonlyComponentVMOf.

Each setter returns a NEW builder instance via ``dataclasses.replace`` (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError`` on failure
(BLD-002).

See spec/10-builders.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.builders import _validation
from vmx.builders.exceptions import BuilderValidationError
from vmx.components.protocols import ViewModelType
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

M = TypeVar("M")

_SENTINEL = object()  # marker for "model not set"


# ---------------------------------------------------------------------------
# ComponentVMBuilder — non-modeled ComponentVM
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ComponentVMBuilder:
    """Immutable fluent builder for :class:`ComponentVM`.

    Required fields: ``name``, ``services(hub, dispatcher)``.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _on_construct: Callable[[], None] | None = dataclasses.field(default=None)
    _on_destruct: Callable[[], None] | None = dataclasses.field(default=None)
    _background: bool = dataclasses.field(default=False)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def name(self, value: str) -> ComponentVMBuilder:
        """Set the required ``name`` field."""
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> ComponentVMBuilder:
        """Set the optional ``hint`` field (default: empty string)."""
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> ComponentVMBuilder:
        """Set the required hub and dispatcher."""
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def on_construct(self, callback: Callable[[], None]) -> ComponentVMBuilder:
        """Set the optional on_construct lifecycle callback."""
        return dataclasses.replace(self, _on_construct=callback)

    def on_destruct(self, callback: Callable[[], None]) -> ComponentVMBuilder:
        """Set the optional on_destruct lifecycle callback."""
        return dataclasses.replace(self, _on_destruct=callback)

    def background(self, value: bool) -> ComponentVMBuilder:
        """Enable/disable background scheduling (default: False)."""
        return dataclasses.replace(self, _background=value)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> ComponentVM:
        """Validate and construct a :class:`ComponentVM`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        from vmx.components.component_vm import ComponentVM

        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)

        return ComponentVM(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=self._on_construct,
            on_destruct=self._on_destruct,
            background=self._background,
        )


# ---------------------------------------------------------------------------
# ComponentVMOfBuilder[M] — modeled ComponentVMOf
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ComponentVMOfBuilder(Generic[M]):
    """Immutable fluent builder for :class:`ComponentVMOf`.

    Required fields: ``name``, ``model``, ``services(hub, dispatcher)``.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _model: object = dataclasses.field(default=_SENTINEL)
    _model_set: bool = dataclasses.field(default=False)
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _modeled_hinter: Callable[[M], str] | None = dataclasses.field(default=None)
    _on_model_changed: Callable[[M], None] | None = dataclasses.field(default=None)
    _on_construct: Callable[[], None] | None = dataclasses.field(default=None)
    _on_destruct: Callable[[], None] | None = dataclasses.field(default=None)
    _background: bool = dataclasses.field(default=False)
    _vm_type: ViewModelType = dataclasses.field(default=ViewModelType.COMPONENT)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def name(self, value: str) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _hint=value)

    def model(self, value: M) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _model=value, _model_set=True)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def modeled_hinter(self, hinter: Callable[[M], str]) -> ComponentVMOfBuilder[M]:
        """Set the optional modeled_hinter function (default: ``lambda m: ""``)."""
        return dataclasses.replace(self, _modeled_hinter=hinter)

    def on_model_changed(self, callback: Callable[[M], None]) -> ComponentVMOfBuilder[M]:
        """Set the optional on_model_changed callback."""
        return dataclasses.replace(self, _on_model_changed=callback)

    def on_construct(self, callback: Callable[[], None]) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _on_construct=callback)

    def on_destruct(self, callback: Callable[[], None]) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _on_destruct=callback)

    def background(self, value: bool) -> ComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _background=value)

    def vm_type(self, value: ViewModelType) -> ComponentVMOfBuilder[M]:
        """Override the VM type (default: COMPONENT)."""
        return dataclasses.replace(self, _vm_type=value)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> ComponentVMOf[M]:
        """Validate and construct a :class:`ComponentVMOf`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        from vmx.components.component_vm import ComponentVMOf

        name = _validation.require_field(self._name, "name")
        if not self._model_set:
            raise BuilderValidationError("model")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)

        hinter: Callable[[M], str] = (
            self._modeled_hinter if self._modeled_hinter is not None else lambda _m: ""
        )

        return ComponentVMOf(
            name=name,
            hint=self._hint,
            # `self._model` is typed `object | None` to allow the _SENTINEL sentinel
            # value; the `_model_set` guard above proves it's the real `M` at this
            # point, but mypy cannot narrow the dataclass field.
            initial_model=self._model,  # type: ignore[arg-type]
            modeled_hinter=hinter,
            on_model_changed=self._on_model_changed,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=self._on_construct,
            on_destruct=self._on_destruct,
            background=self._background,
            vm_type=self._vm_type,
        )


# ---------------------------------------------------------------------------
# ReadonlyComponentVMOfBuilder[M] — readonly modeled VM
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ReadonlyComponentVMOfBuilder(Generic[M]):
    """Immutable fluent builder for :class:`ReadonlyComponentVMOf`.

    Required fields: ``name``, ``model``, ``services(hub, dispatcher)``.
    Model is frozen at build time — there is no setter on the VM.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _model: object = dataclasses.field(default=_SENTINEL)
    _model_set: bool = dataclasses.field(default=False)
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _modeled_hinter: Callable[[M], str] | None = dataclasses.field(default=None)
    _on_construct: Callable[[], None] | None = dataclasses.field(default=None)
    _on_destruct: Callable[[], None] | None = dataclasses.field(default=None)
    _background: bool = dataclasses.field(default=False)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def name(self, value: str) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _hint=value)

    def model(self, value: M) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _model=value, _model_set=True)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def modeled_hinter(self, hinter: Callable[[M], str]) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _modeled_hinter=hinter)

    def on_construct(self, callback: Callable[[], None]) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _on_construct=callback)

    def on_destruct(self, callback: Callable[[], None]) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _on_destruct=callback)

    def background(self, value: bool) -> ReadonlyComponentVMOfBuilder[M]:
        return dataclasses.replace(self, _background=value)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> ReadonlyComponentVMOf[M]:
        """Validate and construct a :class:`ReadonlyComponentVMOf`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        from vmx.components.readonly_component_vm import ReadonlyComponentVMOf

        name = _validation.require_field(self._name, "name")
        if not self._model_set:
            raise BuilderValidationError("model")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)

        hinter: Callable[[M], str] = (
            self._modeled_hinter if self._modeled_hinter is not None else lambda _m: ""
        )

        return ReadonlyComponentVMOf(
            name=name,
            hint=self._hint,
            # Same sentinel-narrowing case as ComponentVMOfBuilder above.
            model=self._model,  # type: ignore[arg-type]
            modeled_hinter=hinter,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=self._on_construct,
            on_destruct=self._on_destruct,
            background=self._background,
        )


# Forward references — these classes are defined in separate modules
# that import from this module, so we import here for type annotations only.
from vmx.components.component_vm import ComponentVM, ComponentVMOf  # noqa: E402
from vmx.components.readonly_component_vm import ReadonlyComponentVMOf  # noqa: E402

__all__ = [
    "ComponentVMBuilder",
    "ComponentVMOfBuilder",
    "ReadonlyComponentVMOfBuilder",
]
