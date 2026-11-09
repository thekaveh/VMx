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
        ("## [Unreleased]\n", "numbered release"),
        ("## [Unreleased]\n\n- Pending.\n\n## [3.23.1]\n", "must be empty"),
        ("## [Draft]\n\n## [Unreleased]\n\n## [3.23.1]\n", "first numbered release"),
    ],
)
def test_rejects_invalid_structure_when_unreleased_exists(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
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


# Release Please writes `*` bullets and runs of blank lines (#1391).
RELEASE_PLEASE_SECTION = (
    "## [3.31.0](https://github.com/thekaveh/VMx/compare/python-v3.30.0...python-v3.31.0)"
    " (2026-11-20)\n\n\n"
    "### ⚠ BREAKING CHANGES\n\n"
    "* **python:** drop the legacy alias\n\n"
    "### Features\n\n"
    "* **python:** add a thing ([#1](https://github.com/thekaveh/VMx/issues/1))"
    " ([abc1234](https://github.com/thekaveh/VMx/commit/abc1234))\n"
    "* second feature_with_underscore and `code`\n\n\n"
    "### Bug Fixes\n\n"
    "* fix z ([#2](https://github.com/thekaveh/VMx/issues/2))\n\n"
)
NORMALIZED_SECTION = (
    "## [3.31.0](https://github.com/thekaveh/VMx/compare/python-v3.30.0...python-v3.31.0)"
    " (2026-11-20)\n\n"
    "### ⚠ BREAKING CHANGES\n\n"
    "- **python:** drop the legacy alias\n\n"
    "### Features\n\n"
    "- **python:** add a thing ([#1](https://github.com/thekaveh/VMx/issues/1))"
    " ([abc1234](https://github.com/thekaveh/VMx/commit/abc1234))\n"
    "- second feature_with_underscore and `code`\n\n"
    "### Bug Fixes\n\n"
    "- fix z ([#2](https://github.com/thekaveh/VMx/issues/2))\n\n"
)
PREVIOUS_RELEASE = "## [3.30.0] — 2026-11-10\n\n### Fixed\n\n- Previous.\n"


def test_normalizes_release_please_markdown_for_mdformat(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        PREAMBLE + RELEASE_PLEASE_SECTION + "## [Unreleased]\n\n" + PREVIOUS_RELEASE,
        encoding="utf-8",
    )

    assert repair.ensure_unreleased(changelog) is True
    assert changelog.read_text(encoding="utf-8") == (
        PREAMBLE + "## [Unreleased]\n\n" + NORMALIZED_SECTION + PREVIOUS_RELEASE
    )
    assert repair.ensure_unreleased(changelog) is False


def test_normalizes_markdown_when_unreleased_is_already_first(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        PREAMBLE + "## [Unreleased]\n\n" + RELEASE_PLEASE_SECTION + PREVIOUS_RELEASE,
        encoding="utf-8",
    )

    assert repair.ensure_unreleased(changelog) is True
    assert changelog.read_text(encoding="utf-8") == (
        PREAMBLE + "## [Unreleased]\n\n" + NORMALIZED_SECTION + PREVIOUS_RELEASE
    )


def test_normalization_leaves_fenced_code_unchanged() -> None:
    text = "- Item.\n\n```text\n* not a bullet\n\n\nkept\n```\n\n\n* bullet\n"

    assert repair.normalize_release_please_markdown(text) == (
        "- Item.\n\n```text\n* not a bullet\n\n\nkept\n```\n\n- bullet\n"
    )


def test_normalized_release_please_output_is_mdformat_clean(tmp_path: Path) -> None:
    mdformat = pytest.importorskip("mdformat")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        PREAMBLE + RELEASE_PLEASE_SECTION + "## [Unreleased]\n\n" + PREVIOUS_RELEASE,
        encoding="utf-8",
    )

    repair.ensure_unreleased(changelog)
    text = changelog.read_text(encoding="utf-8")

    assert mdformat.text(text, extensions={"gfm", "tables"}) == text
