"""Unit tests for tools/check-nuget-package.py."""

import shutil
import stat
import subprocess
import time
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
    core_properties_name: str = "a.psmdcp",
    framework_dependencies: dict[str, list[tuple[str, str]]] | None = None,
    readme: str | None = None,
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
                    path = f"package/services/metadata/core-properties/{core_properties_name}"
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
                elif path == "README.md":
                    package.writestr(path, readme or f"# {package_id}\n\nPackage.\n")
                else:
                    package.writestr(path, b"content")
            if unexpected and archive == main:
                package.writestr(unexpected, b"secret")


def test_validate_package_pair_accepts_exact_assets_and_dependency_floor(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx.Notifications", "1.2.0", "3.20.0")

    assert checker.validate_package_pair(tmp_path, "VMx.Notifications", "1.2.0", "3.20.0") == []


def test_validate_package_pair_accepts_nuget_named_core_properties(tmp_path: Path) -> None:
    _write_packages(
        tmp_path,
        "VMx",
        "3.20.0",
        core_properties_name="nuget.psmdcp",
    )

    assert checker.validate_package_pair(tmp_path, "VMx", "3.20.0", None) == []


def test_validate_package_pair_accepts_exact_public_dependency_contract(tmp_path: Path) -> None:
    dependencies = {
        "net8.0": [("System.Reactive", "7.0.0")],
        ".NETStandard2.0": [
            ("Microsoft.Bcl.AsyncInterfaces", "10.0.14"),
            ("System.Collections.Immutable", "10.0.14"),
            ("System.Reactive", "7.0.0"),
            ("System.Text.Json", "10.0.14"),
        ],
    }
    _write_packages(
        tmp_path,
        "VMx",
        "3.22.1",
        framework_dependencies=dependencies,
    )

    assert checker.validate_package_pair(tmp_path, "VMx", "3.22.1", None) == []


def test_validate_package_pair_accepts_current_di_dependency_contract(tmp_path: Path) -> None:
    dependencies = {
        "net8.0": [
            ("Microsoft.Extensions.DependencyInjection.Abstractions", "10.0.14"),
            ("System.Reactive", "7.0.0"),
        ],
        ".NETStandard2.0": [
            ("Microsoft.Bcl.AsyncInterfaces", "10.0.14"),
            ("Microsoft.Extensions.DependencyInjection.Abstractions", "10.0.14"),
            ("System.Collections.Immutable", "10.0.14"),
            ("System.Reactive", "7.0.0"),
            ("System.Text.Json", "10.0.14"),
        ],
    }
    _write_packages(
        tmp_path,
        "VMx.Extensions.DependencyInjection",
        "2.1.1",
        "3.23.0",
        framework_dependencies=dependencies,
    )

    assert (
        checker.validate_package_pair(
            tmp_path, "VMx.Extensions.DependencyInjection", "2.1.1", "3.23.0"
        )
        == []
    )


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


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "package_id", ["VMx", "VMx.Notifications", "VMx.Extensions.DependencyInjection"]
)
def test_shipped_package_readmes_render_outside_the_repository(package_id: str) -> None:
    readme = REPO_ROOT / "langs/csharp/packaging" / package_id / "README.md"

    assert checker.validate_readme(readme.read_text(encoding="utf-8"), package_id) == []


@pytest.mark.parametrize("package_id", ["VMx.Notifications", "VMx.Extensions.DependencyInjection"])
def test_companion_readmes_state_their_vmx_dependency(package_id: str) -> None:
    readme = (REPO_ROOT / "langs/csharp/packaging" / package_id / "README.md").read_text(
        encoding="utf-8"
    )

    assert "depends on `VMx`" in readme
    assert "https://www.nuget.org/packages/VMx)" in readme


