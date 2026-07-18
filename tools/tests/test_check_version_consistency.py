"""Unit tests for tools/check-version-consistency.py.

The script is imported under the module name `check_version_consistency` (the
hyphen in the filename would prevent direct import; conftest.py pre-loads it
under the underscore alias via importlib so plain imports work in tests).
"""

import json
import textwrap
from pathlib import Path

import check_version_consistency as cvc
import pytest

# ── parse_spec_version ────────────────────────────────────────────────


def test_parse_spec_version(tmp_path: Path) -> None:
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "VERSION").write_text("2.6.0\n", encoding="utf-8")
    assert cvc.parse_spec_version(tmp_path) == "2.6.0"


def test_parse_spec_version_strips_whitespace(tmp_path: Path) -> None:
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "VERSION").write_text("  2.6.0  \n", encoding="utf-8")
    assert cvc.parse_spec_version(tmp_path) == "2.6.0"


# ── parse_csharp_versions ─────────────────────────────────────────────


def test_parse_csharp_versions(tmp_path: Path) -> None:
    csproj = tmp_path / "VMx.csproj"
    csproj.write_text(
        textwrap.dedent("""\
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup>
                <Version>2.6.0</Version>
                <MinSpecVersion>2.6.0</MinSpecVersion>
              </PropertyGroup>
            </Project>
        """),
        encoding="utf-8",
    )
    info = cvc.parse_csharp_versions(csproj)
    assert info["package_id"] == "VMx"
    assert info["version"] == "2.6.0"
    assert info["min_spec_version"] == "2.6.0"
    assert info["tag_prefix"] == "csharp"
    assert info["require_current_spec"] == "true"


def test_parse_csharp_versions_different_patch(tmp_path: Path) -> None:
    csproj = tmp_path / "VMx.csproj"
    csproj.write_text(
        "<Version>2.7.1</Version><MinSpecVersion>2.7.0</MinSpecVersion>",
        encoding="utf-8",
    )
    info = cvc.parse_csharp_versions(csproj)
    assert info["version"] == "2.7.1"
    assert info["min_spec_version"] == "2.7.0"


def test_parse_csharp_versions_reads_explicit_unreleased_marker(tmp_path: Path) -> None:
    csproj = tmp_path / "VMx.Extensions.DependencyInjection.csproj"
    csproj.write_text("<Version>2.1.1</Version><IsUnreleased>true</IsUnreleased>", encoding="utf-8")

    assert cvc.parse_csharp_versions(csproj)["unreleased"] == "true"


def test_parse_csharp_versions_rejects_unmapped_package_namespace(tmp_path: Path) -> None:
    csproj = tmp_path / "VMx.Future.csproj"
    csproj.write_text(
        "<Project><PropertyGroup><PackageId>VMx.Future</PackageId>"
        "<Version>1.0.0</Version></PropertyGroup></Project>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no collision-free release tag namespace"):
        cvc.parse_csharp_versions(csproj)


