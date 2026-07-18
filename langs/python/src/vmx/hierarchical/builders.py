"""Immutable fluent builder for :class:`~vmx.hierarchical.hierarchical_vm.HierarchicalVM`.

Each setter returns a NEW builder instance via ``dataclasses.replace`` (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError`` on failure
(BLD-002). Per ADR-0035 §2 H1 / H2.

In Python, ``HierarchicalVM[TModel, TVM]`` is concrete-enough to instantiate
directly (unlike the C# variant), so the builder constructs a plain
``HierarchicalVM`` by default. Consumers with a concrete subclass set a
``vm_factory`` callable to wire their subclass instead.

See spec/10-builders.md §3 (the HierarchicalVM required-fields row) and
spec/18-hierarchical-vm.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Generic, TypeVar

from vmx.builders import _validation
from vmx.builders.exceptions import BuilderValidationError
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

TModel = TypeVar("TModel")
TVM = TypeVar("TVM", bound="Any")

_MODEL_SENTINEL = object()  # marker for "model not set"


@dataclasses.dataclass(frozen=True, slots=True)
class HierarchicalVMBuilder(Generic[TModel, TVM]):
    """Immutable fluent builder for :class:`HierarchicalVM`.

    Required fields: ``model(TModel)``, ``children_factory(callable)``,
    ``services(hub, dispatcher)``.

    Optional: ``name``, ``hint``, ``eager_children``,
    ``vm_factory`` (override the concrete VM class), plus the ``with_default_services``
    Wither (default-services opt-in) per ADR-0035 §2 H2.

    Usage::

        node = (
            HierarchicalVMBuilder()
            .model(root_model)
            .children_factory(lambda parent: [...])
            .services(hub, dispatcher)
            .eager_children(True)
            .build()
        )

    For a consumer with a custom subclass::

        node = (
            HierarchicalVMBuilder()
            .model(root_model)
            .children_factory(lambda parent: [...])
            .vm_factory(NoteVM)  # the consumer's subclass
            .services(hub, dispatcher)
            .build()
        )
    """

    __orig_class__: object = dataclasses.field(init=False, repr=False, compare=False)
    _model: object = dataclasses.field(default=_MODEL_SENTINEL)
    _model_set: bool = dataclasses.field(default=False)
    _children_factory: Callable[[Any], Iterable[Any]] | None = dataclasses.field(default=None)
    _hub: MessageHub[Any] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _eager_children: bool = dataclasses.field(default=False)
    _vm_factory: Callable[..., Any] | None = dataclasses.field(default=None)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def model(self, value: TModel) -> HierarchicalVMBuilder[TModel, TVM]:
        """Set the required ``model`` for this node."""
        return dataclasses.replace(self, _model=value, _model_set=True)

    def children_factory(
        self, value: Callable[[TVM], Iterable[TVM]]
    ) -> HierarchicalVMBuilder[TModel, TVM]:
        """Set the required ``children_factory`` callable (parent -> iterable of TVM)."""
        return dataclasses.replace(self, _children_factory=value)

    def services(
        self, hub: MessageHub[Any], dispatcher: Dispatcher
    ) -> HierarchicalVMBuilder[TModel, TVM]:
        """Set the required hub + dispatcher."""
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def name(self, value: str) -> HierarchicalVMBuilder[TModel, TVM]:
        """Set the optional ``name`` (default: concrete class name)."""
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> HierarchicalVMBuilder[TModel, TVM]:
        """Set the optional ``hint`` (default: empty string)."""
        return dataclasses.replace(self, _hint=value)

    def eager_children(self, value: bool) -> HierarchicalVMBuilder[TModel, TVM]:
        """When ``True``, materializes the entire subtree at construct() time."""
        return dataclasses.replace(self, _eager_children=value)

    def vm_factory(self, factory: Callable[..., TVM]) -> HierarchicalVMBuilder[TModel, TVM]:
        """Set the concrete VM class (or factory callable) to instantiate.

        Default: ``HierarchicalVM`` itself. Consumers with a subclass should
        set this to that subclass. The factory is invoked with keyword args
        ``model``, ``children_factory``, ``hub``, ``dispatcher``, ``name``,
        ``hint``, ``eager_children``.
        """
        return dataclasses.replace(self, _vm_factory=factory)

    def with_default_services(self) -> HierarchicalVMBuilder[TModel, TVM]:
        """Chainable Wither that explicitly opts in to default hub + dispatcher
        wiring (``MessageHub()`` + ``RxDispatcher.immediate()``). Per ADR-0035
        §2 H2. Since vmx v3.0.0 the ``HierarchicalVM`` constructor requires
        explicit ``hub``/``dispatcher`` (ADR-0052; VMX-080), so this Wither is
        the supported way to request the convenience defaults from the builder.
        """
        from vmx.services.dispatcher import RxDispatcher

        return self.services(MessageHub(), RxDispatcher.immediate())

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> TVM:
        """Validate required fields and construct a :class:`HierarchicalVM`.

        Raises
        ------
        BuilderValidationError
            If ``model``, ``children_factory``, or ``services`` is not set.
        """
        from vmx.hierarchical.hierarchical_vm import HierarchicalVM

        if not self._model_set:
            raise BuilderValidationError("model")
        children_factory = _validation.require_field(self._children_factory, "children_factory")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)

        factory: Callable[..., Any] = self._vm_factory or HierarchicalVM
        result: TVM = factory(
            model=self._model,
            children_factory=children_factory,
            hub=hub,
            dispatcher=dispatcher,
            name=self._name,
            hint=self._hint,
            eager_children=self._eager_children,
        )
        return result


__all__ = ["HierarchicalVMBuilder"]
