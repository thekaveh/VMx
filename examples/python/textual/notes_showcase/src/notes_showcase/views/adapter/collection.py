"""CollectionBridge — VMx :class:`CompositeVM` → Textual :class:`ListView`.

See scenario §7.1 (CollectionBridge) and plan §4.b.

Phase 3.b's ``NotesViewVM`` does not subclass ``CompositeVM`` directly (the
VMx ``PagedComposition`` is a read-only decorator). Real list-pane bindings in
Phase 5.b will therefore target the inner ``CompositeVM`` slots — e.g.
``NotebooksRootVM`` already exposes the canonical composite shape. This
bridge accepts any object that

* is iterable (``for child in vm_collection``),
* exposes a ``current`` property setter, and
* exposes ``on_collection_changed`` as an ``rx.Observable``.

That matches :class:`vmx.composites.composite_vm._CompositeVMBase` exactly.

The bridge applies incremental Add/Remove operations where possible (Textual's
``ListView`` supports ``append`` and ``pop``); on ``reset`` (or any event
shape the bridge doesn't recognise — e.g. WPF-style ``move``) it rebuilds.

Selection is two-way:

* ``vm_collection.current`` change → ``list_view.index``.
* ``list_view.index`` change → ``vm_collection.current``.

The widget→VM direction is wired through a Textual ``watch_index`` override,
which keeps the bridge framework-idiomatic. (See ``property.bind_property_two_way``
for the same pattern at the property level.)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from reactivex.abc import DisposableBase
from reactivex.disposable import CompositeDisposable

from vmx.collections.collection_changed import CollectionChangedEvent
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.tree_structure_changed import TreeStructureChangedMessage

from notes_showcase.views.adapter._hub_accessor import resolve_hub
from notes_showcase.views.adapter.property import _invoke_class_watcher


def bind_collection(
    list_view: Any,
    vm_collection: Any,
    factory: Callable[[Any], Any],
) -> DisposableBase:
    """Bind ``list_view`` rows to ``vm_collection`` children via ``factory``.

    Parameters
    ----------
    list_view:
        Textual :class:`~textual.widgets.ListView` (or any object exposing
        ``clear()``, ``append(item)``, ``pop(index)``, and a writable ``index``
        attribute).
    vm_collection:
        A VMx composite (anything iterable that exposes ``on_collection_changed``
        as an ``rx.Observable[CollectionChangedEvent]`` and a writable ``current``
        slot, e.g. :class:`vmx.composites.CompositeVM`).
    factory:
        Maps a child VM to the corresponding ``ListItem`` (or other widget).

    Returns a composite disposable holding the collection-changed subscription
    and (if available) the hub subscription that mirrors ``current``.
    """
    # Initial population.
    _rebuild(list_view, vm_collection, factory)

    subscriptions = CompositeDisposable()

    def _on_event(event: object) -> None:
        if not isinstance(event, CollectionChangedEvent):
            return
        if (
            event.action == "add"
            and len(event.new_items) == 1
            and event.new_index == len(list_view.children)
        ):
            # Tail insert only — ListView.append cannot honor a mid-list
            # position, so any other insertion index rebuilds (an
            # unconditional append rendered mid-list inserts at the wrong
            # row; real-wiring audit, pass 5).
            list_view.append(factory(event.new_items[0]))
        elif event.action == "remove" and event.old_index >= 0:
            list_view.pop(event.old_index)
        else:
            _rebuild(list_view, vm_collection, factory)

    subscriptions.add(vm_collection.on_collection_changed.subscribe(on_next=_on_event))

    # VM→widget selection: mirror "current" via the hub.
    def _on_message(message: object) -> None:
        if not isinstance(message, PropertyChangedMessage):
            return
        if message.sender is not vm_collection:
            return
        if message.property_name != "current":
            return
        list_view.index = _index_of_current(vm_collection)

    subscriptions.add(
        resolve_hub(vm_collection).messages.subscribe(on_next=_on_message)
    )

    # Seed list_view.index from the VM (None → -1 / first row blank).
    list_view.index = _index_of_current(vm_collection)

    # Widget→VM selection via Textual reactive watcher, chaining the class
    # watcher (ListView.watch_index drives row highlighting — an instance
    # override must not shadow it; real-wiring audit, pass 5).
    cls_watcher = getattr(type(list_view), "watch_index", None)

    def _watch_index(_old: object, new: int | None) -> None:
        if cls_watcher is not None:
            _invoke_class_watcher(cls_watcher, list_view, _old, new)
        target: Any | None = None
        if new is not None and new >= 0:
            children = list(vm_collection)
            if 0 <= new < len(children):
                target = children[new]
        if vm_collection.current is target:
            return
        vm_collection.current = target

    list_view.watch_index = _watch_index

    return subscriptions


def _rebuild(list_view: Any, vm_collection: Any, factory: Callable[[Any], Any]) -> None:
    list_view.clear()
    for child in vm_collection:
        list_view.append(factory(child))


def _index_of_current(vm_collection: Any) -> int | None:
    current = vm_collection.current
    if current is None:
        return None
    for i, child in enumerate(vm_collection):
        if child is current:
            return i
    return None


def on_tree_structure_changed(vm: Any, callback: Callable[[], None]) -> DisposableBase:
    """Invoke ``callback()`` whenever *vm* publishes a
    :class:`~vmx.TreeStructureChangedMessage` on its hub.

    Lets a tree view repopulate on structural changes (notebook add/remove)
    without subscribing to the hub itself — the "no hub subscriptions in
    views" contract check stays green.
    """

    def _on_message(message: object) -> None:
        if isinstance(message, TreeStructureChangedMessage) and message.sender is vm:
            callback()

    return resolve_hub(vm).messages.subscribe(on_next=_on_message)


def bind_observable_list(
    list_view: Any,
    observable_list: Any,
    factory: Callable[[Any], Any],
) -> DisposableBase:
    """Bind a :class:`vmx.ObservableList` ``[T]`` → Textual ``ListView`` rows.

    Companion to :func:`bind_collection` for collections that do not implement
    the :class:`CompositeVM` shape (no ``current`` slot, no
    ``on_collection_changed`` channel). The bridge subscribes to the four
    granular event observables published by ``ObservableList``:
    ``on_item_added`` / ``on_item_removed`` / ``on_item_replaced`` /
    ``on_reset``, and applies the corresponding mutation to the widget.

    Used by ``NotesViewVM.inner`` (centre pane note list — Phase 5.b).
    """
    # Initial seed.
    list_view.clear()
    for item in observable_list:
        list_view.append(factory(item))

    subs = CompositeDisposable()
    subs.add(
        observable_list.on_item_added.subscribe(
            on_next=lambda evt: list_view.append(factory(evt[0]))
        )
    )
    subs.add(
        observable_list.on_item_removed.subscribe(
            on_next=lambda evt: list_view.pop(evt[1])
        )
    )

    def _rebuild_full(_: object = None) -> None:
        list_view.clear()
        for item in observable_list:
            list_view.append(factory(item))

    subs.add(observable_list.on_item_replaced.subscribe(on_next=_rebuild_full))
    subs.add(observable_list.on_reset.subscribe(on_next=_rebuild_full))
    return subs