def test_collect_manifests_includes_csharp_companion_packages(tmp_path: Path) -> None:
    csharp_src = tmp_path / "langs" / "csharp" / "src"
    core = csharp_src / "VMx"
    notifications = csharp_src / "VMx.Notifications"
    di = csharp_src / "VMx.Extensions.DependencyInjection"
    core.mkdir(parents=True)
    notifications.mkdir()
    di.mkdir()

    (core / "VMx.csproj").write_text(
        "<Project><PropertyGroup><PackageId>VMx</PackageId><Version>3.1.0</Version>"
        "<MinSpecVersion>3.1.0</MinSpecVersion></PropertyGroup></Project>",
        encoding="utf-8",
    )
    (notifications / "VMx.Notifications.csproj").write_text(
        "<Project><PropertyGroup><PackageId>VMx.Notifications</PackageId>"
        "<Version>1.2.0</Version><MinSpecVersion>2.6.0</MinSpecVersion>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )
    (di / "VMx.Extensions.DependencyInjection.csproj").write_text(
        "<Project><PropertyGroup><PackageId>VMx.Extensions.DependencyInjection</PackageId>"
        "<Version>2.1.0</Version><MinSpecVersion>2.1.0</MinSpecVersion>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    manifests = cvc.collect_manifests(tmp_path)

    assert manifests["csharp"]["version"] == "3.1.0"
    assert manifests["csharp"]["require_current_spec"] == "true"
    assert manifests["csharp/VMx.Notifications"]["version"] == "1.2.0"
    assert manifests["csharp/VMx.Notifications"]["tag_prefix"] == "csharp-notifications"
    assert manifests["csharp/VMx.Notifications"]["require_current_spec"] == "false"
    assert manifests["csharp/VMx.Extensions.DependencyInjection"]["version"] == "2.1.0"
    assert (
        manifests["csharp/VMx.Extensions.DependencyInjection"]["tag_prefix"]
        == "csharp-dependency-injection"
    )


def test_csharp_companion_manifests_require_package_specific_tags_but_not_current_spec() -> None:
    manifests = {
        "csharp": {
            "version": "3.1.0",
            "min_spec_version": "3.1.0",
            "tag_prefix": "csharp",
            "require_current_spec": "true",
        },
        "csharp/VMx.Extensions.DependencyInjection": {
            "version": "2.1.0",
            "min_spec_version": "2.1.0",
            "tag_prefix": "csharp-dependency-injection",
            "require_current_spec": "false",
        },
    }

    assert cvc.check_min_spec_versions("3.1.0", manifests) == []

    missing = cvc.find_missing_tags("3.1.0", manifests, [], {"csharp-v3.1.0"})
    assert "csharp-dependency-injection-v2.1.0" in missing


def test_current_development_versions_includes_explicit_unreleased_companion() -> None:
    manifests = {
        "csharp/VMx.Extensions.DependencyInjection": {
            "version": "2.1.1",
            "unreleased": "true",
            "require_current_spec": "false",
        }
    }

    versions = cvc.current_development_versions("3.20.0", manifests, [])

    assert versions == {"3.20.0", "2.1.1"}


# ── parse_python_versions ─────────────────────────────────────────────


def test_parse_python_versions(tmp_path: Path) -> None:
    about = tmp_path / "__about__.py"
    about.write_text(
        textwrap.dedent("""\
            __version__ = "2.6.1"  # x-release-please-version
            __min_spec_version__ = "2.6.0"
        """),
        encoding="utf-8",
    )
    info = cvc.parse_python_versions(about)
    assert info["version"] == "2.6.1"
    assert info["min_spec_version"] == "2.6.0"


def test_parse_python_versions_single_quotes(tmp_path: Path) -> None:
    about = tmp_path / "__about__.py"
    about.write_text(
        "__version__ = '2.5.0'\n__min_spec_version__ = '2.5.0'\n",
        encoding="utf-8",
    )
    info = cvc.parse_python_versions(about)
    assert info["version"] == "2.5.0"
    assert info["min_spec_version"] == "2.5.0"


# ── parse_typescript_versions ─────────────────────────────────────────


def test_parse_typescript_versions(tmp_path: Path) -> None:
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"name": "@thekaveh/vmx", "version": "2.6.0"}), encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "version.ts").write_text(
        'export const __minSpecVersion__ = "2.6.0";\n',
        encoding="utf-8",
    )
    info = cvc.parse_typescript_versions(pkg, src)
    assert info["version"] == "2.6.0"
    assert info["min_spec_version"] == "2.6.0"


def test_parse_typescript_versions_no_min_spec(tmp_path: Path) -> None:
    """If no __minSpecVersion__ is found in src/, min_spec_version is empty."""
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"version": "2.6.0"}), encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    info = cvc.parse_typescript_versions(pkg, src)
    assert info["version"] == "2.6.0"
    assert info["min_spec_version"] == ""


