"""DIA-009..013 — VM-backed modal presentation."""

from __future__ import annotations

import pytest

from vmx.dialogs import ModalVM, NullDialogService


@pytest.mark.conformance("DIA-009")
async def test_DIA_009_present_returns_modal_result() -> None:
    modal = ModalVM("cancel")

    class HostDialogService(NullDialogService):
        async def present(self, modal_vm: ModalVM[str]) -> str:
            modal_vm.dismiss("accepted")
            return await modal_vm.wait_result()

    assert await HostDialogService().present(modal) == "accepted"
    assert modal.result == "accepted"


@pytest.mark.conformance("DIA-010")
async def test_DIA_010_null_present_uses_cancellation_result() -> None:
    modal = ModalVM("cancel")

    assert await NullDialogService().present(modal) == "cancel"
    assert modal.is_dismissed is True
    assert modal.result == "cancel"


@pytest.mark.conformance("DIA-011")
async def test_DIA_011_modal_dispose_completes_with_cancellation_result() -> None:
    modal = ModalVM("cancel")
    modal.dispose()

    assert await modal.wait_result() == "cancel"
    assert modal.is_dismissed is True


@pytest.mark.conformance("DIA-012")
async def test_DIA_012_modal_dismiss_is_idempotent() -> None:
    modal = ModalVM("cancel")
    modal.dismiss("first")
    modal.dismiss("second")

    assert await modal.wait_result() == "first"
    assert modal.result == "first"


@pytest.mark.conformance("DIA-013")
async def test_DIA_013_existing_dialog_methods_remain_source_compatible() -> None:
    sut = NullDialogService()

    assert await sut.pick_file_to_open() is None
    assert await sut.pick_file_to_save() is None
    assert await sut.confirm("Proceed?") is False
    assert await sut.notify("Done") is None
