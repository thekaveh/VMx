"""ComponentVM (non-modeled) and ComponentVMOf[M] (modeled with settable model).

See spec/05-component-vm.md §Variants.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ViewModelType
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHubProto

M = TypeVar("M")


# ---------------------------------------------------------------------------
# ComponentVM — non-modeled leaf VM
# ---------------------------------------------------------------------------


class ComponentVM(_ComponentVMBase):
    """Non-modeled leaf viewmodel.

    No model field. Use ``ComponentVM.builder()`` to construct instances.

    Type identifier: ``ViewModelType.COMPONENT``.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        background: bool = False,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=on_construct,
            on_destruct=on_destruct,
            background=background,
        )

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    @staticmethod
    def builder() -> ComponentVMBuilder:
        """Return a new immutable builder for :class:`ComponentVM`."""
        return ComponentVMBuilder()

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        hub: MessageHubProto[Message] | None = None,
        dispatcher: Dispatcher | None = None,
        hint: str = "",
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        background: bool = False,
    ) -> ComponentVM:
        """Construct a :class:`ComponentVM` from keyword options in one call.

        An additive alternative to :meth:`builder` (ADR-0055 / VMX-020).
        Delegates to :class:`ComponentVMBuilder`, so required-field validation
        (``BuilderValidationError`` on a missing ``name``/``hub``/``dispatcher``)
        and the resulting VM are identical to the fluent path.
        """
        builder = ComponentVMBuilder().hint(hint).background(background)
        if name is not None:
            builder = builder.name(name)
        if hub is not None and dispatcher is not None:
            builder = builder.services(hub, dispatcher)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        if on_destruct is not None:
            builder = builder.on_destruct(on_destruct)
        return builder.build()


# ---------------------------------------------------------------------------
# ComponentVMOf[M] — modeled leaf VM (settable model)
# ---------------------------------------------------------------------------


class ComponentVMOf(Generic[M], _ComponentVMBase):
    """Modeled leaf viewmodel with settable model.

    Use ``ComponentVMOf.builder()`` to construct instances.

    Type identifier: ``ViewModelType.COMPONENT``.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        initial_model: M,
        modeled_hinter: Callable[[M], str],
        on_model_changed: Callable[[M], None] | None,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        background: bool = False,
        vm_type: ViewModelType = ViewModelType.COMPONENT,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=on_construct,
            on_destruct=on_destruct,
            background=background,
        )
        self._model: M = initial_model
        self._modeled_hinter: Callable[[M], str] = modeled_hinter
        self._on_model_changed_cb: Callable[[M], None] | None = on_model_changed
        self._modeled_hint: str = modeled_hinter(initial_model)
        self._vm_type: ViewModelType = vm_type

    @property
    def type(self) -> ViewModelType:
        return self._vm_type

    @property
    def model(self) -> M:
        """The current model value."""
        return self._model

    @model.setter
    def model(self, value: M) -> None:
        """Set the model, emitting PropertyChangedMessage only on actual change."""
        self._set_model(value)

    @property
    def modeled_hint(self) -> str:
        """Derived hint computed from the current model via modeled_hinter."""
        return self._modeled_hint

    def _set_model(self, value: M) -> None:
        """Apply equality-guarded model update per spec/05-component-vm.md."""
        if self._is_disposed():
            return
        if self._model == value:
            return

        self._model = value

        self._notify_property_changed("model")

        # Recompute modeled_hint.
        new_hint = self._modeled_hinter(value)
        if self._modeled_hint != new_hint:
            self._modeled_hint = new_hint
            self._notify_property_changed("modeled_hint")

        # Invoke on_model_changed callback.
        if self._on_model_changed_cb is not None:
            self._on_model_changed_cb(value)

    @staticmethod
    def builder() -> ComponentVMOfBuilder[M]:
        """Return a new immutable builder for :class:`ComponentVMOf`."""
        return ComponentVMOfBuilder()

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        model: M,
        hub: MessageHubProto[Message] | None = None,
        dispatcher: Dispatcher | None = None,
        hint: str = "",
        modeled_hinter: Callable[[M], str] | None = None,
        on_model_changed: Callable[[M], None] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        background: bool = False,
        vm_type: ViewModelType = ViewModelType.COMPONENT,
    ) -> ComponentVMOf[M]:
        """Construct a :class:`ComponentVMOf` from keyword options in one call.

        An additive alternative to :meth:`builder` (ADR-0055 / VMX-020).
        Delegates to :class:`ComponentVMOfBuilder`, so required-field validation
        (``BuilderValidationError`` on a missing ``name``/``hub``/``dispatcher``)
        and the resulting VM are identical to the fluent path. ``model`` is a
        required keyword.
        """
        builder: ComponentVMOfBuilder[M] = ComponentVMOfBuilder()
        builder = builder.model(model).hint(hint).background(background).vm_type(vm_type)
        if name is not None:
            builder = builder.name(name)
        if hub is not None and dispatcher is not None:
            builder = builder.services(hub, dispatcher)
        if modeled_hinter is not None:
            builder = builder.modeled_hinter(modeled_hinter)
        if on_model_changed is not None:
            builder = builder.on_model_changed(on_model_changed)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        if on_destruct is not None:
            builder = builder.on_destruct(on_destruct)
        return builder.build()


# Deferred import to avoid circular references — builders imports component_vm.
from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder  # noqa: E402