def test_check_typescript_example_locks_match_package_version(tmp_path: Path) -> None:
    for relative in cvc.TYPESCRIPT_EXAMPLE_LOCKS:
        lock_path = tmp_path / relative
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(
                {
                    "packages": {
                        "../../../../langs/typescript": {
                            "name": "@thekaveh/vmx",
                            "version": "3.21.0",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    assert cvc.check_typescript_example_locks(tmp_path, "3.21.0") == []


def test_check_typescript_example_locks_reports_stale_metadata(tmp_path: Path) -> None:
    lock_path = tmp_path / cvc.TYPESCRIPT_EXAMPLE_LOCKS[0]
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "packages": {
                    "../../../../langs/typescript": {
                        "name": "@thekaveh/vmx",
                        "version": "3.8.0",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    issues = cvc.check_typescript_example_locks(tmp_path, "3.21.0")

    assert len(issues) == 1
    assert "3.8.0" in issues[0]
    assert "3.21.0" in issues[0]


# ── parse_swift_versions ──────────────────────────────────────────────


def test_parse_swift_versions(tmp_path: Path) -> None:
    ver = tmp_path / "Version.swift"
    ver.write_text(
        textwrap.dedent("""\
            public enum VMxVersion {
                public static let current = "2.6.0"
                public static let minSpecVersion = "2.6.0"
            }
        """),
        encoding="utf-8",
    )
    info = cvc.parse_swift_versions(ver)
    assert info["version"] == "2.6.0"
    assert info["min_spec_version"] == "2.6.0"


# ── parse_matrix ──────────────────────────────────────────────────────


def test_parse_matrix_basic(tmp_path: Path) -> None:
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        textwrap.dedent("""\
            # Spec ↔ language compatibility matrix

            ## 1. Matrix

            | spec  | csharp | python | typescript | swift          |
            | ----- | ------ | ------ | ---------- | -------------- |
            | 2.6.x | 2.6.0  | 2.6.1  | 2.6.0      | 2.6.0 (subset) |
            | 2.5.x | 2.5.0  | 2.5.0  | 2.5.0      | 2.5.0 (subset) |
            | 2.0.x | 2.0.0  | 2.0.0  | 2.0.0      | —              |
        """),
        encoding="utf-8",
    )
    rows = cvc.parse_matrix(matrix)
    assert len(rows) == 3

    row_26 = next(r for r in rows if r["spec_row"] == "2.6.x")
    assert row_26["csharp"] == ["2.6.0"]
    assert row_26["python"] == ["2.6.1"]
    assert row_26["typescript"] == ["2.6.0"]
    assert row_26["swift"] == ["2.6.0"]  # "(subset)" stripped

    row_25 = next(r for r in rows if r["spec_row"] == "2.5.x")
    assert row_25["csharp"] == ["2.5.0"]
    assert row_25["swift"] == ["2.5.0"]

    row_20 = next(r for r in rows if r["spec_row"] == "2.0.x")
    assert row_20["swift"] == []  # "—" → empty


def test_parse_matrix_maps_flavors_by_header_name(tmp_path: Path) -> None:
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        textwrap.dedent("""\
            | spec | python | csharp | typescript | swift | rust |
            | --- | --- | --- | --- | --- | --- |
            | 3.22.x | 3.22.1 | 3.22.0 | 3.23.0 | 3.22.0 | 0.25.0 |
        """),
        encoding="utf-8",
    )

    assert cvc.parse_matrix(matrix) == [
        {
            "spec_row": "3.22.x",
            "csharp": ["3.22.0"],
            "python": ["3.22.1"],
            "typescript": ["3.23.0"],
            "swift": ["3.22.0"],
            "rust": ["0.25.0"],
        }
    ]


def test_parse_matrix_handles_version_range(tmp_path: Path) -> None:
    """A version-range cell (en-dash separator) should yield two version entries."""
    # The real compatibility-matrix.md uses U+2013 (EN DASH) for ranges.
    en = "\u2013"  # EN DASH (U+2013), same char used in compatibility-matrix.md
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        textwrap.dedent(f"""\
            | spec  | csharp             | python             | typescript         | swift |
            | ----- | ------------------ | ------------------ | ------------------ | ----- |
            | 1.1.x | 1.1.0 {en} 1.2.0  | 1.1.0 {en} 1.2.0  | 1.1.0 {en} 1.2.0  | —     |
        """),
        encoding="utf-8",
    )
    rows = cvc.parse_matrix(matrix)
    assert len(rows) == 1
    row = rows[0]
    assert sorted(row["csharp"]) == ["1.1.0", "1.2.0"]
    assert sorted(row["python"]) == ["1.1.0", "1.2.0"]
    assert row["swift"] == []


def test_parse_matrix_marks_legacy_semantic_tag_row(tmp_path: Path) -> None:
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        textwrap.dedent("""\
            | spec                               | csharp | python | typescript | swift  | rust |
            | ---------------------------------- | ------ | ------ | ---------- | ------ | ---- |
            | 3.20.x[^legacy-semantic-tag-only] | —      | —      | —          | 3.20.0 | —    |
        """),
        encoding="utf-8",
    )

    assert cvc.parse_matrix(matrix) == [
        {
            "spec_row": "3.20.x",
            "legacy_semantic_tag_only": True,
            "csharp": [],
            "python": [],
            "typescript": [],
            "swift": ["3.20.0"],
            "rust": [],
        }
    ]


def test_parse_matrix_dash_cell(tmp_path: Path) -> None:
    """A '—' or '-' cell means no release for that flavor/spec pair."""
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        textwrap.dedent("""\
            | spec  | csharp | python | typescript | swift |
            | ----- | ------ | ------ | ---------- | ----- |
            | 1.0.x | 1.0.0  | 1.0.0  | —          | —     |
        """),
        encoding="utf-8",
    )
    rows = cvc.parse_matrix(matrix)
    row = rows[0]
    assert row["typescript"] == []
    assert row["swift"] == []
    assert row["csharp"] == ["1.0.0"]


# ── check_min_spec_versions ───────────────────────────────────────────


def test_check_min_spec_versions_all_match() -> None:
    manifests = {
        "csharp": {"version": "2.6.0", "min_spec_version": "2.6.0"},
        "python": {"version": "2.6.1", "min_spec_version": "2.6.0"},
    }
    issues = cvc.check_min_spec_versions("2.6.0", manifests)
    assert issues == []


def test_check_min_spec_versions_mismatch() -> None:
    manifests = {
        "csharp": {"version": "2.6.0", "min_spec_version": "2.5.0"},  # stale
    }
    issues = cvc.check_min_spec_versions("2.6.0", manifests)
    assert len(issues) == 1
    assert "csharp" in issues[0]
    assert "2.5.0" in issues[0]
    assert "2.6.0" in issues[0]


# ── find_missing_tags ─────────────────────────────────────────────────


def test_find_missing_tags_flags_fabricated_matrix_row() -> None:
    """(a) A matrix row that claims versions but has zero matching tags is flagged."""
    rows = [
        {
            "spec_row": "2.5.x",
            "csharp": ["2.5.0"],
            "python": ["2.5.0"],
            "typescript": ["2.5.0"],
            "swift": ["2.5.0"],
        }
    ]
    tags: set[str] = set()  # no tags at all
    missing = cvc.find_missing_tags("2.6.0", {}, rows, tags)

    assert "csharp-v2.5.0" in missing
    assert "python-v2.5.0" in missing
    assert "typescript-v2.5.0" in missing
    assert "swift-v2.5.0" in missing
    assert "spec-v2.5.0" in missing
    assert "v2.5.0" in missing


def test_find_missing_tags_flags_missing_spec_tag() -> None:
    """(b) A manifest spec/VERSION with no matching spec-v/v tags is flagged."""
    manifests = {
        "csharp": {"version": "2.6.0", "min_spec_version": "2.6.0"},
        "python": {"version": "2.6.1", "min_spec_version": "2.6.0"},
    }
    # Flavor tags exist but spec/repo-wide tags are absent
    tags = {"csharp-v2.6.0", "python-v2.6.1"}
    missing = cvc.find_missing_tags("2.6.0", manifests, [], tags)

    assert "spec-v2.6.0" in missing
    assert "v2.6.0" in missing
    # Flavor tags are present, so not reported
    assert "csharp-v2.6.0" not in missing
    assert "python-v2.6.1" not in missing


def test_find_missing_tags_passes_fully_consistent_fixture() -> None:
    """(c) A fully-consistent fixture produces an empty missing-tag dict."""
    rows = [
        {
            "spec_row": "2.6.x",
            "csharp": ["2.6.0"],
            "python": ["2.6.0"],
            "typescript": ["2.6.0"],
            "swift": ["2.6.0"],
        }
    ]
    manifests = {
        "csharp": {"version": "2.6.0", "min_spec_version": "2.6.0"},
        "python": {"version": "2.6.0", "min_spec_version": "2.6.0"},
        "typescript": {"version": "2.6.0", "min_spec_version": "2.6.0"},
        "swift": {"version": "2.6.0", "min_spec_version": "2.6.0"},
    }
    tags = {
        "csharp-v2.6.0",
        "python-v2.6.0",
        "typescript-v2.6.0",
        "swift-v2.6.0",
        "spec-v2.6.0",
        "v2.6.0",
    }
    missing = cvc.find_missing_tags("2.6.0", manifests, rows, tags)
    assert not missing

    issues = cvc.check_min_spec_versions("2.6.0", manifests)
    assert not issues


def test_find_missing_tags_deduplicates_same_tag_from_matrix_and_manifest() -> None:
    """spec-v2.6.0 is implied by both the manifest and matrix; it must appear once."""
    rows = [
        {
            "spec_row": "2.6.x",
            "csharp": ["2.6.0"],
            "python": ["2.6.0"],
            "typescript": ["2.6.0"],
            "swift": ["2.6.0"],
        }
    ]
    manifests = {
        "csharp": {"version": "2.6.0", "min_spec_version": "2.6.0"},
    }
    tags: set[str] = set()  # nothing tagged
    missing = cvc.find_missing_tags("2.6.0", manifests, rows, tags)

    # spec-v2.6.0 is missing — appears exactly once as a dict key
    assert "spec-v2.6.0" in missing
    # The reasons list may mention both sources, but the key is deduplicated
    assert isinstance(missing["spec-v2.6.0"], list)


def test_find_missing_tags_skips_empty_flavor_cells() -> None:
    """A '—' cell in the matrix should not generate any missing-tag report."""
    rows = [
        {
            "spec_row": "2.3.x",
            "csharp": ["2.3.0"],
            "python": ["2.3.0"],
            "typescript": ["2.3.0"],
            "swift": [],  # no swift release for 2.3.x
        }
    ]
    tags = {"csharp-v2.3.0", "python-v2.3.0", "typescript-v2.3.0", "spec-v2.3.0", "v2.3.0"}
    missing = cvc.find_missing_tags("2.6.0", {}, rows, tags)
    assert "swift-v2.3.0" not in missing


def test_find_missing_tags_does_not_invent_release_tags_for_source_only_rust_row() -> None:
    rows = [
        {
            "spec_row": "3.2.x",
            "csharp": [],
            "python": [],
            "typescript": [],
            "swift": [],
            "rust": ["0.2.0"],
        }
    ]

    missing = cvc.find_missing_tags("3.3.0", {}, rows, set())

    assert "rust-v0.2.0" in missing
    assert "spec-v3.2.0" not in missing
    assert "v3.2.0" not in missing


def test_find_missing_tags_requires_release_tags_for_stable_rust_only_row() -> None:
    rows = [
        {
            "spec_row": "4.0.x",
            "csharp": [],
            "python": [],
            "typescript": [],
            "swift": [],
            "rust": ["2.0.0"],
        }
    ]

    missing = cvc.find_missing_tags("4.1.0", {}, rows, set())

    assert "rust-v2.0.0" in missing
    assert "spec-v4.0.0" in missing
    assert "v4.0.0" in missing


def test_find_missing_tags_accepts_explicit_legacy_semantic_tag_only_row() -> None:
    rows = [
        {
            "spec_row": "3.20.x",
            "legacy_semantic_tag_only": True,
            "csharp": [],
            "python": [],
            "typescript": [],
            "swift": ["3.20.0"],
            "rust": [],
        }
    ]
    tags = {"v3.20.0", "swift-v3.20.0"}

    missing = cvc.find_missing_tags("3.21.0", {}, rows, tags)

    assert "spec-v3.20.0" not in missing
    assert "v3.20.0" not in missing
    assert "swift-v3.20.0" not in missing


# ── main integration ───────────────────────────────────────────────────


def _make_repo(tmp_path: Path) -> None:
    """Set up a minimal repo layout for main() integration tests."""
    # spec/VERSION
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "VERSION").write_text("2.6.0\n", encoding="utf-8")

    # compatibility-matrix.md (one clean 2.6.x row, one problem 2.5.x row)
    (tmp_path / "compatibility-matrix.md").write_text(
        textwrap.dedent("""\
            # matrix

            ## 1. Matrix

            | spec  | csharp | python | typescript | swift |
            | ----- | ------ | ------ | ---------- | ----- |
            | 2.6.x | 2.6.0  | 2.6.0  | 2.6.0      | 2.6.0 |
            | 2.5.x | 2.5.0  | 2.5.0  | 2.5.0      | 2.5.0 |
        """),
        encoding="utf-8",
    )

    # C# manifest
    cs_dir = tmp_path / "langs" / "csharp" / "src" / "VMx"
    cs_dir.mkdir(parents=True)
    (cs_dir / "VMx.csproj").write_text(
        "<Version>2.6.0</Version><MinSpecVersion>2.6.0</MinSpecVersion>",
        encoding="utf-8",
    )

    # Python manifest
    py_dir = tmp_path / "langs" / "python" / "src" / "vmx"
    py_dir.mkdir(parents=True)
    (py_dir / "__about__.py").write_text(
        '__version__ = "2.6.0"\n__min_spec_version__ = "2.6.0"\n',
        encoding="utf-8",
    )

    # TypeScript manifest
    ts_dir = tmp_path / "langs" / "typescript"
    ts_dir.mkdir(parents=True)
    (ts_dir / "package.json").write_text(json.dumps({"version": "2.6.0"}), encoding="utf-8")
    ts_src = ts_dir / "src"
    ts_src.mkdir()
    (ts_src / "version.ts").write_text(
        'export const __minSpecVersion__ = "2.6.0";\n', encoding="utf-8"
    )

    # Swift manifest
    swift_dir = tmp_path / "langs" / "swift" / "Sources" / "VMx"
    swift_dir.mkdir(parents=True)
    (swift_dir / "Version.swift").write_text(
        'public static let current = "2.6.0"\npublic static let minSpecVersion = "2.6.0"\n',
        encoding="utf-8",
    )