def test_repository_root_readme_would_be_rejected_as_a_package_readme() -> None:
    errors = checker.validate_readme((REPO_ROOT / "README.md").read_text(encoding="utf-8"), "VMx")

    assert any(
        error.startswith("README uses raw HTML, which nuget.org does not render: <img")
        and "assets/vmx-poster.png" in error
        for error in errors
    )
    assert any("docs/content/getting-started/csharp.md" in error for error in errors)


def test_every_packable_project_packs_its_own_readme() -> None:
    props = (REPO_ROOT / "langs/csharp/Directory.Build.props").read_text(encoding="utf-8")

    assert "packaging\\$(MSBuildProjectName)\\README.md" in props
    assert "..\\..\\README.md" not in props
    for project in sorted((REPO_ROOT / "langs/csharp/src").glob("*/*.csproj")):
        assert (REPO_ROOT / "langs/csharp/packaging" / project.stem / "README.md").is_file()


@pytest.mark.parametrize(
    ("readme", "error"),
    [
        (
            '# VMx\n\n<img src="assets/vmx-poster.png">\n',
            "README uses raw HTML, which nuget.org does not render: "
            '<img src="assets/vmx-poster.png">',
        ),
        (
            "# VMx\n\n![diagram](assets/architecture.svg)\n",
            "README image must be an absolute https URL: assets/architecture.svg",
        ),
        (
            "# VMx\n\n[guide](docs/content/getting-started/csharp.md)\n",
            "README link must be an absolute https URL: docs/content/getting-started/csharp.md",
        ),
        (
            "# VMx\n\n[guide][ref]\n\n[ref]: ../langs/rust/README.md\n",
            "README link must be an absolute https URL: ../langs/rust/README.md",
        ),
        (
            "# VMx\n\n[site](http://thekaveh.github.io/VMx/)\n",
            "README link must be an absolute https URL: http://thekaveh.github.io/VMx/",
        ),
        (
            "# VMx\n\n![badge](https://example.com/badge.png)\n",
            "README image host is not allowed: https://example.com/badge.png",
        ),
        (
            "# VMx\n\n![diagram](https://raw.githubusercontent.com/thekaveh/VMx/main/a.svg)\n",
            "README image must be PNG, JPEG, or GIF: "
            "https://raw.githubusercontent.com/thekaveh/VMx/main/a.svg",
        ),
        ("# Something else\n", "README must open with the heading '# VMx'"),
    ],
)
def test_validate_readme_rejects_unresolvable_content(readme: str, error: str) -> None:
    assert error in checker.validate_readme(readme, "VMx")


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            "[![ci](https://img.shields.io/x.svg)](https://example.com)",
            "README image host is not allowed: https://img.shields.io/x.svg",
        ),
        (
            "[![ci](https://raw.githubusercontent.com/a/b.png)](docs/index.md)",
            "README link must be an absolute https URL: docs/index.md",
        ),
        (
            "![p][r]\n\n[r]: https://example.com/poster.png",
            "README image host is not allowed: https://example.com/poster.png",
        ),
        (
            "![p][r]\n\n[r]: https://raw.githubusercontent.com/a/p.svg",
            "README image must be PNG, JPEG, or GIF: https://raw.githubusercontent.com/a/p.svg",
        ),
        (
            "[docs](docs/index.md 'Docs')",
            "README link must be an absolute https URL: docs/index.md",
        ),
        (
            "![p](assets/p.png (P))",
            "README image must be an absolute https URL: assets/p.png",
        ),
    ],
    ids=[
        "linked-image-off-host",
        "linked-image-relative-target",
        "reference-image-off-host",
        "reference-image-svg",
        "single-quoted-title",
        "parenthesized-title",
    ],
)
def test_validate_readme_reads_every_commonmark_target_form(body: str, error: str) -> None:
    # #785: each form gave no error before.
    assert checker.validate_readme(f"# VMx\n\n{body}\n", "VMx") == [error]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            "Indices in [0, count) are valid.\n\nSee [guide](docs/guide.md).",
            "README link must be an absolute https URL: docs/guide.md",
        ),
        (
            "See [x][r].\n\n[r]:\n  docs/a.md",
            "README link must be an absolute https URL: docs/a.md",
        ),
        (
            "![p](assets/a_((b)).png)",
            "README image must be an absolute https URL: assets/a_((b)).png",
        ),
    ],
    ids=["after-unmatched-bracket", "definition-on-next-line", "nested-parentheses"],
)
def test_validate_readme_keeps_reading_past_unusual_markdown(body: str, error: str) -> None:
    # #785 review: the old regex caught each of these.
    assert checker.validate_readme(f"# VMx\n\n{body}\n", "VMx") == [error]


