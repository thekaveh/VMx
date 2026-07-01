"""DISC-001..006 — DiscriminatorVM."""

from __future__ import annotations

import pytest

from vmx.state import DiscriminatorVM


@pytest.mark.conformance("DISC-001")
def test_DISC_001_initial_active_key_and_is_active() -> None:
    sut = DiscriminatorVM("nav")
    assert sut.active_key == "nav"
    assert sut.is_active("nav") is True
    assert sut.is_active("modal") is False


@pytest.mark.conformance("DISC-002")
def test_DISC_002_set_active_key_emits_change() -> None:
    sut = DiscriminatorVM("nav")
    seen: list[str] = []
    sut.active_changed.subscribe(seen.append)
    sut.set_active_key("detail")
    assert sut.active_key == "detail"
    assert seen == ["detail"]


@pytest.mark.conformance("DISC-003")
def test_DISC_003_setting_same_key_is_noop() -> None:
    sut = DiscriminatorVM("nav")
    seen: list[str] = []
    sut.active_changed.subscribe(seen.append)
    sut.set_active_key("nav")
    assert seen == []


@pytest.mark.conformance("DISC-004")
def test_DISC_004_modal_open_activates_modal_key() -> None:
    sut = DiscriminatorVM("nav")
    sut.modal_open("modal")
    assert sut.active_key == "modal"
    assert sut.is_active("modal") is True


@pytest.mark.conformance("DISC-005")
def test_DISC_005_modal_close_restores_prior_key() -> None:
    sut = DiscriminatorVM("nav")
    sut.set_active_key("detail")
    sut.modal_open("modal")
    sut.modal_close()
    assert sut.active_key == "detail"


@pytest.mark.conformance("DISC-006")
def test_DISC_006_nested_modal_precedence_restores_in_lifo_order() -> None:
    sut = DiscriminatorVM("nav")
    sut.modal_open("modal-a")
    sut.modal_open("modal-b")
    sut.modal_close()
    assert sut.active_key == "modal-a"
    sut.modal_close()
    assert sut.active_key == "nav"
