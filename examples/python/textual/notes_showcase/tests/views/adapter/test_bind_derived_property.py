"""Unit tests for :func:`notes_showcase.views.adapter.bind_derived_property`
and :func:`on_derived_change` (Phase 5.b binding-gap #3).
"""

from __future__ import annotations

from textual.widgets import Static

from reactivex.subject import BehaviorSubject

from vmx import from_sources

from notes_showcase.views.adapter import bind_derived_property, on_derived_change


def test_bind_derived_property_seeds_widget_from_current_value() -> None:
    src: BehaviorSubject[str] = BehaviorSubject("hello")
    derived = from_sources(src, transform=lambda v: f"<{v}>")
    widget = Static()

    sub = bind_derived_property(widget, "renderable", derived)
    try:
        assert str(widget.renderable) == "<hello>"
    finally:
        sub.dispose()
        derived.dispose()
        src.on_completed()
        src.dispose()


def test_bind_derived_property_updates_widget_on_value_change() -> None:
    src: BehaviorSubject[int] = BehaviorSubject(1)
    derived = from_sources(src, transform=lambda v: v * 10)
    widget = Static()

    sub = bind_derived_property(widget, "renderable", derived)
    try:
        assert str(widget.renderable) == "10"
        src.on_next(5)
        assert str(widget.renderable) == "50"
        src.on_next(7)
        assert str(widget.renderable) == "70"
    finally:
        sub.dispose()
        derived.dispose()
        src.on_completed()
        src.dispose()


def test_on_derived_change_fires_callback_immediately_and_on_change() -> None:
    src: BehaviorSubject[str] = BehaviorSubject("a")
    derived = from_sources(src, transform=lambda v: v.upper())
    captured: list[str] = []

    sub = on_derived_change(derived, lambda v: captured.append(v))
    try:
        # Immediate seed call.
        assert captured == ["A"]
        src.on_next("b")
        assert captured == ["A", "B"]
        src.on_next("c")
        assert captured == ["A", "B", "C"]
    finally:
        sub.dispose()
        derived.dispose()
        src.on_completed()
        src.dispose()


def test_bind_derived_property_does_not_raise_when_no_value_yet() -> None:
    """A DerivedProperty fed by a plain ``Subject`` (no replay) has no value
    at bind time. The bridge must swallow ``RuntimeError`` and leave the
    widget attribute at its construction default; later changes propagate
    once the second emission arrives (the first is consumed by the property
    itself per spec ch. 15).
    """
    from reactivex.subject import Subject

    src: Subject[str] = Subject()
    derived = from_sources(src, transform=lambda v: f"!{v}!")

    class _Stub:
        text: str = "placeholder"

    widget = _Stub()
    sub = bind_derived_property(widget, "text", derived)
    try:
        # No source emission → widget attr left at construction default.
        assert widget.text == "placeholder"
        # Per spec ch. 15: first emission populates ``value`` silently; no
        # ``value_changed`` tick. Second emission produces a real change.
        src.on_next("first")
        src.on_next("second")
        assert widget.text == "!second!"
    finally:
        sub.dispose()
        derived.dispose()
        src.on_completed()
        src.dispose()
