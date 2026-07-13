"""Unit tests for package-specific C# release notes."""

import pytest
import render_csharp_release_notes as notes

CHANGELOG = """# Changelog

## [VMx.Notifications 1.2.0] — 2026-07-13

Notification package notes.

## [3.20.0] — 2026-07-12

Core package notes.
"""


def test_render_selects_package_qualified_companion_section() -> None:
    rendered = notes.render_notes(CHANGELOG, [{"id": "VMx.Notifications", "version": "1.2.0"}])

    assert rendered == "## VMx.Notifications 1.2.0\n\nNotification package notes.\n"


def test_render_selects_plain_core_version_section() -> None:
    rendered = notes.render_notes(CHANGELOG, [{"id": "VMx", "version": "3.20.0"}])

    assert rendered == "## VMx 3.20.0\n\nCore package notes.\n"


def test_render_fails_when_matching_section_is_absent() -> None:
    with pytest.raises(ValueError, match="2.1.1"):
        notes.render_notes(
            CHANGELOG,
            [{"id": "VMx.Extensions.DependencyInjection", "version": "2.1.1"}],
        )
