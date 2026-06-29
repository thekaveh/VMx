"""ReadonlyComponentVMOf[M] — readonly modeled leaf VM.

Model is provided at build time and frozen thereafter.

See spec/05-component-vm.md §Readonly variant.
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


class ReadonlyComponentVMOf(Generic[M], _ComponentVMBase):
    """Read-only modeled leaf viewmodel.

    The model is fixed at build time and cannot be changed.
    Use ``ReadonlyComponentVMOf.builder()`` to construct instances.

    Type identifier: ``ViewModelType.READONLY_COMPONENT``.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        model: M,
        modeled_hinter: Callable[[M], str],
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
        self._model: M = model
        self._modeled_hint: str = modeled_hinter(model)

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.READONLY_COMPONENT

    @property
    def model(self) -> M:
        """The model value; read-only (no setter)."""
        return self._model

    @property
    def modeled_hint(self) -> str:
        """Derived hint string; stable (model never changes)."""
        return self._modeled_hint

    @staticmethod
    def builder() -> ReadonlyComponentVMOfBuilder[M]:
        """Return a new immutable builder for :class:`ReadonlyComponentVMOf`."""
        return ReadonlyComponentVMOfBuilder()


# Deferred import to avoid circular references.
from vmx.components.builders import ReadonlyComponentVMOfBuilder  # noqa: E402