def test_main_exits_nonzero_when_tags_missing(tmp_path: Path, monkeypatch: object) -> None:
    """main() returns 1 when a 2.x matrix row has versions but no enforced tags exist."""
    _make_repo(tmp_path)
    # Have 2.6.x flavor tags but missing spec-v2.6.0, v2.6.0, and all 2.5.x tags.
    # The 2.5.x and spec/repo-wide gaps are major-2 → enforced → exit 1.
    import check_version_consistency as _cvc

    monkeypatch.setattr(
        _cvc,
        "get_git_tags",
        lambda _root: {"csharp-v2.6.0", "python-v2.6.0", "typescript-v2.6.0", "swift-v2.6.0"},
    )
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 1


def test_main_exits_zero_when_fully_consistent(tmp_path: Path, monkeypatch: object) -> None:
    """main() returns 0 when every claimed version has a matching tag."""
    _make_repo(tmp_path)
    import check_version_consistency as _cvc

    full_tags = {
        "csharp-v2.6.0",
        "python-v2.6.0",
        "typescript-v2.6.0",
        "swift-v2.6.0",
        "spec-v2.6.0",
        "v2.6.0",
        "csharp-v2.5.0",
        "python-v2.5.0",
        "typescript-v2.5.0",
        "swift-v2.5.0",
        "spec-v2.5.0",
        "v2.5.0",
    }
    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: full_tags)
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 0


