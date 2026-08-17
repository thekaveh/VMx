"""Tests for restoring the canonical Unreleased section after Release Please."""

from pathlib import Path

import ensure_release_changelog_unreleased as repair
import pytest

PREAMBLE = "# Changelog\n\nPython release history.\n\n"


def test_inserts_empty_unreleased_before_first_numbered_release(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        PREAMBLE + "## [3.23.1] — 2026-08-16\n\n### Fixed\n\n- Repair.\n",
        encoding="utf-8",
    )

    assert repair.ensure_unreleased(changelog) is True
    assert changelog.read_text(encoding="utf-8") == (
        PREAMBLE + "## [Unreleased]\n\n" + "## [3.23.1] — 2026-08-16\n\n### Fixed\n\n- Repair.\n"
    )


def test_canonical_changelog_is_unchanged(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    original = PREAMBLE + "## [Unreleased]\n\n## [3.23.1] — 2026-08-16\n"
    changelog.write_text(original, encoding="utf-8")

    assert repair.ensure_unreleased(changelog) is False
    assert changelog.read_text(encoding="utf-8") == original


def test_moves_empty_unreleased_before_release_please_linked_heading(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    release = (
        "## [3.23.1](https://example.test/compare/v3.23.0...v3.23.1) (2026-08-17)\n\n"
        "### Fixed\n\n- Repair.\n\n"
    )
    previous = "## [3.23.0] — 2026-07-25\n\n- Previous.\n"
    changelog.write_text(PREAMBLE + release + "## [Unreleased]\n\n" + previous, encoding="utf-8")

    assert repair.ensure_unreleased(changelog) is True
    assert changelog.read_text(encoding="utf-8") == (
        PREAMBLE + "## [Unreleased]\n\n" + release + previous
    )


def test_rejects_misplaced_unreleased_with_notes(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    body = "## [3.23.1]\n\n- Release.\n\n## [Unreleased]\n\n- Pending.\n"
    changelog.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match="must be empty"):
        repair.ensure_unreleased(changelog)

    assert changelog.read_text(encoding="utf-8") == body


@pytest.mark.parametrize(
    "body, message",
    [
        (
            "## [Unreleased]\n\n## [3.23.1]\n\n## [Unreleased]\n",
            "exactly one",
        ),
        ("# Changelog\n\nNo numbered releases yet.\n", "numbered release"),
    ],
)
def test_rejects_ambiguous_or_malformed_changelog(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        repair.ensure_unreleased(changelog)

    assert changelog.read_text(encoding="utf-8") == body
