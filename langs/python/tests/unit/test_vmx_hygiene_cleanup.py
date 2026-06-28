"""Regression tests for the VMx Python-hygiene cleanup.

Covers the guarantees introduced by the cleanup batch:

- VMX-013: observable-typed getters expose a sealed ``Observable``, never the
  raw backing ``Subject`` (external callers cannot ``on_next``/``dispose`` and
  corrupt other subscribers), while subscription behaviour is preserved.
- VMX-014: ``ObservableDictionary.keys1``/``keys2`` hand out a read-only view
  with no mutators, yet still expose the granular observables and reflect the
  live key axis.
- VMX-076: ``RxDispatcher`` exposes the asyncio ``loop`` it owns.
- VMX-077: a group child's inherited ``select_command`` reports
  ``can_execute() == False`` (no longer enabled-but-inert); the group reuses a
  single parent adaptor.
- VMX-078: ``HierarchicalVM.children``/``path`` are genuinely read-only and
  identity-stable.
- VMX-096: ``ObservableList``/``ObservableDictionary`` complete their backing
  subjects on ``dispose()``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from reactivex.subject import Subject

from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.collections.observable_list import ObservableList
from vmx.commands.relay_command import RelayCommand
from vmx.components.builders import ComponentVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.hierarchical import HierarchicalVM
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


def _hub() -> MessageHub[Any]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


# ---------------------------------------------------------------------------
# VMX-013 — observable getters are sealed (never the raw Subject)
# ---------------------------------------------------------------------------


def _assert_sealed(observable: object) -> None:
    """A sealed observable exposes neither ``on_next`` nor ``dispose``."""
    assert not isinstance(observable, Subject)
    assert not hasattr(observable, "on_next")
    assert not hasattr(observable, "on_completed")
    assert not hasattr(observable, "dispose")


def test_vmx_013_component_property_changed_is_sealed() -> None:
    vm = ComponentVMBuilder().name("c").services(_hub(), _dispatcher()).build()

    observable = vm.property_changed
    _assert_sealed(observable)
    # Not the raw internal subject — so external code cannot inject/tear it down.
    assert observable is not vm._property_changed_subject

    # Subscription behaviour preserved.
    received: list[str] = []
    observable.subscribe(on_next=received.append)
    vm.construct()
    assert "status" in received


def test_vmx_013_relay_command_can_execute_changed_is_sealed() -> None:
    trigger: Subject[object] = Subject()
    cmd = RelayCommand.builder().task(lambda: None).triggers(trigger).build()

    observable = cmd.can_execute_changed
    _assert_sealed(observable)
    assert observable is not cmd._can_execute_changed_subject

    received: list[Any] = []
    observable.subscribe(on_next=received.append)
    trigger.on_next(None)
    assert len(received) == 1


def test_vmx_013_observable_list_streams_are_sealed() -> None:
    lst: ObservableList[int] = ObservableList()
    _assert_sealed(lst.on_item_added)
    assert lst.on_item_added is not lst._added_subject

    received: list[tuple[int, int]] = []
    lst.on_item_added.subscribe(on_next=received.append)
    lst.add(7)
    assert received == [(7, 0)]


def test_vmx_013_group_on_collection_changed_is_sealed() -> None:
    grp: GroupVM[object] = (
        GroupVMBuilder().name("g").services(_hub(), _dispatcher()).children(lambda: ()).build()
    )
    # Was typed (and returned) as a raw Subject — now a sealed Observable.
    _assert_sealed(grp.on_collection_changed)
    assert grp.on_collection_changed is not grp._collection_changed_subject


# ---------------------------------------------------------------------------
# VMX-014 — ObservableDictionary key views are read-only
# ---------------------------------------------------------------------------


def test_vmx_014_key_views_are_read_only_but_observable() -> None:
    d: ObservableDictionary[str, int, str] = ObservableDictionary()

    keys1 = d.keys1
    # No mutators leaked.
    for mutator in ("add", "append", "insert", "remove", "remove_at", "clear", "replace"):
        assert not hasattr(keys1, mutator), f"keys1 must not expose {mutator!r}"

    # Granular observable still works and the view reflects the live axis.
    added: list[str] = []
    d.keys1.on_item_added.subscribe(on_next=lambda e: added.append(e[0]))
    d.add("a", 1, "v1")
    d.add("a", 2, "v2")  # same key1 -> no new keys1 entry
    d.add("b", 3, "v3")
    assert added == ["a", "b"]
    assert list(d.keys1) == ["a", "b"]
    assert d.keys1.count == 2


# ---------------------------------------------------------------------------
# VMX-076 — RxDispatcher exposes the asyncio loop it owns
# ---------------------------------------------------------------------------


def test_vmx_076_immediate_dispatcher_has_no_loop() -> None:
    assert RxDispatcher.immediate().loop is None


def test_vmx_076_asyncio_dispatcher_exposes_loop() -> None:
    explicit = asyncio.new_event_loop()
    try:
        d = RxDispatcher.asyncio(explicit)
        assert d.loop is explicit
    finally:
        explicit.close()

    created = RxDispatcher.asyncio()
    try:
        assert created.loop is not None
    finally:
        # The factory created this loop; the public accessor lets the caller
        # close it instead of reaching into a private scheduler attribute.
        assert created.loop is not None
        created.loop.close()


# ---------------------------------------------------------------------------
# VMX-077 — group children are not selectable; parent adaptor is cached
# ---------------------------------------------------------------------------


def test_vmx_077_group_child_select_command_is_disabled() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    child = ComponentVMBuilder().name("child").services(hub, dispatcher).build()
    grp: GroupVM[object] = (
        GroupVMBuilder().name("g").services(hub, dispatcher).children(lambda: [child]).build()
    )
    grp.construct()  # constructs the child too

    selected = grp[0]
    assert selected.can_select() is False
    assert selected.select_command.can_execute() is False


def test_vmx_077_group_reuses_single_parent_adaptor() -> None:
    grp: GroupVM[object] = (
        GroupVMBuilder().name("g").services(_hub(), _dispatcher()).children(lambda: ()).build()
    )
    assert grp._as_parent() is grp._as_parent()


# ---------------------------------------------------------------------------
# VMX-078 — HierarchicalVM children/path are read-only and identity-stable
# ---------------------------------------------------------------------------


class _Node(HierarchicalVM[int, "_Node"]):
    def __init__(self, children: list[_Node] | None = None, hub: MessageHub[Any] | None = None):
        super().__init__(
            model=0,
            children_factory=lambda _: children or [],
            hub=hub,
        )


def test_vmx_078_children_are_read_only_and_stable() -> None:
    hub = _hub()
    leaf = _Node(hub=hub)
    root = _Node(children=[leaf], hub=hub)

    children = root.children
    assert root.children is children  # identity-stable (HIER-004)
    with pytest.raises((AttributeError, TypeError)):
        children.append(leaf)  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        children[0] = leaf  # type: ignore[index]

    # Still reflects live structural changes through the read-only view.
    extra = _Node(hub=hub)
    root.add_child(extra)
    assert len(root.children) == 2


def test_vmx_078_path_is_read_only_and_list_comparable() -> None:
    hub = _hub()
    grandchild = _Node(hub=hub)
    child = _Node(children=[grandchild], hub=hub)
    root = _Node(children=[child], hub=hub)
    _ = root.children
    _ = child.children

    path = grandchild.path
    assert path == [root, child, grandchild]  # list-comparable
    assert grandchild.path is path  # cached identity
    with pytest.raises((AttributeError, TypeError)):
        path.append(root)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# VMX-096 — collections complete their subjects on dispose()
# ---------------------------------------------------------------------------


def test_vmx_096_observable_list_dispose_completes_subjects() -> None:
    lst: ObservableList[int] = ObservableList()
    completed: list[bool] = []
    lst.on_reset.subscribe(on_completed=lambda: completed.append(True))

    lst.dispose()
    assert completed == [True]
    lst.dispose()  # idempotent


def test_vmx_096_observable_dictionary_dispose_completes_subjects() -> None:
    d: ObservableDictionary[str, int, str] = ObservableDictionary()
    completed: list[bool] = []
    d.on_reset.subscribe(on_completed=lambda: completed.append(True))
    keys_completed: list[bool] = []
    d.keys1.on_reset.subscribe(on_completed=lambda: keys_completed.append(True))

    d.dispose()
    assert completed == [True]
    assert keys_completed == [True]  # key-axis views are disposed too
    d.dispose()  # idempotent
