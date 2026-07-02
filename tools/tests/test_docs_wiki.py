from pathlib import Path

import pytest
from docs.build_wiki import build, flattened_name, rewrite_links, validate_markdown_links


def test_flattened_name_preserves_special_pages(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    root.mkdir()

    assert flattened_name(root / "Home.md", root) == "Home.md"
    assert flattened_name(root / "_Sidebar.md", root) == "_Sidebar.md"
    assert flattened_name(root / "_Footer.md", root) == "_Footer.md"


def test_flattened_name_encodes_hierarchy(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    page = root / "Framework-Primitives" / "ViewModel-Families" / "Composite-Family.md"

    assert (
        flattened_name(page, root) == "Framework-Primitives-ViewModel-Families-Composite-Family.md"
    )


def test_rewrite_links_rejects_missing_page() -> None:
    with pytest.raises(ValueError, match="missing page"):
        rewrite_links("[[Missing]]", {"Home"})


def test_build_raises_for_missing_link_in_source(tmp_path: Path) -> None:
    source = tmp_path / "wiki"
    out = tmp_path / "out"
    source.mkdir()

    (source / "Home.md").write_text("# Home\n\n[[Missing]]\n", encoding="utf-8")
    (source / "_Sidebar.md").write_text("- [[Home]]\n", encoding="utf-8")
    (source / "_Footer.md").write_text("Footer\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing page"):
        build(source, out)


def test_validate_markdown_links_rejects_source_markdown_links() -> None:
    with pytest.raises(ValueError, match="source markdown file"):
        validate_markdown_links("[Quickstart](../../site/quickstart.md)", Path("docs/wiki/Home.md"))


def test_validate_markdown_links_rejects_reference_source_markdown_links() -> None:
    with pytest.raises(ValueError, match="source markdown file"):
        validate_markdown_links("[quickstart]: ../../site/quickstart.md", Path("docs/wiki/Home.md"))


def test_validate_markdown_links_rejects_indented_reference_source_markdown_links() -> None:
    with pytest.raises(ValueError, match="source markdown file"):
        validate_markdown_links(
            "   [quickstart]: ../../site/quickstart.md", Path("docs/wiki/Home.md")
        )


def test_validate_markdown_links_rejects_angle_reference_source_markdown_links() -> None:
    with pytest.raises(ValueError, match="source markdown file"):
        validate_markdown_links(
            "[quickstart]: <../../site/quickstart.md>", Path("docs/wiki/Home.md")
        )


def test_validate_markdown_links_allows_public_urls_and_diagram_assets() -> None:
    validate_markdown_links(
        "[Quickstart](https://thekaveh.github.io/VMx/quickstart/)\n"
        "![Diagram](../../assets/diagrams/system-architecture.png)\n",
        Path("docs/wiki/Home.md"),
    )


def test_build_rewrites_hierarchical_links_to_flattened_targets(tmp_path: Path) -> None:
    source = tmp_path / "wiki"
    out = tmp_path / "out"
    source.mkdir()
    (source / "Architecture").mkdir(parents=True)
    (source / "Home.md").write_text(
        "# Home\n\n[[Architecture Map|Architecture/Architecture-Map]]\n",
        encoding="utf-8",
    )
    (source / "_Sidebar.md").write_text("- [[Home]]\n", encoding="utf-8")
    (source / "_Footer.md").write_text("Footer\n", encoding="utf-8")
    (source / "Architecture" / "Architecture-Map.md").write_text(
        "# Architecture Map\n",
        encoding="utf-8",
    )

    written = build(source, out)

    assert out / "Architecture-Architecture-Map.md" in written
    assert (out / "Home.md").read_text(encoding="utf-8") == (
        "# Home\n\n[[Architecture Map|Architecture-Architecture-Map]]\n"
    )


def test_build_rewrites_diagram_asset_links_for_flattened_pages(tmp_path: Path) -> None:
    source = tmp_path / "wiki"
    out = tmp_path / "out"
    source.mkdir()
    (source / "Framework-Primitives" / "ViewModel-Families").mkdir(parents=True)
    (source / "Home.md").write_text("# Home\n", encoding="utf-8")
    (source / "_Sidebar.md").write_text("- [[Home]]\n", encoding="utf-8")
    (source / "_Footer.md").write_text("Footer\n", encoding="utf-8")
    (source / "Framework-Primitives" / "ViewModel-Families" / "Composite-Family.md").write_text(
        "# Composite Family\n\n"
        "![Composite Family](../../assets/diagrams/composite-family.png)\n\n"
        "[SVG](../../assets/diagrams/composite-family.svg)\n",
        encoding="utf-8",
    )

    build(source, out)

    assert (out / "Framework-Primitives-ViewModel-Families-Composite-Family.md").read_text(
        encoding="utf-8"
    ) == (
        "# Composite Family\n\n"
        "![Composite Family](assets/diagrams/composite-family.png)\n\n"
        "[SVG](assets/diagrams/composite-family.svg)\n"
    )
