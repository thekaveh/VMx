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

import inspect
import weakref
from collections.abc import Callable
from typing import Any

from reactivex.abc import DisposableBase
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.properties.derived import DerivedProperty

from notes_showcase.views.adapter._hub_accessor import resolve_hub


def _assign(widget: Any, attr: str, value: object) -> None:
    """Assign *value* to ``widget.<attr>``, routing rendered-content targets
    through the widget's ``update()``.

    ``attr == "renderable"`` is the adapter's conventional name for "the
    widget's rendered content". Textual's ``Static`` (8.x) has no
    ``renderable`` attribute — a plain ``setattr`` would create a dead
    instance attribute and the widget would never repaint. ``Static.update()``
    is the supported repaint API, so route through it whenever the target
    exposes one.
    """
    if attr == "renderable" and callable(getattr(widget, "update", None)):
        widget.update(value if isinstance(value, str) else str(value))
        return
    setattr(widget, attr, value)


def _invoke_class_watcher(
    watcher: Callable[..., None], widget: Any, old: object, new: object
) -> None:
    """Call a Textual class-level ``watch_*`` method with its declared arity.

    Textual watchers may declare ``(self)``, ``(self, new)``, or
    ``(self, old, new)``; mirror Textual's flexible-arity dispatch so an
    instance-level override can chain to the original behaviour (e.g.
    ``ToggleButton.watch_value`` toggling the ``-on`` class).
    """
    params = [
        p
        for p in inspect.signature(watcher).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    arity = len(params) - 1  # exclude self
    if arity <= 0:
        watcher(widget)
    elif arity == 1:
        watcher(widget, new)
    else:
        watcher(widget, old, new)


def bind_property(
    widget: Any,
    attr: str,
    vm: Any,
    vm_property: str,
    transform: Callable[[Any], object] | None = None,
) -> DisposableBase:
    """One-way bind ``vm.<vm_property>`` → ``widget.<attr>``.

    Seeds ``widget.attr`` from the VM, then subscribes to the VM's hub. On
    each ``PropertyChangedMessage`` whose ``sender`` is ``vm`` and whose
    ``property_name`` equals ``vm_property``, re-reads the VM and assigns the
    fresh value to the widget. An optional *transform* maps the VM value to
    the widget value (e.g. an ``ObservableList`` → a display string).

    Returns the subscription (a :class:`reactivex.abc.DisposableBase`). Call
    ``dispose()`` to unbind.
    """

    def _read() -> object:
        value = getattr(vm, vm_property)
        return transform(value) if transform is not None else value

    _assign(widget, attr, _read())

    def _on_next(message: object) -> None:
        if not isinstance(message, PropertyChangedMessage):
            return
        if message.sender is not vm:
            return
        if message.property_name != vm_property:
            return
        _assign(widget, attr, _read())

    subscription = resolve_hub(vm).messages.subscribe(on_next=_on_next)
    return subscription


def on_vm_property_change(
    vm: Any,
    property_names: str | set[str],
    callback: Callable[[str | None], None],
) -> DisposableBase:
    """Invoke ``callback(property_name)`` on hub ``PropertyChangedMessage``
    events from *vm* whose name is in *property_names*.

    The free-form companion to :func:`bind_property` for views that must
    *react* (e.g. rebuild list rows) rather than assign a single attribute.
    Fires once eagerly with ``None`` so callers don't need a separate initial
    render. Widgets delegate here rather than touching the hub directly so
    the "no hub subscriptions in views" contract check stays green.
    """
    names = {property_names} if isinstance(property_names, str) else property_names
    callback(None)

    def _on_next(message: object) -> None:
        if not isinstance(message, PropertyChangedMessage):
            return
        if message.sender is not vm:
            return
        if message.property_name not in names:
            return
        callback(message.property_name)

    return resolve_hub(vm).messages.subscribe(on_next=_on_next)


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
    ``reactive`` descriptor (otherwise no ``watch_*`` hook is called). For
    ``TextArea.text``, use :func:`bind_text_area` and
    :func:`push_text_area_text`.
    """
    disposable = bind_property(widget, widget_attr, vm, vm_property)

    # Chain the class-level watcher (if any): an instance-level override
    # otherwise *shadows* it — e.g. ToggleButton.watch_value applies the
    # "-on" CSS class, so swallowing it froze every Checkbox glyph
    # (runtime behavior).
    cls_watcher = getattr(type(widget), f"watch_{widget_attr}", None)

    def _watcher(_old: object, new: object) -> None:
        if cls_watcher is not None:
            _invoke_class_watcher(cls_watcher, widget, _old, new)
        if getattr(vm, vm_property) == new:
            return
        setattr(vm, vm_property, new)

    setattr(widget, f"watch_{widget_attr}", _watcher)
    return disposable


# For each editor, a VM value and the editor text that stands for it.
# ``bind_text_area`` records the pair after each load. ``TextArea`` rebuilds the
# text with one newline style, so the two can differ. When the editor already
# shows a new VM value, the pair holds that value twice.
_loaded_text: weakref.WeakKeyDictionary[Any, tuple[str, str]] = weakref.WeakKeyDictionary()


def bind_text_area(
    text_area: Any,
    vm: Any,
    vm_property: str,
    *,
    identity: Callable[[], object] | None = None,
) -> DisposableBase:
    """Bind ``vm.<vm_property>`` → ``text_area.text`` for a Textual ``TextArea``.

    ``TextArea.text`` is a plain property, not a ``reactive``, so Textual
    never calls the ``watch_text`` hook of :func:`bind_property_two_way`.
    This function is the VM→widget half of the binding. For the widget→VM
    half, the view calls :func:`push_text_area_text` from its
    ``on_text_area_changed`` handler.

    Each ``text`` assignment calls ``TextArea.load_text``. That call moves
    the cursor to the start and clears the undo history. So the bridge keeps
    the last VM value that it saw. It loads the text only when the VM value
    is different from that value. A typed key can be in the widget while its
    ``Changed`` message is still queued. A broadcast of an unchanged VM value
    then does not drop that key.

    ``identity`` returns a key for the record that the editor shows, for
    example a note id. When the key changes, the bridge loads the text even
    if it is equal. This clears the undo history of the previous record.
    """
    synced: str | None = None
    synced_identity: object = None

    def _load(text: str, *, force: bool) -> None:
        loaded = _loaded_text.get(text_area)
        if force:
            text_area.load_text(text)
        elif text_area.text == text:
            if loaded is not None and loaded[1] == text:
                # Another writer set the rendition itself. A later push must
                # keep that text, not map it to an older loaded value.
                _loaded_text[text_area] = (text, text)
            return
        elif loaded == (text, text_area.text):
            # The editor already shows its rendition of this value, for
            # example after an undo. A reload would move the cursor.
            return
        else:
            text_area.text = text
        _loaded_text[text_area] = (text, text_area.text)

    def _sync(_name: str | None) -> None:
        nonlocal synced, synced_identity
        text = str(getattr(vm, vm_property))
        current = identity() if identity is not None else None
        if synced is not None and current != synced_identity:
            synced, synced_identity = text, current
            _load(text, force=True)
            return
        if text == synced:
            return
        synced, synced_identity = text, current
        _load(text, force=False)

    return on_vm_property_change(vm, vm_property, _sync)


def push_text_area_text(text_area: Any, vm: Any, vm_property: str) -> None:
    """Write ``text_area.text`` to ``vm.<vm_property>`` when they are different.

    Call this from the view's ``on_text_area_changed`` handler. The function
    reads the text when the message arrives, not when Textual sent it. For
    this reason, the ``Changed`` message of an earlier VM value cannot write
    that value back over a later one.

    The editor can show its own rendition of the VM value that
    :func:`bind_text_area` recorded, for example with other line endings. That
    rendition is not an edit. When the editor shows it, after the load or after
    an undo, the function writes the recorded value instead.
    """
    text = text_area.text
    loaded = _loaded_text.get(text_area)
    if loaded is not None and text == loaded[1]:
        text = loaded[0]
    if getattr(vm, vm_property) != text:
        setattr(vm, vm_property, text)


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
        _assign(widget, attr, derived.value)
    except RuntimeError:
        # Derived has no first value yet. Its first value arrives without a
        # value_changed emission, so a first value emitted after binding is not
        # shown; the widget shows the next change after it
        # (https://github.com/thekaveh/VMx/issues/364).
        pass

    def _on_next(value: object) -> None:
        _assign(widget, attr, value)

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
        # No first value yet; a first value emitted after binding is not
        # delivered (https://github.com/thekaveh/VMx/issues/364).
        pass

    return derived.value_changed.subscribe(on_next=callback)
