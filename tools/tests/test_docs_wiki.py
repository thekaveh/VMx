from pathlib import Path

import pytest
from docs.build_wiki import build, flattened_name, rewrite_links


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
