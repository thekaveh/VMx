"""HIER-015..HIER-017 conformance tests — HierarchicalVMBuilder.

Per spec/12-conformance.md §HIER and ADR-0035 §2 H1 / H2 / H3.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.builders.exceptions import BuilderValidationError
from vmx.hierarchical import HierarchicalVM, HierarchicalVMBuilder
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


def _hub() -> MessageHub[Any]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


# ---------------------------------------------------------------------------
# HIER-015 — Build() validates required fields
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-015")
def test_HIER_015_missing_model_raises() -> None:
    h = _hub()
    d = _dispatcher()
    with pytest.raises(BuilderValidationError) as exc_info:
        (
            HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
            .children_factory(lambda _parent: [])
            .services(h, d)
            .build()
        )
    assert exc_info.value.missing_field == "model"


@pytest.mark.conformance("HIER-015")
def test_HIER_015_missing_children_factory_raises() -> None:
    h = _hub()
    d = _dispatcher()
    with pytest.raises(BuilderValidationError) as exc_info:
        (
            HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
            .model("root")
            .services(h, d)
            .build()
        )
    assert exc_info.value.missing_field == "children_factory"


@pytest.mark.conformance("HIER-015")
def test_HIER_015_missing_services_raises() -> None:
    with pytest.raises(BuilderValidationError) as exc_info:
        (
            HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
            .model("root")
            .children_factory(lambda _parent: [])
            .build()
        )
    # missing_field will be either "hub" or "dispatcher"
    assert exc_info.value.missing_field in {"hub", "dispatcher"}


# ---------------------------------------------------------------------------
# HIER-016 — Repeated identical Build() calls
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-016")
def test_HIER_016_repeated_build_produces_distinct_equivalent_nodes() -> None:
    h = _hub()
    d = _dispatcher()
    b = (
        HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
        .model("root")
        .children_factory(lambda _parent: [])
        .services(h, d)
        .hint("h")
        .eager_children(True)
    )
    n1 = b.build()
    n2 = b.build()
    assert n1 is not n2
    assert n1.model == n2.model == "root"
    assert n1.hint == n2.hint == "h"


# ---------------------------------------------------------------------------
# HIER-017 — Field defaults applied when not set
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-017")
def test_HIER_017_defaults_applied_when_not_set() -> None:
    h = _hub()
    d = _dispatcher()
    node = (
        HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
        .model("root")
        .children_factory(lambda _parent: [])
        .services(h, d)
        .build()
    )
    assert node.hint == ""
    assert node.name == HierarchicalVM.__name__  # default to class name
    # eager_children defaults to False: children are not materialized at build time
    assert node._children_list is None  # pragma: no cover — private check


# ---------------------------------------------------------------------------
# H2 — with_default_services Wither
# ---------------------------------------------------------------------------


def test_with_default_services_wires_defaults() -> None:
    """ADR-0035 §2 H2: chainable Wither that explicitly opts in to default
    hub + dispatcher wiring (makes the implicit-default behavior of Python /
    TS HierarchicalVM visible at the call site).
    """
    node = (
        HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
        .model("root")
        .children_factory(lambda _parent: [])
        .with_default_services()
        .build()
    )
    assert node.model == "root"
    # Default services should be a real (non-null) hub + dispatcher.
    assert node._hub is not None
    assert node._dispatcher is not None


def test_with_default_services_returns_new_builder_instance() -> None:
    """``with_default_services()`` adheres to BLD-001: returns a new builder
    instance rather than mutating the original."""
    b1 = (
        HierarchicalVMBuilder[str, HierarchicalVM[str, Any]]()
        .model("root")
        .children_factory(lambda _parent: [])
    )
    b2 = b1.with_default_services()
    assert b1 is not b2
    # b1 still has no services wired — building it raises
    with pytest.raises(BuilderValidationError):
        b1.build()
    # b2 builds fine
    n = b2.build()
    assert n.model == "root"
