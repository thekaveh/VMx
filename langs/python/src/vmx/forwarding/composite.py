"""ForwardingCompositeVM — forwarding decorator for CompositeVMProto[VM].

Every public member — including the MutableSequence-like surface, ``current``,
``select_component`` / ``deselect_component`` / ``can_select_component``,
the parent-composite child-selection surface (``current_child``,
``select_child``, ``deselect_child``, ``supports_child_selection``), the
membership-source surface (``snapshot`` / ``subscribe_membership``), and
``on_collection_changed`` — delegates to ``_wrapped`` by default. Subclasses
override individual members to customise behaviour.

See spec/09-forwarding.md §ForwardingCompositeVM and FWD-003 in
spec/12-conformance.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Generic, TypeVar, cast

import reactivex as rx
from reactivex.abc import DisposableBase

from vmx.collections import BatchUpdateHandle
from vmx.commands.relay_command import RelayCommand
from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ViewModelType
from vmx.composites.composite_vm import _CompositeVMBase
from vmx.composites.protocols import CompositeVMProto
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.message_hub import MessageHubProto

VM = TypeVar("VM")


class ForwardingCompositeVM(Generic[VM]):
    """Forwarding decorator for :class:`~vmx.composites.protocols.CompositeVMProto`.

    Every member delegates to the wrapped composite by default. Subclasses
    override individual members to customise behaviour.

    This is not abstract: the class is usable as-is; subclassing is expected
    rather than enforced. See spec/09-forwarding.md.
    """

    def __init__(self, wrapped: CompositeVMProto[VM]) -> None:
        if wrapped is None:
            raise ValueError("wrapped must not be None")
        # The public contract accepts any ``CompositeVMProto``, but forwarding
        # the full MutableSequence surface (add/insert/remove_at/index/…) needs
        # the concrete composite members. Every shipped composite is a
        # ``_CompositeVMBase``; narrow once here (``Any`` element type — the
        # wrapper's own ``VM`` is unbounded) so the per-call ``type: ignore``
        # masks are unnecessary (VMX-074).
        self._wrapped: _CompositeVMBase[Any] = cast("_CompositeVMBase[Any]", wrapped)

    # ── Identity ─────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._wrapped.name

    @property
    def hint(self) -> str:
        return self._wrapped.hint

    @property
    def type(self) -> ViewModelType:
        return self._wrapped.type

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_current(self) -> bool:
        return self._wrapped.is_current

    @property
    def is_constructed(self) -> bool:
        return self._wrapped.is_constructed

    @property
    def status(self) -> ConstructionStatus:
        return self._wrapped.status

    @property
    def hub(self) -> MessageHubProto[Message]:
        return self._wrapped.hub

    # ── Observable property changes ───────────────────────────────────────────

    @property
    def property_changed(self) -> rx.Observable[object]:
        return self._wrapped.property_changed

    # ── Built-in commands ─────────────────────────────────────────────────────

    @property
    def select_command(self) -> RelayCommand:
        return self._wrapped.select_command

    @property
    def deselect_command(self) -> RelayCommand:
        return self._wrapped.deselect_command

    @property
    def select_next_command(self) -> RelayCommand:
        return self._wrapped.select_next_command

    @property
    def select_previous_command(self) -> RelayCommand:
        return self._wrapped.select_previous_command

    @property
    def reconstruct_command(self) -> RelayCommand:
        return self._wrapped.reconstruct_command

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def can_construct(self) -> bool:
        return self._wrapped.can_construct()

    def construct(self) -> None:
        self._wrapped.construct()

    def can_destruct(self) -> bool:
        return self._wrapped.can_destruct()

    def destruct(self) -> None:
        self._wrapped.destruct()

    def can_reconstruct(self) -> bool:
        return self._wrapped.can_reconstruct()

    def reconstruct(self) -> None:
        self._wrapped.reconstruct()

    def dispose(self) -> None:
        self._wrapped.dispose()

    # ── Selection ─────────────────────────────────────────────────────────────

    def can_select(self) -> bool:
        return self._wrapped.can_select()

    def select(self) -> None:
        self._wrapped.select()

    def can_deselect(self) -> bool:
        return self._wrapped.can_deselect()

    def deselect(self) -> None:
        self._wrapped.deselect()

    # ── Parent-composite surface (child selection on the wrapped composite) ──

    @property
    def supports_child_selection(self) -> bool:
        return self._wrapped.supports_child_selection

    @property
    def current_child(self) -> object | None:
        return self._wrapped.current_child

    def select_child(self, vm: _ComponentVMBase) -> None:
        self._wrapped.select_child(vm)

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        self._wrapped.deselect_child(vm)

    # ── CompositeVM: current and child selection ──────────────────────────────

    @property
    def current(self) -> VM | None:
        return self._wrapped.current

    @current.setter
    def current(self, value: VM | None) -> None:
        self._wrapped.current = value

    def select_component(self, vm: VM) -> None:
        self._wrapped.select_component(vm)

    def deselect_component(self, vm: VM) -> None:
        self._wrapped.deselect_component(vm)

    def can_select_component(self, vm: VM) -> bool:
        return self._wrapped.can_select_component(vm)

    # ── CompositeVM: collection observable ────────────────────────────────────

    @property
    def on_collection_changed(self) -> rx.Observable[object]:
        return self._wrapped.on_collection_changed

    # ── CompositeVM: collection query ─────────────────────────────────────────

    @property
    def count(self) -> int:
        return self._wrapped.count

    def __len__(self) -> int:
        return self._wrapped.count

    # ── CompositeVM: membership source (AggregateChangeStream) ────────────────

    def snapshot(self) -> tuple[VM, ...]:
        return cast("tuple[VM, ...]", self._wrapped.snapshot())

    def subscribe_membership(self, callback: Callable[[], None]) -> DisposableBase:
        return self._wrapped.subscribe_membership(callback)

    # ── CompositeVM: collection query ─────────────────────────────────────────
    # ``_wrapped`` is narrowed to the concrete ``_CompositeVMBase`` in __init__,
    # so the full MutableSequence surface is statically available here (VMX-074).

    def __iter__(self) -> Iterator[VM]:
        return iter(self._wrapped)

    def __getitem__(self, index: int) -> VM:
        return cast(VM, self._wrapped[index])

    def __setitem__(self, index: int, value: VM) -> None:
        self._wrapped[index] = value

    def __delitem__(self, index: int) -> None:
        del self._wrapped[index]

    def __contains__(self, item: object) -> bool:
        return item in self._wrapped

    def index(self, value: VM, start: int = 0, stop: int | None = None) -> int:
        return self._wrapped.index(value, start, stop)

    def index_of(self, item: VM) -> int:
        # CompositeVM exposes the standard MutableSequence `index()` which
        # raises ValueError on absence; convert to -1 to mirror C# `IList<T>.
        # IndexOf` semantics (and GroupVM's own `index_of`). The `index_of`
        # name on the wrapper matches the spec-canonical surface (chapter 06).
        try:
            return self._wrapped.index(item)
        except ValueError:
            return -1

    # ── CompositeVM: collection mutation ──────────────────────────────────────

    def add(self, item: VM) -> None:
        self._wrapped.add(item)

    def append(self, item: VM) -> None:
        self._wrapped.append(item)

    def remove(self, item: VM) -> bool:
        return self._wrapped.remove(item)

    def insert(self, index: int, item: VM) -> None:
        self._wrapped.insert(index, item)

    def remove_at(self, index: int) -> None:
        self._wrapped.remove_at(index)

    def clear(self) -> None:
        self._wrapped.clear()

    def move(self, from_index: int, to_index: int) -> None:
        self._wrapped.move(from_index, to_index)

    def copy_to(self, target: list[VM], array_index: int) -> None:
        self._wrapped.copy_to(target, array_index)

    def batch_update(self) -> BatchUpdateHandle:
        return self._wrapped.batch_update()