def test_main_exits_2_when_spec_version_missing(tmp_path: Path) -> None:
    """main() returns 2 if spec/VERSION is absent."""
    (tmp_path / "compatibility-matrix.md").write_text("# empty\n", encoding="utf-8")
    import check_version_consistency as _cvc

    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 2


def test_main_exits_2_when_matrix_missing(tmp_path: Path) -> None:
    """main() returns 2 if compatibility-matrix.md is absent."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "VERSION").write_text("2.6.0\n", encoding="utf-8")
    import check_version_consistency as _cvc

    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 2


def test_main_reports_min_spec_version_mismatch(tmp_path: Path, monkeypatch: object) -> None:
    """main() returns 1 and reports mismatching minSpecVersion fields."""
    _make_repo(tmp_path)
    # Overwrite C# manifest with a stale minSpecVersion
    cs_dir = tmp_path / "langs" / "csharp" / "src" / "VMx"
    (cs_dir / "VMx.csproj").write_text(
        "<Version>2.6.0</Version><MinSpecVersion>2.5.0</MinSpecVersion>",
        encoding="utf-8",
    )
    import check_version_consistency as _cvc

    # Provide all needed tags so the only error is the minSpecVersion mismatch
    full_tags = {
        "csharp-v2.6.0",
        "python-v2.6.0",
        "typescript-v2.6.0",
        "swift-v2.6.0",
        "spec-v2.6.0",
        "v2.6.0",
        "csharp-v2.5.0",
        "python-v2.5.0",
        "typescript-v2.5.0",
        "swift-v2.5.0",
        "spec-v2.5.0",
        "v2.5.0",
    }
    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: full_tags)
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 1


# ── MIN_ENFORCED_MAJOR: pre-2.0 tolerance (VMX-060) ───────────────────


def test_main_tolerates_missing_1x_tags(tmp_path: Path, monkeypatch: object) -> None:
    """(VMX-060a) A 1.x matrix row with no matching tags exits 0 (informational only)."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "VERSION").write_text("2.6.0\n", encoding="utf-8")
    (tmp_path / "compatibility-matrix.md").write_text(
        textwrap.dedent("""\
            # matrix

            ## 1. Matrix

            | spec  | csharp | python | typescript | swift |
            | ----- | ------ | ------ | ---------- | ----- |
            | 2.6.x | 2.6.0  | 2.6.0  | 2.6.0      | 2.6.0 |
            | 1.1.x | 1.1.0  | 1.1.0  | 1.1.0      | —     |
            | 1.0.x | 1.0.0  | 1.0.0  | —          | —     |
        """),
        encoding="utf-8",
    )
    # Minimal manifests at 2.6.0
    cs_dir = tmp_path / "langs" / "csharp" / "src" / "VMx"
    cs_dir.mkdir(parents=True)
    (cs_dir / "VMx.csproj").write_text(
        "<Version>2.6.0</Version><MinSpecVersion>2.6.0</MinSpecVersion>",
        encoding="utf-8",
    )
    py_dir = tmp_path / "langs" / "python" / "src" / "vmx"
    py_dir.mkdir(parents=True)
    (py_dir / "__about__.py").write_text(
        '__version__ = "2.6.0"\n__min_spec_version__ = "2.6.0"\n',
        encoding="utf-8",
    )
    ts_dir = tmp_path / "langs" / "typescript"
    ts_dir.mkdir(parents=True)
    (ts_dir / "package.json").write_text(json.dumps({"version": "2.6.0"}), encoding="utf-8")
    ts_src = ts_dir / "src"
    ts_src.mkdir()
    (ts_src / "version.ts").write_text(
        'export const __minSpecVersion__ = "2.6.0";\n', encoding="utf-8"
    )
    import check_version_consistency as _cvc

    # Provide all 2.6.x tags but NO 1.x tags.
    all_2_6_tags = {
        "csharp-v2.6.0",
        "python-v2.6.0",
        "typescript-v2.6.0",
        "swift-v2.6.0",
        "spec-v2.6.0",
        "v2.6.0",
    }
    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: all_2_6_tags)
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    # 1.x gaps are informational only; must not cause exit 1.
    assert rc == 0


