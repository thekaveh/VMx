"""PropertyBridge — VMx ``PropertyChangedMessage`` → Textual widget attribute.

See scenario §7.1 (PropertyBridge) and plan §4.b.

A single hub subscription (per call) feeds one widget attribute. The bridge
filters on ``isinstance(message, PropertyChangedMessage)`` *and* identity of
``message.sender`` so cross-VM updates published to the same hub do not leak
into unrelated widgets. The widget's attribute is seeded with the current VM
value *before* subscribing — that mirrors INPC's "initial render" guarantee
and means callers do not need a separate read after binding.

``bind_derived_property`` is the companion bridge for :class:`DerivedProperty`
values (Phase 5.b binding gap #3). ``DerivedProperty`` does **not** publish
``PropertyChangedMessage`` on its owner's hub — it exposes its own
``value_changed`` observable. The status-bar reads (``note_count_text``,
``editing_text``, …) and ``NoteFormVM.is_dirty`` / ``is_valid`` are all
``DerivedProperty`` instances, so the view-layer subscribes here instead.
"""

from __future__ import annotations

from typing import Any

from reactivex.abc import DisposableBase

from vmx.messages.property_changed import PropertyChangedMessage
from vmx.properties.derived import DerivedProperty

from notes_showcase.views.adapter._hub_accessor import resolve_hub


def bind_property(
    widget: Any,
    attr: str,
    vm: Any,
    vm_property: str,
) -> DisposableBase:
    """One-way bind ``vm.<vm_property>`` → ``widget.<attr>``.

    Seeds ``widget.attr`` from the VM, then subscribes to the VM's hub. On
    each ``PropertyChangedMessage`` whose ``sender`` is ``vm`` and whose
    ``property_name`` equals ``vm_property``, re-reads the VM and assigns the
    fresh value to the widget.

    Returns the subscription (a :class:`reactivex.abc.DisposableBase`). Call
    ``dispose()`` to unbind.
    """
    setattr(widget, attr, getattr(vm, vm_property))

    def _on_next(message: object) -> None:
        if not isinstance(message, PropertyChangedMessage):
            return
        if message.sender is not vm:
            return
        if message.property_name != vm_property:
            return
        setattr(widget, attr, getattr(vm, vm_property))

    subscription = resolve_hub(vm).messages.subscribe(on_next=_on_next)
    return subscription


def bind_property_two_way(
    widget: Any,
    widget_attr: str,
    vm: Any,
    vm_property: str,
) -> DisposableBase:
    """Two-way bind ``widget.<widget_attr>`` ↔ ``vm.<vm_property>``.

    Establishes the VM→widget direction via :func:`bind_property`. The
    widget→VM direction is wired by installing a Textual ``watch_<attr>``
    method on ``widget`` (Textual's reactive-watcher convention; see Textual
    ≥0.80 reactive docs) that writes back to the VM. The watcher short-circuits
    when the new value already equals the VM's current value so the
    forward-bind that fires on every VM update doesn't cause a ping-pong.

    Two-way binding only makes sense for widget attributes backed by Textual's
    ``reactive`` descriptor (otherwise no ``watch_*`` hook is called).
    """
    disposable = bind_property(widget, widget_attr, vm, vm_property)

    def _watcher(_old: object, new: object) -> None:
        if getattr(vm, vm_property) == new:
            return
        setattr(vm, vm_property, new)

    setattr(widget, f"watch_{widget_attr}", _watcher)
    return disposable


def bind_derived_property(
    widget: Any,
    attr: str,
    derived: DerivedProperty[Any],
) -> DisposableBase:
    """One-way bind a :class:`DerivedProperty` → ``widget.<attr>``.

    ``DerivedProperty`` lives outside the hub message graph: it owns its own
    ``value_changed`` :class:`reactivex.Observable` and never publishes
    ``PropertyChangedMessage``. This bridge subscribes there directly.

    Seeds ``widget.attr`` from ``derived.value`` (when the derived has emitted
    at least once — otherwise leaves the widget attribute untouched, mirroring
    the spec ch. 15 "no value yet" semantics).
    """
    try:
        setattr(widget, attr, derived.value)
    except RuntimeError:
        # Derived has not received a first emission yet — that's fine; the
        # subscription below will seed on the next tick.
        pass

    def _on_next(value: object) -> None:
        setattr(widget, attr, value)

    return derived.value_changed.subscribe(on_next=_on_next)


def on_derived_change(
    derived: DerivedProperty[Any],
    callback: Any,
) -> DisposableBase:
    """Subscribe a free-form ``callback(value)`` to a :class:`DerivedProperty`.

    Used when a widget needs to *react* to a derived change with more than a
    simple ``setattr`` — e.g. rebuilding child widgets from a derived list.
    The widget delegates here rather than touching the hub directly so the
    Phase 6 "no hub subscriptions in widgets" grep stays green.

    Fires once eagerly with the current ``derived.value`` (if seeded) so the
    caller does not need a separate ``callback(derived.value)`` after binding.
    """
    try:
        callback(derived.value)
    except RuntimeError:
        pass

    return derived.value_changed.subscribe(on_next=callback)
