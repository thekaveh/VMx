"""Unit tests for tools/check-nuget-package.py."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import check_nuget_package as checker


def _nuspec(
    package_id: str, version: str, vmx_floor: str | None = None, *, symbols: bool = False
) -> str:
    dependency = "" if vmx_floor is None else f'<dependency id="VMx" version="{vmx_floor}" />'
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
      <group targetFramework="net8.0">{dependency}</group>
      <group targetFramework=".NETStandard2.0">{dependency}</group>
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
) -> None:
    main_paths = checker.expected_paths(package_id, symbols=False)
    symbol_paths = checker.expected_paths(package_id, symbols=True)
    main = root / f"{package_id}.{version}.nupkg"
    symbols = root / f"{package_id}.{version}.snupkg"
    for archive, paths in ((main, main_paths), (symbols, symbol_paths)):
        with ZipFile(archive, "w", ZIP_DEFLATED) as package:
            for path in paths:
                if path.endswith(".nuspec"):
                    package.writestr(
                        path,
                        _nuspec(package_id, version, vmx_floor, symbols=archive == symbols),
                    )
                else:
                    package.writestr(path, b"content")
            if unexpected and archive == main:
                package.writestr(unexpected, b"secret")


def test_validate_package_pair_accepts_exact_assets_and_dependency_floor(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx.Notifications", "1.2.0", "3.20.0")

    assert checker.validate_package_pair(tmp_path, "VMx.Notifications", "1.2.0", "3.20.0") == []


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

    assert any("VMx dependency must be exactly 3.20.0" in error for error in errors)


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
