"""DISC-001..009 — DiscriminatorVM."""

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


@pytest.mark.conformance("DISC-007")
def test_DISC_007_modal_depth_tracks_frames_and_disposal_releases_them() -> None:
    sut = DiscriminatorVM("nav")
    assert sut.modal_depth == 0
    sut.modal_open("modal-a")
    assert sut.modal_depth == 1
    sut.modal_open("modal-b")
    assert sut.modal_depth == 2
    sut.modal_close()
    assert sut.modal_depth == 1
    sut.dispose()
    assert sut.modal_depth == 0


@pytest.mark.conformance("DISC-008")
def test_DISC_008_clear_modals_drains_without_changing_active_key() -> None:
    sut = DiscriminatorVM("nav")
    sut.modal_open("modal-a")
    sut.modal_open("modal-b")
    seen: list[str] = []
    sut.active_changed.subscribe(seen.append)

    sut.clear_modals()

    assert sut.modal_depth == 0
    assert sut.active_key == "modal-b"
    assert seen == []
    sut.modal_close()
    assert sut.active_key == "modal-b"


@pytest.mark.conformance("DISC-009")
def test_DISC_009_non_modal_set_abandons_history_including_same_key() -> None:
    sut = DiscriminatorVM("nav")
    seen: list[str] = []
    sut.active_changed.subscribe(seen.append)
    sut.modal_open("modal-a")
    sut.modal_open("modal-b")

    sut.set_active_key("route")

    assert sut.modal_depth == 0
    sut.modal_close()
    assert sut.active_key == "route"

    sut.modal_open("modal")
    change_count = len(seen)
    sut.set_active_key("modal")
    assert sut.modal_depth == 0
    assert len(seen) == change_count