def test_main_still_fails_2x_missing_tags(tmp_path: Path, monkeypatch: object) -> None:
    """(VMX-060b) A 2.x matrix row with missing tags still exits 1 after the policy change."""
    _make_repo(tmp_path)  # matrix has 2.6.x and 2.5.x rows (both major=2)
    import check_version_consistency as _cvc

    # Only 2.6.x flavor tags — spec-v2.6.0, v2.6.0, and all 2.5.x tags absent.
    # Major-2 gaps → enforced → exit 1.
    monkeypatch.setattr(
        _cvc,
        "get_git_tags",
        lambda _root: {"csharp-v2.6.0", "python-v2.6.0", "typescript-v2.6.0", "swift-v2.6.0"},
    )
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 1


# ── _tag_version helper ───────────────────────────────────────────────


def test_tag_version_extracts_semver() -> None:
    assert cvc._tag_version("csharp-v3.0.0") == "3.0.0"
    assert cvc._tag_version("spec-v3.0.0") == "3.0.0"
    assert cvc._tag_version("v3.0.0") == "3.0.0"
    assert cvc._tag_version("python-v2.6.1") == "2.6.1"


def test_tag_version_empty_when_unparseable() -> None:
    assert cvc._tag_version("not-a-tag") == ""


# ── in-development (== spec/VERSION) exemption ────────────────────────


