"""Bindings between VMx view-models and NiceGUI elements.

Each function must be called inside a page builder, where NiceGUI's client and
loop are current. It reads the VM once to seed the element, then applies every
later change through :class:`ClientDelivery`, so a change made on a worker
thread is applied on the loop, inside the page that owns the element.

Every function returns a disposable. Pass them to :func:`release_on_delete`,
which disposes them when NiceGUI deletes the page's client. It does not use
``client.on_disconnect``: since NiceGUI 3.0 that also fires when a browser
reconnects, and the page would lose its bindings on a brief network drop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from typing import Any, cast

import reactivex as rx
import reactivex.operators as ops
from nicegui import ui
from nicegui.element import Element
from nicegui.elements.mixins.value_element import ValueElement
from nicegui.events import ValueChangeEventArguments
from nicegui.functions.refreshable import refreshable
from reactivex.abc import DisposableBase
from reactivex.disposable import CompositeDisposable, Disposable
from vmx import Message, MessageHub, PropertyChangedMessage
from vmx.commands.protocols import Command
from vmx.properties.derived import DerivedProperty

from nicegui_notes.adapter.delivery import ClientDelivery

_log = logging.getLogger(__name__)


def _hub(vm: Any) -> MessageHub[Message]:
    hub = getattr(vm, "hub", None) or getattr(vm, "_hub", None)
    if hub is None:
        raise AttributeError(f"{vm!r} exposes no message hub to bind to")
    return cast(MessageHub[Message], hub)


def vm_property_changes(vm: Any, names: Collection[str]) -> rx.Observable[str]:
    """The names of ``vm``'s properties in ``names`` as they change on its hub."""
    wanted = set(names)
    return _hub(vm).messages.pipe(
        ops.filter(
            lambda message: (
                isinstance(message, PropertyChangedMessage)
                and message.sender is vm
                and message.property_name in wanted
            )
        ),
        ops.map(lambda message: cast(PropertyChangedMessage[Any], message).property_name),
    )


# docs-snippet:start nicegui-bind-property
def bind_property(
    element: Element,
    attr: str,
    vm: Any,
    vm_property: str,
    transform: Callable[[Any], object] | None = None,
) -> DisposableBase:
    """One-way: ``vm.<vm_property>`` → ``element.<attr>``, optionally transformed."""
    delivery = ClientDelivery()

    def _show() -> None:
        value = getattr(vm, vm_property)
        setattr(element, attr, transform(value) if transform is not None else value)

    _show()
    return vm_property_changes(vm, {vm_property}).subscribe(on_next=lambda _: delivery.run(_show))
    # docs-snippet:end nicegui-bind-property


def bind_property_two_way(
    element: ValueElement[Any],
    vm: Any,
    vm_property: str,
    parse: Callable[[Any], Any] | None = None,
) -> DisposableBase:
    """Two-way: ``element.value`` ↔ ``vm.<vm_property>``, without echoing either way.

    ``parse`` maps the element's value before it reaches the VM. A cleared
    ``ui.input`` reports ``None``; :func:`text` turns that into ``""``.
    """
    delivery = ClientDelivery()
    state = {"syncing": False, "active": True}
    element.value = getattr(vm, vm_property)

    def _from_element(event: ValueChangeEventArguments[Any]) -> None:
        if state["syncing"] or not state["active"]:
            return
        value = parse(event.value) if parse is not None else event.value
        if getattr(vm, vm_property) != value:
            setattr(vm, vm_property, value)

    def _to_element() -> None:
        value = getattr(vm, vm_property)
        if element.value == value:
            return
        state["syncing"] = True
        try:
            element.value = value
        finally:
            state["syncing"] = False

    def _deactivate() -> None:
        state["active"] = False

    element.on_value_change(_from_element)
    changes = vm_property_changes(vm, {vm_property}).subscribe(
        on_next=lambda _: delivery.run(_to_element)
    )
    return CompositeDisposable(changes, Disposable(_deactivate))


def bind_derived_property(
    element: Element,
    attr: str,
    derived: DerivedProperty[Any],
    transform: Callable[[Any], object] | None = None,
) -> DisposableBase:
    """One-way: a :class:`DerivedProperty`'s value → ``element.<attr>``.

    A property whose source has not emitted has no value yet, so the element
    stays unset. Its first value arrives without a ``value_changed`` emission,
    so the element shows the next change after it (#364).
    """
    delivery = ClientDelivery()

    def _show() -> None:
        try:
            value = derived.value
        except RuntimeError:
            return  # no first value yet
        setattr(element, attr, transform(value) if transform is not None else value)

    _show()
    return derived.value_changed.subscribe(on_next=lambda _: delivery.run(_show))


def bind_command(button: ui.button, command: Command) -> DisposableBase:
    """``button`` runs ``command``; its enabled state follows ``command.can_execute()``.

    A command with an ``errors`` channel, such as ``AsyncRelayCommand``, reports a
    fire-and-forget failure there instead of to the caller. The binding logs each
    failure and shows it in a negative notification on the page.
    """
    delivery = ClientDelivery()
    state = {"active": True}

    def _sync_enabled() -> None:
        button.set_enabled(command.can_execute())

    def _click() -> None:
        if state["active"] and command.can_execute():
            command.execute()

    def _deactivate() -> None:
        state["active"] = False

    def _report(error: BaseException) -> None:
        _log.error("command failed", exc_info=error)
        delivery.run(lambda: ui.notify(f"Command failed: {error}", type="negative"))

    _sync_enabled()
    button.on_click(_click)
    changes = command.can_execute_changed.subscribe(on_next=lambda _: delivery.run(_sync_enabled))
    disposables = [changes, Disposable(_deactivate)]
    errors: rx.Observable[BaseException] | None = getattr(command, "errors", None)
    if errors is not None:
        disposables.append(errors.subscribe(on_next=_report))
    return CompositeDisposable(*disposables)


def bind_refreshable(render: refreshable[..., Any], changes: rx.Observable[Any]) -> DisposableBase:
    """Re-run a page-local ``@ui.refreshable`` builder whenever ``changes`` emits.

    Define ``render`` inside the page builder, so refreshing it rebuilds only
    this page's copy.
    """
    delivery = ClientDelivery()

    def _refresh() -> None:
        render.refresh()

    return changes.subscribe(on_next=lambda _: delivery.run(_refresh))


def text(value: object) -> str:
    """Parse a text element's value: a cleared input reports ``None``."""
    return "" if value is None else str(value)


# docs-snippet:start nicegui-release
def release_on_delete(*disposables: DisposableBase) -> DisposableBase:
    """Dispose ``disposables`` when NiceGUI deletes the current page's client.

    Returns them as one idempotent disposable, so a host can also release the
    page earlier, for example at shutdown.
    """
    page = CompositeDisposable(*disposables)
    ui.context.client.on_delete(page.dispose)
    return page
    # docs-snippet:end nicegui-release
