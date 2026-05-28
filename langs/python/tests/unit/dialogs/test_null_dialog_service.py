"""Unit tests for NullDialogService.

Each test covers one independently verifiable behavioural requirement.
"""

from __future__ import annotations

import pytest

from vmx.dialogs import (
    NULL_DIALOG_SERVICE,
    DialogService,
    FileFilter,
    NotificationSeverity,
    NullDialogService,
)

# ---------------------------------------------------------------------------
# Construction / type identity
# ---------------------------------------------------------------------------


def test_null_dialog_service_is_dialog_service() -> None:
    sut = NullDialogService()
    assert isinstance(sut, DialogService)


def test_null_dialog_service_singleton_is_not_none() -> None:
    assert NULL_DIALOG_SERVICE is not None


def test_null_dialog_service_singleton_is_same_object() -> None:
    assert NULL_DIALOG_SERVICE is NULL_DIALOG_SERVICE


# ---------------------------------------------------------------------------
# pick_file_to_open
# ---------------------------------------------------------------------------


async def test_pick_file_to_open_no_args_returns_none() -> None:
    sut = NullDialogService()
    result = await sut.pick_file_to_open()
    assert result is None


async def test_pick_file_to_open_with_filter_returns_none() -> None:
    sut = NullDialogService()
    flt = FileFilter("Images", ["*.png", "*.jpg"])
    result = await sut.pick_file_to_open(filter=flt)
    assert result is None


async def test_pick_file_to_open_with_title_returns_none() -> None:
    sut = NullDialogService()
    result = await sut.pick_file_to_open(title="Choose a file")
    assert result is None


async def test_pick_file_to_open_null_filter_returns_none() -> None:
    sut = NullDialogService()
    result = await sut.pick_file_to_open(filter=None)
    assert result is None


async def test_pick_file_to_open_multiple_successive_calls_all_return_none() -> None:
    sut = NullDialogService()
    for i in range(3):
        result = await sut.pick_file_to_open()
        assert result is None, f"call {i} should return None"


# ---------------------------------------------------------------------------
# pick_file_to_save
# ---------------------------------------------------------------------------


async def test_pick_file_to_save_no_args_returns_none() -> None:
    sut = NullDialogService()
    result = await sut.pick_file_to_save()
    assert result is None


async def test_pick_file_to_save_with_all_args_returns_none() -> None:
    sut = NullDialogService()
    flt = FileFilter("Text files", ["*.txt"])
    result = await sut.pick_file_to_save(filter=flt, title="Save as", suggested_name="output.txt")
    assert result is None


async def test_pick_file_to_save_null_filter_returns_none() -> None:
    sut = NullDialogService()
    result = await sut.pick_file_to_save(filter=None)
    assert result is None


async def test_pick_file_to_save_multiple_successive_calls_all_return_none() -> None:
    sut = NullDialogService()
    for i in range(3):
        result = await sut.pick_file_to_save()
        assert result is None, f"call {i} should return None"


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------


async def test_confirm_returns_false_for_safest_default() -> None:
    sut = NullDialogService()
    result = await sut.confirm("Delete item?")
    assert result is False, "NullDialogService returns False to avoid destructive ops"


async def test_confirm_with_title_returns_false() -> None:
    sut = NullDialogService()
    result = await sut.confirm("Overwrite?", title="Confirm")
    assert result is False


async def test_confirm_null_title_returns_false() -> None:
    sut = NullDialogService()
    result = await sut.confirm("msg", title=None)
    assert result is False


async def test_confirm_multiple_successive_calls_all_return_false() -> None:
    sut = NullDialogService()
    for i in range(3):
        result = await sut.confirm(f"message {i}")
        assert result is False, f"call {i} should return False"


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------


async def test_notify_default_severity_info_no_raise() -> None:
    sut = NullDialogService()
    await sut.notify("Hello")  # must not raise


async def test_notify_info_severity_explicit_no_raise() -> None:
    sut = NullDialogService()
    await sut.notify("Info", severity=NotificationSeverity.INFO)


async def test_notify_warning_severity_no_raise() -> None:
    sut = NullDialogService()
    await sut.notify("Warn", severity=NotificationSeverity.WARNING)


async def test_notify_error_severity_no_raise() -> None:
    sut = NullDialogService()
    await sut.notify("Error", severity=NotificationSeverity.ERROR)


async def test_notify_null_title_no_raise() -> None:
    sut = NullDialogService()
    await sut.notify("msg", title=None)


async def test_notify_with_title_no_raise() -> None:
    sut = NullDialogService()
    await sut.notify("msg", title="My title")


async def test_notify_multiple_successive_calls_no_raise() -> None:
    sut = NullDialogService()
    for i in range(3):
        await sut.notify(f"message {i}")  # must not raise


# ---------------------------------------------------------------------------
# FileFilter
# ---------------------------------------------------------------------------


def test_file_filter_stores_description_and_extensions() -> None:
    flt = FileFilter("Images", ["*.png", "*.jpg"])
    assert flt.description == "Images"
    assert list(flt.extensions) == ["*.png", "*.jpg"]


def test_file_filter_empty_extensions_is_valid() -> None:
    flt = FileFilter("All files", [])
    assert list(flt.extensions) == []


def test_file_filter_is_frozen_dataclass() -> None:
    flt = FileFilter("Images", ["*.png"])
    with pytest.raises((AttributeError, TypeError)):
        flt.description = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NotificationSeverity
# ---------------------------------------------------------------------------


def test_notification_severity_has_info_warning_error() -> None:
    assert NotificationSeverity.INFO is not None
    assert NotificationSeverity.WARNING is not None
    assert NotificationSeverity.ERROR is not None


def test_notification_severity_info_value() -> None:
    assert NotificationSeverity.INFO.value == "info"


def test_notification_severity_warning_value() -> None:
    assert NotificationSeverity.WARNING.value == "warning"


def test_notification_severity_error_value() -> None:
    assert NotificationSeverity.ERROR.value == "error"