def _make_repo_v3(tmp_path: Path) -> None:
    """Minimal repo at spec/VERSION 3.0.0 with a current 3.0.x row + a tagged 2.6.x row."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "VERSION").write_text("3.0.0\n", encoding="utf-8")

    (tmp_path / "compatibility-matrix.md").write_text(
        textwrap.dedent("""\
            # matrix

            ## 1. Matrix

            | spec  | csharp | python | typescript | swift          |
            | ----- | ------ | ------ | ---------- | -------------- |
            | 3.0.x | 3.0.0  | 3.0.0  | 3.0.0      | 3.0.0 (subset) |
            | 2.6.x | 2.6.0  | 2.6.0  | 2.6.0      | 2.6.0          |
        """),
        encoding="utf-8",
    )

    cs_dir = tmp_path / "langs" / "csharp" / "src" / "VMx"
    cs_dir.mkdir(parents=True)
    (cs_dir / "VMx.csproj").write_text(
        "<Version>3.0.0</Version><MinSpecVersion>3.0.0</MinSpecVersion>",
        encoding="utf-8",
    )
    py_dir = tmp_path / "langs" / "python" / "src" / "vmx"
    py_dir.mkdir(parents=True)
    (py_dir / "__about__.py").write_text(
        '__version__ = "3.0.0"\n__min_spec_version__ = "3.0.0"\n',
        encoding="utf-8",
    )
    ts_dir = tmp_path / "langs" / "typescript"
    ts_dir.mkdir(parents=True)
    (ts_dir / "package.json").write_text(json.dumps({"version": "3.0.0"}), encoding="utf-8")
    ts_src = ts_dir / "src"
    ts_src.mkdir()
    (ts_src / "version.ts").write_text(
        'export const __minSpecVersion__ = "3.0.0";\n', encoding="utf-8"
    )
    swift_dir = tmp_path / "langs" / "swift" / "Sources" / "VMx"
    swift_dir.mkdir(parents=True)
    (swift_dir / "Version.swift").write_text(
        'static let current = "3.0.0"\nstatic let minSpecVersion = "3.0.0"\n',
        encoding="utf-8",
    )


# Tags for the already-released 2.6.x row (everything EXCEPT the in-dev 3.0.0).
_TAGS_2_6_ONLY = {
    "csharp-v2.6.0",
    "python-v2.6.0",
    "typescript-v2.6.0",
    "swift-v2.6.0",
    "spec-v2.6.0",
    "v2.6.0",
}


def test_main_exits_zero_when_indev_version_untagged(tmp_path: Path, monkeypatch: object) -> None:
    """The current version (== spec/VERSION) needs no tag; absent 3.0.0 tags exit 0."""
    _make_repo_v3(tmp_path)
    import check_version_consistency as _cvc

    # Only the prior 2.6.x tags exist; NO v3.0.0 / spec-v3.0.0 / <flavor>-v3.0.0 tags.
    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: set(_TAGS_2_6_ONLY))
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 0


def test_main_exempts_independently_versioned_current_flavor(
    tmp_path: Path, monkeypatch: object
) -> None:
    """A current flavor may advance while its min-spec remains spec/VERSION."""
    _make_repo_v3(tmp_path)
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace(
            "| 3.0.x | 3.0.0  | 3.0.0  | 3.0.0      | 3.0.0 (subset) |",
            "| 3.0.x | 3.0.0  | 3.0.0  | 3.0.0\u20133.1.0 | 3.0.0 (subset) |",
        ),
        encoding="utf-8",
    )
    package_json = tmp_path / "langs" / "typescript" / "package.json"
    package_json.write_text(json.dumps({"version": "3.1.0"}), encoding="utf-8")
    import check_version_consistency as _cvc

    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: set(_TAGS_2_6_ONLY))

    assert _cvc.main(["--repo-root", str(tmp_path)]) == 0


def test_main_exempts_untagged_source_history_in_current_row(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Earlier untagged snapshots in the active row are source history, not releases."""
    _make_repo_v3(tmp_path)
    matrix = tmp_path / "compatibility-matrix.md"
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace(
            "| 3.0.x | 3.0.0  | 3.0.0  | 3.0.0      | 3.0.0 (subset) |",
            "| 3.0.x | 3.0.0\u20133.0.1 | 3.0.0 | 3.0.0 | 3.0.0 (subset) |",
        ),
        encoding="utf-8",
    )
    csproj = tmp_path / "langs" / "csharp" / "src" / "VMx" / "VMx.csproj"
    csproj.write_text(
        "<Version>3.0.1</Version><MinSpecVersion>3.0.0</MinSpecVersion>",
        encoding="utf-8",
    )
    import check_version_consistency as _cvc

    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: set(_TAGS_2_6_ONLY))

    assert _cvc.main(["--repo-root", str(tmp_path)]) == 0


