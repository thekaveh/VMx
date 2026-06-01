"""Immutable fluent builder for GroupVM (non-modeled).

Each setter returns a NEW builder instance (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError``
on failure (BLD-002).

See spec/07-group-vm.md §Builder and spec/10-builders.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from typing import Generic, TypeVar

from vmx.builders import _validation
from vmx.components.base import _ComponentVMBase
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

VM = TypeVar("VM", bound=_ComponentVMBase)


@dataclasses.dataclass(frozen=True, slots=True)
class GroupVMBuilder(Generic[VM]):
    """Immutable fluent builder for :class:`GroupVM`.

    Required fields: ``name``, ``services(hub, dispatcher)``.

    Usage::

        from vmx.groups.builders import GroupVMBuilder

        group = (
            GroupVMBuilder()
            .name("my-group")
            .services(hub, dispatcher)
            .children(lambda: [child_a, child_b])
            .build()
        )
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _auto_construct_on_add: bool = dataclasses.field(default=False)
    _children_factory: Callable[[], Iterable[VM]] | None = dataclasses.field(default=None)
    _on_construct: Callable[[], None] | None = dataclasses.field(default=None)
    _on_destruct: Callable[[], None] | None = dataclasses.field(default=None)

    # ── Fluent setters ───────────────────────────────────────────────────────

    def name(self, value: str) -> GroupVMBuilder[VM]:
        """Set the required ``name`` field."""
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> GroupVMBuilder[VM]:
        """Set the optional ``hint`` field (default: ``""``)."""
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> GroupVMBuilder[VM]:
        """Set the required hub and dispatcher."""
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def auto_construct_on_add(self, value: bool) -> GroupVMBuilder[VM]:
        """When True, children added after the group is Constructed are auto-constructed."""
        return dataclasses.replace(self, _auto_construct_on_add=value)

    def children(self, factory: Callable[[], Iterable[VM]]) -> GroupVMBuilder[VM]:
        """Set the required children factory, invoked lazily on ``construct()``.

        For a group with no initial children, pass ``lambda: ()`` or
        ``lambda: []`` (per spec/10-builders.md §3 / ADR-0035).
        """
        return dataclasses.replace(self, _children_factory=factory)

    def on_construct(self, callback: Callable[[], None]) -> GroupVMBuilder[VM]:
        """Set the optional on_construct lifecycle callback."""
        return dataclasses.replace(self, _on_construct=callback)

    def on_destruct(self, callback: Callable[[], None]) -> GroupVMBuilder[VM]:
        """Set the optional on_destruct lifecycle callback."""
        return dataclasses.replace(self, _on_destruct=callback)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> GroupVM[VM]:
        """Validate required fields and construct a :class:`GroupVM`.

        Raises
        ------
        BuilderValidationError
            If ``name``, ``hub``, ``dispatcher``, or ``children`` are not set.
        """
        from vmx.groups.group_vm import GroupVM

        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
        children_factory = _validation.require_field(self._children_factory, "children")

        return GroupVM(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            auto_construct_on_add=self._auto_construct_on_add,
            children_factory=children_factory,
            on_construct=self._on_construct,
            on_destruct=self._on_destruct,
        )


# Deferred import to avoid circular references.
from vmx.groups.group_vm import GroupVM  # noqa: E402

__all__ = ["GroupVMBuilder"]
