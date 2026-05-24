"""ForwardingCompositeVM — forwarding decorator for CompositeVMProto[VM].

Every public member — including the MutableSequence-like surface, ``current``,
``select_component`` / ``deselect_component`` / ``can_select_component``, and
``on_collection_changed`` — delegates to ``_wrapped`` by default. Subclasses
override individual members to customise behaviour.

See spec/09-forwarding.md §ForwardingCompositeVM and FWD-003 in
spec/12-conformance.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Generic, TypeVar, cast

import reactivex as rx

from vmx.commands.relay_command import RelayCommand
from vmx.components.protocols import ViewModelType
from vmx.composites.protocols import CompositeVMProto
from vmx.lifecycle.status import ConstructionStatus

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
        self._wrapped: CompositeVMProto[VM] = wrapped

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

    # ── CompositeVM: collection query ─────────────────────────────────────────
    # CompositeVMProto is a structural Protocol that intentionally omits the full
    # MutableSequence surface (__iter__, __getitem__, __contains__, index_of, plus
    # the mutation methods below) because concrete CompositeVM / GroupVM implement
    # them but they are not part of the Protocol contract every wrapper must declare.
    # The type: ignore tags below acknowledge the gap mypy reports on Protocol calls.

    def __iter__(self) -> Iterator[VM]:
        return cast(Iterator[VM], iter(self._wrapped))  # type: ignore[call-overload]

    def __getitem__(self, index: int) -> VM:
        return cast(VM, self._wrapped[index])  # type: ignore[index]

    def __contains__(self, item: object) -> bool:
        return bool(item in self._wrapped)  # type: ignore[operator]

    def index_of(self, item: VM) -> int:
        return int(self._wrapped.index_of(item))  # type: ignore[attr-defined]

    # ── CompositeVM: collection mutation ──────────────────────────────────────
    # Same Protocol-gap reasoning as above for the mutation surface.

    def add(self, item: VM) -> None:
        self._wrapped.add(item)  # type: ignore[attr-defined]

    def remove(self, item: VM) -> bool:
        return bool(self._wrapped.remove(item))  # type: ignore[attr-defined]

    def insert(self, index: int, item: VM) -> None:
        self._wrapped.insert(index, item)  # type: ignore[attr-defined]

    def remove_at(self, index: int) -> None:
        self._wrapped.remove_at(index)  # type: ignore[attr-defined]

    def clear(self) -> None:
        self._wrapped.clear()  # type: ignore[attr-defined]