def test_indev_tags_reported_separately() -> None:
    """The 3.0.0 (in-dev) gaps are carved out of enforced_missing in find_missing_tags."""
    rows = [
        {
            "spec_row": "3.0.x",
            "csharp": ["3.0.0"],
            "python": ["3.0.0"],
            "typescript": ["3.0.0"],
            "swift": ["3.0.0"],
        },
        {
            "spec_row": "2.6.x",
            "csharp": ["2.6.0"],
            "python": ["2.6.0"],
            "typescript": ["2.6.0"],
            "swift": ["2.6.0"],
        },
    ]
    missing = cvc.find_missing_tags("3.0.0", {}, rows, set(_TAGS_2_6_ONLY))
    # 3.0.0 tags are missing but identified as in-dev by _tag_version == spec/VERSION.
    indev = {t for t in missing if cvc._tag_version(t) == "3.0.0"}
    enforced = {t for t in missing if cvc._tag_version(t) != "3.0.0"}
    assert "spec-v3.0.0" in indev
    assert "v3.0.0" in indev
    assert "csharp-v3.0.0" in indev
    # The released 2.6.x row is fully tagged, so nothing else is missing.
    assert enforced == set()


def test_main_still_fails_when_non_current_2x_untagged(tmp_path: Path, monkeypatch: object) -> None:
    """In-dev 3.0.0 is exempt, but a non-current 2.6.x row with NO tags still exits 1."""
    _make_repo_v3(tmp_path)
    import check_version_consistency as _cvc

    # No tags at all: 3.0.0 gaps are exempt (in-dev) but the 2.6.x row is enforced.
    monkeypatch.setattr(_cvc, "get_git_tags", lambda _root: set())
    rc = _cvc.main(["--repo-root", str(tmp_path)])
    assert rc == 1
