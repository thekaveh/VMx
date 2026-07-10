"""Shared protocols for lifecycle-aware VM child collections."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

import reactivex as rx

from vmx.collections.batch import BatchUpdateHandle
from vmx.components.protocols import ComponentVMProto

VM_co = TypeVar("VM_co", covariant=True)


@runtime_checkable
class VmCollectionProto(ComponentVMProto, Protocol, Generic[VM_co]):
    """Ordered observable VM collection without selection semantics."""

    @property
    def count(self) -> int: ...

    @property
    def on_collection_changed(self) -> rx.Observable[object]: ...

    def __len__(self) -> int: ...

    def __iter__(self) -> Iterator[VM_co]: ...

    def __getitem__(self, index: int) -> VM_co: ...

    def __setitem__(self, index: int, value: Any) -> None: ...

    def add(self, item: Any) -> None: ...

    def insert(self, index: int, item: Any) -> None: ...

    def remove(self, item: Any) -> bool: ...

    def remove_at(self, index: int) -> None: ...

    def clear(self) -> None: ...

    def move(self, from_index: int, to_index: int) -> None: ...

    def batch_update(self) -> BatchUpdateHandle: ...


@runtime_checkable
class SelectableVmCollectionProto(VmCollectionProto[VM_co], Protocol, Generic[VM_co]):
    """VM collection that additionally owns a current-child slot."""

    @property
    def current(self) -> VM_co | None: ...

    @current.setter
    def current(self, value: Any) -> None: ...

    def select_component(self, vm: Any) -> None: ...

    def deselect_component(self, vm: Any) -> None: ...

    def can_select_component(self, vm: Any) -> bool: ...