def test_validate_readme_ignores_code_and_accepts_absolute_targets() -> None:
    readme = (
        "# VMx\n\n"
        "![poster](https://raw.githubusercontent.com/thekaveh/VMx/main/assets/vmx-poster.png)\n"
        "[docs](https://thekaveh.github.io/VMx/) and [top](#vmx).\n\n"
        "```csharp\nvar x = items[0](value); // [not](a/link)\n```\n"
        "Inline `[code](relative.md)` is ignored.\n"
    )

    assert checker.validate_readme(readme, "VMx") == []


def test_validate_package_pair_rejects_a_repository_relative_readme(tmp_path: Path) -> None:
    _write_packages(tmp_path, "VMx", "3.20.0", readme="# VMx\n\n![poster](assets/vmx-poster.png)\n")

    assert checker.validate_package_pair(tmp_path, "VMx", "3.20.0", None) == [
        "VMx.3.20.0.nupkg: README image must be an absolute https URL: assets/vmx-poster.png"
    ]


_RAW_HTML_ERROR = "README uses raw HTML, which nuget.org does not render: "


@pytest.mark.parametrize(
    ("body", "tag"),
    [
        (
            '<img src="https://raw.githubusercontent.com/thekaveh/VMx/main/assets/vmx-poster.png">',
            '<img src="https://raw.githubusercontent.com/thekaveh/VMx/main/assets/vmx-poster.png">',
        ),
        (
            "<a href=https://thekaveh.github.io/VMx/>docs</a>",
            "<a href=https://thekaveh.github.io/VMx/>",
        ),
        ("Line one<br/>line two", "<br/>"),
        ("<details open\n  class='x'>", "<details open class='x'>"),
        ("<!-- hidden note -->", "<!-- hidden note -->"),
        ("Store a List<T> here.", "<T>"),
    ],
    ids=["absolute-image", "unquoted-anchor", "self-closing", "multi-line", "comment", "generic"],
)
def test_validate_readme_rejects_raw_html(body: str, tag: str) -> None:
    # #351: nuget.org renders Markdown without raw HTML; the checker accepted
    # an HTML image or link whose target was an absolute https URL.
    errors = checker.validate_readme(f"# VMx\n\n{body}\n", "VMx")

    assert f"{_RAW_HTML_ERROR}{tag}" in errors


def test_validate_readme_reports_each_raw_html_tag() -> None:
    errors = checker.validate_readme("# VMx\n\n<p>text</p>\n", "VMx")

    assert errors == [f"{_RAW_HTML_ERROR}<p>", f"{_RAW_HTML_ERROR}</p>"]


