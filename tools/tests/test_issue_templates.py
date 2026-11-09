"""Contracts for the GitHub issue forms in .github/ISSUE_TEMPLATE (#1359)."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"

# Labels that exist in thekaveh/VMx (`gh api repos/thekaveh/VMx/labels`,
# 2026-11-09). GitHub silently drops a form label that the repository lacks, so
# a new form label must be created in the repository before it is added here.
REPOSITORY_LABELS = frozenset(
    {
        ".NET",
        "bug",
        "documentation",
        "enhancement",
        "javascript",
        "python",
        "rust",
    }
)
BOARD_SECTIONS = ("Summary", "Context", "Acceptance criteria", "Evidence")
BUG_FORMS = {
    "bug-csharp.yml": "csharp",
    "bug-python.yml": "python",
    "bug-rust.yml": "rust",
    "bug-swift.yml": "swift",
    "bug-typescript.yml": "typescript",
}
FEATURE_FORMS = ("spec-feature-request.yml",)


def _labels(text: str) -> list[str]:
    match = re.search(r"(?m)^labels: \[(?P<items>[^\]]*)\]$", text)
    assert match is not None
    return [item.strip().strip('"') for item in match.group("items").split(",") if item.strip()]


def _fields(text: str) -> list[dict[str, str]]:
    """Return each body field's top-level attribute lines as a flat mapping."""
    fields = []
    for block in re.split(r"(?m)^  - type: ", text.split("\nbody:\n", 1)[1])[1:]:
        field = {"type": block.split("\n", 1)[0].strip()}
        for key in ("id", "label", "placeholder", "render"):
            match = re.search(rf"(?m)^ {{4,6}}{key}: (?P<value>.+)$", block)
            if match:
                field[key] = match.group("value").strip().strip('"')
        field["block"] = block
        fields.append(field)
    return fields


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def _manifest_majors() -> dict[str, set[str]]:
    csharp = REPO_ROOT / "langs/csharp/src"
    project_versions = {
        _major(re.search(r"<Version>([^<]+)</Version>", path.read_text(encoding="utf-8"))[1])
        for path in (
            csharp / "VMx/VMx.csproj",
            csharp / "VMx.Notifications/VMx.Notifications.csproj",
            csharp / "VMx.Extensions.DependencyInjection/VMx.Extensions.DependencyInjection.csproj",
        )
    }
    python = re.search(
        r'__version__ = "([^"]+)"',
        (REPO_ROOT / "langs/python/src/vmx/__about__.py").read_text(encoding="utf-8"),
    )[1]
    typescript = json.loads(
        (REPO_ROOT / "langs/typescript/package.json").read_text(encoding="utf-8")
    )["version"]
    swift = re.search(
        r'public static let current = "([^"]+)"',
        (REPO_ROOT / "langs/swift/Sources/VMx/Version.swift").read_text(encoding="utf-8"),
    )[1]
    rust = re.search(
        r'(?m)^version = "([^"]+)"',
        (REPO_ROOT / "langs/rust/Cargo.toml").read_text(encoding="utf-8"),
    )[1]
    return {
        "csharp": project_versions,
        "python": {_major(python)},
        "typescript": {_major(typescript)},
        "swift": {_major(swift)},
        "rust": {_major(rust)},
    }


def test_every_form_label_exists_in_the_repository() -> None:
    forms = sorted(TEMPLATES.glob("*.yml"))
    assert forms
    for form in forms:
        labels = _labels(form.read_text(encoding="utf-8"))
        assert labels, form.name
        assert set(labels) <= REPOSITORY_LABELS, (form.name, labels)


def test_bug_forms_apply_bug_and_their_flavor_label() -> None:
    expected = {
        "bug-csharp.yml": ["bug", ".NET"],
        "bug-python.yml": ["bug", "python"],
        "bug-rust.yml": ["bug", "rust"],
        "bug-swift.yml": ["bug"],  # the repository has no Swift label
        "bug-typescript.yml": ["bug", "javascript"],
    }
    for name, labels in expected.items():
        assert _labels((TEMPLATES / name).read_text(encoding="utf-8")) == labels


def test_bug_and_feature_forms_follow_the_board_sections_in_order() -> None:
    for name in (*BUG_FORMS, *FEATURE_FORMS):
        fields = _fields((TEMPLATES / name).read_text(encoding="utf-8"))
        labels = [field.get("label") for field in fields]
        positions = [labels.index(section) for section in BOARD_SECTIONS]
        assert positions == sorted(positions), (name, labels)
        evidence = fields[labels.index("Evidence")]["block"]
        assert "Location | What it shows" in evidence, name


def test_bug_forms_ask_for_the_reproduction_and_observed_output_in_context() -> None:
    for name, render in BUG_FORMS.items():
        fields = _fields((TEMPLATES / name).read_text(encoding="utf-8"))
        labels = [field.get("label") for field in fields]
        context = fields[labels.index("Context")]
        assert "reproduce" in context["block"] and "observed output" in context["block"], name
        reproduction = fields[labels.index("Context") + 1]
        assert reproduction.get("render") == render, name
        assert labels.index("Context") + 1 < labels.index("Acceptance criteria"), name


def test_rust_bug_form_asks_for_version_toolchain_and_platform() -> None:
    labels = [
        field.get("label")
        for field in _fields((TEMPLATES / "bug-rust.yml").read_text(encoding="utf-8"))
    ]
    for label in ("vmx-rs version", "Rust toolchain version", "Platform"):
        assert label in labels


def test_version_placeholders_match_the_manifest_major_versions() -> None:
    majors = _manifest_majors()
    for name, flavor in BUG_FORMS.items():
        fields = _fields((TEMPLATES / name).read_text(encoding="utf-8"))
        version = next(field for field in fields if field.get("id") == "version")
        placeholder_majors = {
            _major(found) for found in re.findall(r"\d+\.\d+\.\d+", version["placeholder"])
        }
        assert placeholder_majors, name
        assert placeholder_majors <= majors[flavor], (name, placeholder_majors, majors[flavor])
