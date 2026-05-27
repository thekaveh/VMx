"""Conformance tests: CAP-001..020 — capability micro-interfaces.

Per spec/14-capabilities.md and ADR-0010, each test uses a fixture class
implementing the capability and verifies the per-interface semantic contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx import (
    ComponentVMBuilder,
    MessageHub,
    RxDispatcher,
)
from vmx.capabilities import (
    IApprovable,
    ICancelable,
    IClosable,
    ICollapsible,
    IConstructable,
    ICurrentDeletable,
    ICurrentUpdatable,
    IDeletable,
    IDeselectable,
    IDestructable,
    IExpandable,
    IExpansionTogglable,
    IManagable,
    INewCreatable,
    IReconstructable,
    ISavable,
    ISearchable,
    ISelectable,
    ISelectionTogglable,
    IUpdatable,
)


def _bare_component_vm() -> Any:
    return (
        ComponentVMBuilder().name("bare").services(MessageHub(), RxDispatcher.immediate()).build()
    )


# ---------------------------------------------------------------------------
# CAP-001 — ISelectable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-001")
def test_CAP_001_iselectable_contract() -> None:
    class F(ISelectable):
        def __init__(self) -> None:
            self.calls = 0

        def can_select(self) -> bool:
            return True

        def select(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_select() is True
    f.select()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-002 — IDeselectable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-002")
def test_CAP_002_ideselectable_contract() -> None:
    class F(IDeselectable):
        def __init__(self) -> None:
            self.calls = 0

        def can_deselect(self) -> bool:
            return True

        def deselect(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_deselect() is True
    f.deselect()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-003 — ISelectionTogglable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-003")
def test_CAP_003_iselectiontogglable_contract() -> None:
    class F(ISelectionTogglable):
        def __init__(self) -> None:
            self.selected = False

        def can_toggle_selection(self) -> bool:
            return True

        def toggle_selection(self) -> None:
            self.selected = not self.selected

    f = F()
    initial = f.selected
    assert f.can_toggle_selection() is True
    f.toggle_selection()
    f.toggle_selection()
    assert f.selected == initial


# ---------------------------------------------------------------------------
# CAP-004 — IExpandable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-004")
def test_CAP_004_iexpandable_contract() -> None:
    class F(IExpandable):
        def __init__(self) -> None:
            self._expanded = False

        @property
        def is_expanded(self) -> bool:
            return self._expanded

        def can_expand(self) -> bool:
            return True

        def expand(self) -> None:
            self._expanded = True

    f = F()
    assert f.is_expanded is False
    assert f.can_expand() is True
    f.expand()
    assert f.is_expanded is True


# ---------------------------------------------------------------------------
# CAP-005 — ICollapsible
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-005")
def test_CAP_005_icollapsible_contract() -> None:
    class F(ICollapsible):
        def __init__(self) -> None:
            self.calls = 0

        def can_collapse(self) -> bool:
            return True

        def collapse(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_collapse() is True
    f.collapse()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-006 — IExpansionTogglable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-006")
def test_CAP_006_iexpansiontogglable_contract() -> None:
    class F(IExpansionTogglable):
        def __init__(self) -> None:
            self.expanded = False

        def can_toggle_expansion(self) -> bool:
            return True

        def toggle_expansion(self) -> None:
            self.expanded = not self.expanded

    f = F()
    initial = f.expanded
    assert f.can_toggle_expansion() is True
    f.toggle_expansion()
    f.toggle_expansion()
    assert f.expanded == initial


# ---------------------------------------------------------------------------
# CAP-007 — IClosable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-007")
def test_CAP_007_iclosable_contract() -> None:
    class F(IClosable):
        def __init__(self) -> None:
            self.calls = 0

        def can_close(self) -> bool:
            return True

        def close(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_close() is True
    f.close()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-008 — ISearchable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-008")
def test_CAP_008_isearchable_contract() -> None:
    class F(ISearchable):
        def __init__(self) -> None:
            self._term = ""
            self.searched: list[str] = []

        @property
        def search_term(self) -> str:
            return self._term

        @search_term.setter
        def search_term(self, value: str) -> None:
            self._term = value

        def can_search(self) -> bool:
            return True

        def search(self) -> None:
            self.searched.append(self._term)

    f = F()
    f.search_term = "abc"
    assert f.can_search() is True
    f.search()
    assert f.search_term == "abc"
    assert f.searched == ["abc"]


# ---------------------------------------------------------------------------
# CAP-009 — IApprovable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-009")
def test_CAP_009_iapprovable_contract() -> None:
    class F(IApprovable):
        def __init__(self) -> None:
            self.calls = 0

        def can_approve(self) -> bool:
            return True

        def approve(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_approve() is True
    f.approve()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-010 — ICancelable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-010")
def test_CAP_010_icancelable_contract() -> None:
    class F(ICancelable):
        def __init__(self) -> None:
            self.calls = 0

        def can_cancel(self) -> bool:
            return True

        def cancel(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_cancel() is True
    f.cancel()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-011 — ISavable<T>
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-011")
def test_CAP_011_isavable_contract() -> None:
    class F(ISavable[str]):
        def __init__(self) -> None:
            self.saved: list[str] = []

        def can_save(self, item: str) -> bool:
            return True

        def save(self, item: str) -> None:
            self.saved.append(item)

    f = F()
    assert f.can_save("a") is True
    f.save("a")
    assert f.saved == ["a"]


# ---------------------------------------------------------------------------
# CAP-012 — IManagable<T>
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-012")
def test_CAP_012_imanagable_contract() -> None:
    class F(IManagable[str]):
        def __init__(self) -> None:
            self.managed: list[str] = []

        def can_manage(self, item: str) -> bool:
            return True

        def manage(self, item: str) -> None:
            self.managed.append(item)

    f = F()
    assert f.can_manage("x") is True
    f.manage("x")
    assert f.managed == ["x"]


# ---------------------------------------------------------------------------
# CAP-013 — INewCreatable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-013")
def test_CAP_013_inewcreatable_contract() -> None:
    class F(INewCreatable):
        def __init__(self) -> None:
            self.calls = 0

        def can_create_new(self) -> bool:
            return True

        def create_new(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_create_new() is True
    f.create_new()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-014 — IDeletable<T>
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-014")
def test_CAP_014_ideletable_contract() -> None:
    class F(IDeletable[str]):
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def can_delete(self, item: str) -> bool:
            return True

        def delete(self, item: str) -> None:
            self.deleted.append(item)

    f = F()
    assert f.can_delete("a") is True
    f.delete("a")
    assert f.deleted == ["a"]


# ---------------------------------------------------------------------------
# CAP-015 — IUpdatable<T>
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-015")
def test_CAP_015_iupdatable_contract() -> None:
    class F(IUpdatable[str]):
        def __init__(self) -> None:
            self.updated: list[str] = []

        def can_update(self, item: str) -> bool:
            return True

        def update(self, item: str) -> None:
            self.updated.append(item)

    f = F()
    assert f.can_update("a") is True
    f.update("a")
    assert f.updated == ["a"]


# ---------------------------------------------------------------------------
# CAP-016 — ICurrentDeletable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-016")
def test_CAP_016_icurrentdeletable_contract() -> None:
    class F(ICurrentDeletable):
        def __init__(self) -> None:
            self.calls = 0

        def can_delete_current(self) -> bool:
            return True

        def delete_current(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_delete_current() is True
    f.delete_current()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-017 — ICurrentUpdatable
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-017")
def test_CAP_017_icurrentupdatable_contract() -> None:
    class F(ICurrentUpdatable):
        def __init__(self) -> None:
            self.calls = 0

        def can_update_current(self) -> bool:
            return True

        def update_current(self) -> None:
            self.calls += 1

    f = F()
    assert f.can_update_current() is True
    f.update_current()
    assert f.calls == 1


# ---------------------------------------------------------------------------
# CAP-018 — Lifecycle capability set
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-018")
def test_CAP_018_lifecycle_capability_set() -> None:
    class F(IConstructable, IDestructable, IReconstructable):
        def can_construct(self) -> bool:
            return True

        def construct(self) -> None:
            pass

        def can_destruct(self) -> bool:
            return True

        def destruct(self) -> None:
            pass

        def can_reconstruct(self) -> bool:
            return True

        def reconstruct(self) -> None:
            pass

    f = F()
    for op in (
        "can_construct",
        "construct",
        "can_destruct",
        "destruct",
        "can_reconstruct",
        "reconstruct",
    ):
        assert callable(getattr(f, op)), f"{op} should be callable on F"


# ---------------------------------------------------------------------------
# CAP-019 — A single VM may implement multiple capabilities
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-019")
def test_CAP_019_multiple_capabilities() -> None:
    class F(ISelectable, IExpandable, IClosable, IApprovable, ICancelable):
        def __init__(self) -> None:
            self.selects = 0
            self.expands = 0
            self.closes = 0
            self.approves = 0
            self.cancels = 0

        def can_select(self) -> bool:
            return True

        def select(self) -> None:
            self.selects += 1

        @property
        def is_expanded(self) -> bool:
            return False

        def can_expand(self) -> bool:
            return True

        def expand(self) -> None:
            self.expands += 1

        def can_close(self) -> bool:
            return True

        def close(self) -> None:
            self.closes += 1

        def can_approve(self) -> bool:
            return True

        def approve(self) -> None:
            self.approves += 1

        def can_cancel(self) -> bool:
            return True

        def cancel(self) -> None:
            self.cancels += 1

    f = F()
    assert isinstance(f, ISelectable)
    assert isinstance(f, IExpandable)
    assert isinstance(f, IClosable)
    assert isinstance(f, IApprovable)
    assert isinstance(f, ICancelable)
    f.select()
    f.expand()
    f.close()
    f.approve()
    f.cancel()
    assert (f.selects, f.expands, f.closes, f.approves, f.cancels) == (1, 1, 1, 1, 1)


# ---------------------------------------------------------------------------
# CAP-020 — Core VM types do NOT implement non-baseline capabilities by default
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-020")
def test_CAP_020_bare_componentvm_opt_in_only() -> None:
    vm = _bare_component_vm()
    # Non-baseline capabilities — must be False
    for cap in (
        ISelectable,
        IExpandable,
        IClosable,
        INewCreatable,
        ICurrentDeletable,
        ISearchable,
    ):
        assert not isinstance(vm, cap), f"bare ComponentVM should NOT satisfy {cap.__name__}"
    # Lifecycle capabilities — must be True per spec rule 2
    for cap in (IConstructable, IDestructable, IReconstructable):
        assert isinstance(vm, cap), f"bare ComponentVM should satisfy {cap.__name__}"