@pytest.mark.parametrize(
    "body",
    [
        "Inline `<img src=x>` is code.",
        "```html\n<div class='x'></div>\n```",
        "See <https://thekaveh.github.io/VMx/> for docs.",
        "Escaped \\<div> is text.",
        "A comparison: 1 < 2 and 3 > 2.",
        "    var x = new List<int>();",
        "``List<T>`` and ``a ` <b> ``",
        " ```cs\n var x = new List<int>();\n ```",
        "  ```cs\n  var x = new List<int>();\n  ```",
        "   ~~~\n   List<T>\n   ~~~",
        '[a](https://example.com "<b>x</b>")',
        "[a][r]\n\n[r]: https://example.com '<b>x</b>'",
        "- item\n\n  ```cs\n  List<T>\n  ```",
        "- item\n\n      List<T>",
    ],
    ids=[
        "inline-code",
        "fenced-code",
        "autolink",
        "escaped",
        "comparison",
        "indented-code",
        "double-backtick-span",
        "fence-indented-one",
        "fence-indented-two",
        "tilde-fence-indented-three",
        "link-title",
        "definition-title",
        "fence-in-list",
        "indented-code-in-list",
    ],
)
def test_validate_readme_accepts_markdown_that_is_not_raw_html(body: str) -> None:
    assert checker.validate_readme(f"# VMx\n\n{body}\n", "VMx") == []


@pytest.mark.parametrize(
    ("body", "tag"),
    [
        ("Text\n    List<T> continues the paragraph.", "<T>"),
        ("- item\n\n    List<T> is list text.", "<T>"),
        ("    ```\n    code\n    ```\n\nAfter <b>x</b>", "<b>"),
        ("```\ncode\n```\n\nAfter <b>x</b>", "<b>"),
        ("Unmatched ``List<T>` run.", "<T>"),
        ("`a\n\n<b>` crosses a blank line.", "<b>"),
        ('[a](https://example.com "t") then <b>x</b>', "<b>"),
    ],
    ids=[
        "paragraph-continuation",
        "list-paragraph",
        "after-indented-code",
        "after-fence",
        "unmatched-backticks",
        "span-across-blank-line",
        "after-link-title",
    ],
)
def test_validate_readme_still_rejects_raw_html_outside_code(body: str, tag: str) -> None:
    errors = checker.validate_readme(f"# VMx\n\n{body}\n", "VMx")

    assert f"{_RAW_HTML_ERROR}{tag}" in errors


@pytest.mark.parametrize("opener", ["<!-- ", "<? "])
def test_validate_readme_scans_unterminated_openers_in_linear_time(opener: str) -> None:
    # #1439: each unterminated opener used to scan to the end of the text.
    readme = "# VMx\n\n" + opener * 50_000 + "\n"

    started = time.perf_counter()
    errors = checker.validate_readme(readme, "VMx")
    elapsed = time.perf_counter() - started

    assert errors == []
    assert elapsed < 1.0, f"{elapsed:.2f} s"


def test_validate_readme_applies_link_rules_to_autolinks() -> None:
    assert checker.validate_readme("# VMx\n\n<http://thekaveh.github.io/VMx/>\n", "VMx") == [
        "README link must be an absolute https URL: http://thekaveh.github.io/VMx/"
    ]


def test_validate_readme_reads_an_angle_bracket_destination_once() -> None:
    assert checker.validate_readme("# VMx\n\n[guide](<http://example.com/a>)\n", "VMx") == [
        "README link must be an absolute https URL: http://example.com/a"
    ]


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "content").mkdir(parents=True)
    (tmp_path / "docs" / "content" / "Guide One.md").write_text("guide", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "poster.png").write_bytes(b"png")
    (tmp_path / "LICENSE").write_text("license", encoding="utf-8")
    return tmp_path


_BLOB = "https://github.com/thekaveh/VMx/blob/main/"
_TREE = "https://github.com/thekaveh/VMx/tree/main/"
_RAW = "https://raw.githubusercontent.com/thekaveh/VMx/main/"


