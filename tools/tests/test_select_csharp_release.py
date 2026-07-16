"""Unit tests for collision-free C# release-tag selection."""

import json
from pathlib import Path

import pytest
import select_csharp_release as selector


@pytest.mark.parametrize(
    ("tag", "package_id", "version"),
    [
        ("csharp-v3.22.0", "VMx", "3.22.0"),
        ("csharp-notifications-v1.2.0", "VMx.Notifications", "1.2.0"),
        (
            "csharp-dependency-injection-v2.1.1",
            "VMx.Extensions.DependencyInjection",
            "2.1.1",
        ),
    ],
)
def test_parse_tag_maps_each_namespace_to_one_package(
    tag: str,
    package_id: str,
    version: str,
) -> None:
    assert selector.parse_tag(tag) == (package_id, version)


@pytest.mark.parametrize(
    "tag",
    [
        "csharp-v3.22",
        "csharp-v3.22.0-rc.1",
        "csharp-other-v1.0.0",
        "python-v3.22.0",
    ],
)
def test_parse_tag_rejects_unknown_or_non_stable_tags(tag: str) -> None:
    with pytest.raises(ValueError):
        selector.parse_tag(tag)


def test_build_manifest_selects_only_tag_named_package_when_versions_collide(
    tmp_path: Path,
) -> None:
    for package_id in ("VMx", "VMx.Notifications", "VMx.Extensions.DependencyInjection"):
        project = tmp_path / package_id / f"{package_id}.csproj"
        project.parent.mkdir()
        project.write_text(
            "<Project><PropertyGroup>"
            f"<PackageId>{package_id}</PackageId><Version>2.1.1</Version>"
            "</PropertyGroup></Project>",
            encoding="utf-8",
        )

    manifest = selector.build_manifest(
        "csharp-dependency-injection-v2.1.1",
        tmp_path,
    )

    assert manifest == [
        {
            "id": "VMx.Extensions.DependencyInjection",
            "version": "2.1.1",
            "nupkg": "VMx.Extensions.DependencyInjection.2.1.1.nupkg",
            "snupkg": "VMx.Extensions.DependencyInjection.2.1.1.snupkg",
        }
    ]


def test_build_manifest_rejects_tag_project_version_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "VMx" / "VMx.csproj"
    project.parent.mkdir()
    project.write_text(
        "<Project><PropertyGroup><PackageId>VMx</PackageId>"
        "<Version>3.22.1</Version></PropertyGroup></Project>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"declares 3\.22\.1"):
        selector.build_manifest("csharp-v3.22.0", tmp_path)


def test_main_writes_exact_single_package_manifest(tmp_path: Path) -> None:
    project_root = tmp_path / "projects"
    project = project_root / "VMx.Notifications" / "VMx.Notifications.csproj"
    project.parent.mkdir(parents=True)
    project.write_text(
        "<Project><PropertyGroup><PackageId>VMx.Notifications</PackageId>"
        "<Version>1.2.0</Version></PropertyGroup></Project>",
        encoding="utf-8",
    )
    output = tmp_path / "manifest.json"

    assert (
        selector.main(
            [
                "--tag",
                "csharp-notifications-v1.2.0",
                "--project-root",
                str(project_root),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))[0]["id"] == "VMx.Notifications"
