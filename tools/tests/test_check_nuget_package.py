"""Unit tests for tools/check-nuget-package.py."""

import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import check_nuget_package as checker
import pytest


def _nuspec(
    package_id: str,
    version: str,
    vmx_floor: str | None = None,
    *,
    symbols: bool = False,
    extra_dependency: str = "",
    framework_dependencies: dict[str, list[tuple[str, str]]] | None = None,
) -> str:
    def dependency_group(framework: str) -> str:
        dependencies = (
            [] if framework_dependencies is None else framework_dependencies.get(framework, [])
        )
        project_dependency = [] if vmx_floor is None else [("VMx", vmx_floor)]
        return (
            "".join(
                f'<dependency id="{dependency_id}" version="{dependency_version}" />'
                for dependency_id, dependency_version in project_dependency + dependencies
            )
            + extra_dependency
        )

    main_metadata = (
        ""
        if symbols
        else '<authors>Kaveh Razavi</authors><license type="expression">Apache-2.0</license>'
        "<readme>README.md</readme>"
    )
    package_type = (
        '<packageTypes><packageType name="SymbolsPackage" /></packageTypes>' if symbols else ""
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">
  <metadata>
    <id>{package_id}</id><version>{version}</version>{main_metadata}
    <projectUrl>https://github.com/thekaveh/VMx</projectUrl>
    <description>VMx package.</description><tags>mvvm reactive</tags>
    {package_type}
    <repository type="git" url="https://github.com/thekaveh/VMx" commit="{"a" * 40}" />
    <dependencies>
      <group targetFramework="net8.0">{dependency_group("net8.0")}</group>
      <group targetFramework=".NETStandard2.0">{dependency_group(".NETStandard2.0")}</group>
    </dependencies>
  </metadata>
</package>"""


def _write_packages(
    root: Path,
    package_id: str,
    version: str,
    vmx_floor: str | None = None,
    *,
    unexpected: str | None = None,
    extra_dependency: str = "",
    symlink_path: str | None = None,
    framework_dependencies: dict[str, list[tuple[str, str]]] | None = None,
) -> None:
    if framework_dependencies is None:
        framework_dependencies = checker._PACKAGE_DEPENDENCIES.get(package_id, {})
    main_paths = checker.expected_paths(package_id, symbols=False)
    symbol_paths = checker.expected_paths(package_id, symbols=True)
    main = root / f"{package_id}.{version}.nupkg"
    symbols = root / f"{package_id}.{version}.snupkg"
    for archive, paths in ((main, main_paths), (symbols, symbol_paths)):
        with ZipFile(archive, "w", ZIP_DEFLATED) as package:
            for path in paths:
                if path == "<core-properties>":
                    path = "package/services/metadata/core-properties/a.psmdcp"
                if path.endswith(".nuspec"):
                    package.writestr(
                        path,
                        _nuspec(
                            package_id,
                            version,
                            vmx_floor,
                            symbols=archive == symbols,
                            extra_dependency=extra_dependency,
                            framework_dependencies=framework_dependencies,
                        ),
                    )
                elif path == symlink_path and archive == main:
                    info = ZipInfo(path)
                    info.create_system = 3
                    info.external_attr = stat.S_IFLNK << 16
                    package.writestr(info, "../../outside")
                else:
                    package.writestr(path, b"content")
            if unexpected and archive == main:
                package.writestr(unexpected, b"secret")


def test_validate_package_pair_accepts_exact_assets_and_dependency_floor(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx.Notifications", "1.2.0", "3.20.0")

    assert checker.validate_package_pair(tmp_path, "VMx.Notifications", "1.2.0", "3.20.0") == []


def test_validate_package_pair_accepts_exact_public_dependency_contract(tmp_path: Path) -> None:
    dependencies = {
        "net8.0": [("System.Reactive", "7.0.0")],
        ".NETStandard2.0": [
            ("Microsoft.Bcl.AsyncInterfaces", "8.0.0"),
            ("System.Collections.Immutable", "10.0.10"),
            ("System.Reactive", "7.0.0"),
            ("System.Text.Json", "8.0.6"),
        ],
    }
    _write_packages(
        tmp_path,
        "VMx",
        "3.22.1",
        framework_dependencies=dependencies,
    )

    assert checker.validate_package_pair(tmp_path, "VMx", "3.22.1", None) == []


def test_main_packages_include_legal_texts_but_symbol_packages_do_not() -> None:
    assert {"LICENSE", "NOTICE"} <= checker.expected_paths("VMx", symbols=False)
    assert {"LICENSE", "NOTICE"}.isdisjoint(checker.expected_paths("VMx", symbols=True))


def test_validate_package_pair_rejects_unexpected_content(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx", "3.20.0", unexpected="secrets.txt")

    errors = checker.validate_package_pair(tmp_path, "VMx", "3.20.0", None)

    assert "VMx.3.20.0.nupkg: unexpected package file: secrets.txt" in errors


def test_validate_package_pair_rejects_wrong_companion_floor(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx.Extensions.DependencyInjection", "2.1.1", "3.19.0")

    errors = checker.validate_package_pair(
        tmp_path, "VMx.Extensions.DependencyInjection", "2.1.1", "3.20.0"
    )

    assert any(
        "dependencies must be exactly" in error
        and "('VMx', '3.20.0')" in error
        and "('VMx', '3.19.0')" in error
        for error in errors
    )


@pytest.mark.parametrize("vmx_floor", [None, "3.20.0"])
def test_validate_package_pair_rejects_additional_dependencies(
    tmp_path: Path, vmx_floor: str | None
) -> None:
    package_id = "VMx" if vmx_floor is None else "VMx.Notifications"
    _write_packages(
        tmp_path,
        package_id,
        "1.2.0",
        vmx_floor,
        extra_dependency='<dependency id="Unexpected.Dependency" version="[9.0.0]" />',
    )

    errors = checker.validate_package_pair(tmp_path, package_id, "1.2.0", vmx_floor)

    assert any("dependencies must be exactly" in error for error in errors)


def test_validate_package_pair_reports_missing_dependency_attributes(tmp_path: Path) -> None:
    _write_packages(
        tmp_path,
        "VMx",
        "3.22.1",
        extra_dependency='<dependency id="System.Reactive" />',
    )

    errors = checker.validate_package_pair(tmp_path, "VMx", "3.22.1", None)

    assert any("dependencies must be exactly" in error for error in errors)


def test_validate_package_pair_rejects_duplicate_archive_members(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx", "3.20.0")
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(tmp_path / "VMx.3.20.0.nupkg", "a", ZIP_DEFLATED) as package:
            package.writestr("README.md", b"replacement")

    errors = checker.validate_package_pair(tmp_path, "VMx", "3.20.0", None)

    assert "VMx.3.20.0.nupkg: duplicate package file: README.md" in errors


def test_validate_package_pair_rejects_symbolic_link_members(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx", "3.20.0", symlink_path="README.md")

    errors = checker.validate_package_pair(tmp_path, "VMx", "3.20.0", None)

    assert "VMx.3.20.0.nupkg: symbolic links are forbidden: README.md" in errors


def test_validate_package_pair_requires_one_core_properties_member(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx", "3.20.0")
    with ZipFile(tmp_path / "VMx.3.20.0.nupkg", "a", ZIP_DEFLATED) as package:
        package.writestr(
            "package/services/metadata/core-properties/b.psmdcp",
            b"duplicate metadata",
        )

    errors = checker.validate_package_pair(tmp_path, "VMx", "3.20.0", None)

    assert "VMx.3.20.0.nupkg: expected exactly one core-properties metadata file" in errors


def test_discover_expected_reads_all_packable_projects(tmp_path: Path) -> None:
    for package_id, version in (("VMx", "3.20.0"), ("VMx.Notifications", "1.2.0")):
        project = tmp_path / package_id / f"{package_id}.csproj"
        project.parent.mkdir()
        project.write_text(
            f"<Project><PropertyGroup><PackageId>{package_id}</PackageId>"
            f"<Version>{version}</Version></PropertyGroup></Project>",
            encoding="utf-8",
        )

    assert checker.discover_expected(tmp_path) == {
        "VMx": ("3.20.0", None),
        "VMx.Notifications": ("1.2.0", "3.20.0"),
    }


def test_main_rejects_project_root_without_packable_projects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package_dir = tmp_path / "packages"
    package_dir.mkdir()

    result = checker.main(
        ["--package-dir", str(package_dir), "--project-root", str(tmp_path / "missing")]
    )

    assert result == 1
    assert "no packable projects discovered" in capsys.readouterr().err