@pytest.mark.parametrize(
    "body",
    [
        f"[guide]({_BLOB}docs/content/Guide%20One.md#usage)",
        f"[docs]({_TREE}docs/content)",
        f"[docs]({_TREE}docs/content/)",
        "[repo](https://github.com/thekaveh/VMx/tree/main)",
        f"![poster]({_RAW}assets/poster.png)",
        "[poster](https://github.com/thekaveh/VMx/raw/main/assets/poster.png?raw=1)",
        "[license][l]\n\n[l]: https://github.com/TheKaveh/vmx/blob/main/LICENSE",
        f"[old]({_BLOB.replace('/main/', '/v1.0.0/')}missing.md)",
        "[other](https://github.com/someone/else/blob/main/missing.md)",
        "[guide](https://www.github.com/thekaveh/VMx/blob/main/docs/content/Guide%20One.md)",
        "[guide](https://github.com/thekaveh/VMx/blob/HEAD/docs/content/Guide%20One.md)",
        "[docs](https://github.com/thekaveh/VMx/tree/refs/heads/main/docs/content)",
        "![p](https://raw.githubusercontent.com/thekaveh/VMx/HEAD/assets/poster.png)",
        "![p](https://raw.githubusercontent.com/thekaveh/VMx/refs/heads/main/assets/poster.png)",
        f"[guide]({_BLOB}assets/../docs/./content/Guide%20One.md)",
        "[clone](https://github.com/thekaveh/VMx.git)",
    ],
    ids=[
        "encoded-file-with-fragment",
        "directory",
        "directory-trailing-slash",
        "repository-root",
        "raw-image",
        "raw-route-with-query",
        "case-insensitive-owner",
        "other-ref-not-checked",
        "other-repository-not-checked",
        "www-host",
        "blob-head",
        "tree-refs-heads-main",
        "raw-head",
        "raw-refs-heads-main",
        "dot-segments-resolved",
        "clone-url-without-a-path",
    ],
)
def test_validate_readme_accepts_repository_paths_present_in_the_tree(
    body: str, repo_root: Path
) -> None:
    assert checker.validate_readme(f"# VMx\n\n{body}\n", "VMx", repo_root=repo_root) == []


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            f"[guide]({_BLOB}docs/content/moved.md)",
            f"README link names a path missing from the checked-out tree: "
            f"{_BLOB}docs/content/moved.md",
        ),
        (
            f"[guide]({_BLOB}docs/content/guide%20one.md)",
            f"README link names a path missing from the checked-out tree: "
            f"{_BLOB}docs/content/guide%20one.md",
        ),
        (
            f"[license]({_TREE}LICENSE)",
            f"README link names a path missing from the checked-out tree: {_TREE}LICENSE",
        ),
        (
            f"[docs]({_BLOB}docs)",
            f"README link names a path missing from the checked-out tree: {_BLOB}docs",
        ),
        (
            f"![poster]({_RAW}assets/old-poster.png)",
            f"README image names a path missing from the checked-out tree: "
            f"{_RAW}assets/old-poster.png",
        ),
        (
            f"[guide][g]\n\n[g]: {_BLOB}docs/gone.md",
            f"README link names a path missing from the checked-out tree: {_BLOB}docs/gone.md",
        ),
        (
            f"See <{_BLOB}docs/gone.md>.",
            f"README link names a path missing from the checked-out tree: {_BLOB}docs/gone.md",
        ),
        (
            "[g](https://www.github.com/thekaveh/VMx/blob/main/docs/gone.md)",
            "README link names a path missing from the checked-out tree: "
            "https://www.github.com/thekaveh/VMx/blob/main/docs/gone.md",
        ),
        (
            "[g](https://github.com/thekaveh/VMx/blob/HEAD/docs/gone.md)",
            "README link names a path missing from the checked-out tree: "
            "https://github.com/thekaveh/VMx/blob/HEAD/docs/gone.md",
        ),
        (
            "[g](https://github.com/thekaveh/VMx/blob/refs/heads/main/docs/gone.md)",
            "README link names a path missing from the checked-out tree: "
            "https://github.com/thekaveh/VMx/blob/refs/heads/main/docs/gone.md",
        ),
        (
            "![p](https://raw.githubusercontent.com/thekaveh/VMx/HEAD/assets/gone.png)",
            "README image names a path missing from the checked-out tree: "
            "https://raw.githubusercontent.com/thekaveh/VMx/HEAD/assets/gone.png",
        ),
        (
            "[g](https://github.com/thekaveh/VMx.git/blob/main/LICENSE)",
            "README link uses a VMx.git path, which GitHub does not serve: "
            "https://github.com/thekaveh/VMx.git/blob/main/LICENSE",
        ),
        (
            f"[g]({_BLOB}docs/../../LICENSE)",
            f"README link names a path above the repository root: {_BLOB}docs/../../LICENSE",
        ),
        (
            f"[g]({_BLOB}assets/../docs/gone.md)",
            "README link names a path missing from the checked-out tree: "
            f"{_BLOB}assets/../docs/gone.md",
        ),
    ],
    ids=[
        "missing-file",
        "wrong-case",
        "tree-names-a-file",
        "blob-names-a-directory",
        "missing-raw-image",
        "reference-definition",
        "autolink",
        "www-host",
        "blob-head",
        "blob-refs-heads-main",
        "raw-head",
        "dot-git-repository",
        "above-repository-root",
        "dot-segments-resolved",
    ],
)
def test_validate_readme_rejects_repository_paths_missing_from_the_tree(
    body: str, error: str, repo_root: Path
) -> None:
    # #351: a published README cannot change, so a renamed or moved file
    # would leave a dangling link on nuget.org with no CI signal.
    assert checker.validate_readme(f"# VMx\n\n{body}\n", "VMx", repo_root=repo_root) == [error]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, timeout=30
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="requires git")
def test_validate_readme_requires_tracked_paths_in_a_git_work_tree(repo_root: Path) -> None:
    _git(repo_root, "init", "-q")
    (repo_root / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(repo_root, "add", ".gitignore", "docs", "LICENSE")
    (repo_root / "build").mkdir()
    (repo_root / "build" / "out.md").write_text("ignored", encoding="utf-8")
    body = (
        f"[guide]({_BLOB}docs/content/Guide%20One.md) [docs]({_TREE}docs/content) "
        f"[license]({_BLOB}LICENSE) [repo](https://github.com/thekaveh/VMx/tree/main)\n"
        f"![untracked]({_RAW}assets/poster.png) [ignored]({_BLOB}build/out.md) "
        f"[ignored-dir]({_TREE}build)"
    )

    assert checker.validate_readme(f"# VMx\n\n{body}\n", "VMx", repo_root=repo_root) == [
        f"README image names a path missing from the checked-out tree: {_RAW}assets/poster.png",
        f"README link names a path missing from the checked-out tree: {_BLOB}build/out.md",
        f"README link names a path missing from the checked-out tree: {_TREE}build",
    ]


def test_main_resolves_readme_paths_against_the_repo_root_argument(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "src" / "VMx" / "VMx.csproj"
    project.parent.mkdir(parents=True)
    project.write_text(
        "<Project><PropertyGroup><PackageId>VMx</PackageId>"
        "<Version>3.20.0</Version></PropertyGroup></Project>",
        encoding="utf-8",
    )
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    _write_packages(
        package_dir,
        "VMx",
        "3.20.0",
        readme=f"# VMx\n\n[guide]({_BLOB}docs/content/Guide%20One.md)\n",
    )
    arguments = ["--package-dir", str(package_dir), "--project-root", str(tmp_path / "src")]

    assert checker.main([*arguments, "--repo-root", str(repo_root)]) == 0
    assert checker.main(arguments) == 1
    assert (
        "ERROR: VMx.3.20.0.nupkg: README link names a path missing from the checked-out tree: "
        f"{_BLOB}docs/content/Guide%20One.md"
    ) in capsys.readouterr().err


def test_validate_readme_checks_this_checkout_by_default() -> None:
    url = f"{_BLOB}docs/content/getting-started/not-a-page.md"

    assert checker.validate_readme(f"# VMx\n\n[guide]({url})\n", "VMx") == [
        f"README link names a path missing from the checked-out tree: {url}"
    ]
