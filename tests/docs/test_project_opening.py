from __future__ import annotations

import shutil
from pathlib import Path
from statistics import median

import pytest
from PIL import Image
from scripts.docs import build_docs
from scripts.docs.check_docs import check_project_opening
from scripts.docs.manifest import load_manifest
from scripts.docs.opener import load_opener
from scripts.docs.transforms import build_source_map, rewrite_for_surface

ROOT = Path(__file__).resolve().parents[2]


def test_project_opening_matches_canonical_contract() -> None:
    opener = load_opener(ROOT / "docs/opener.yaml", ROOT)

    assert 100 <= len(opener.summary.split()) <= 150
    assert check_project_opening(ROOT) == []


@pytest.mark.parametrize(
    ("relative_path", "title"),
    [("README.md", "VMx"), ("docs/content/index.md", "1. VMx")],
)
def test_project_opening_uses_centered_poster_first_hierarchy(
    relative_path: str,
    title: str,
) -> None:
    opener = load_opener(ROOT / "docs/opener.yaml", ROOT)
    markdown = (ROOT / relative_path).read_text(encoding="utf-8")

    assert markdown.startswith('<p align="center">\n  <img ')
    assert f'<h1 align="center">{title}</h1>' in markdown
    assert f'<p align="center"><strong>{opener.tagline}</strong></p>' in markdown
    assert f'<p align="center">{opener.summary}</p>' in markdown


def test_readme_centers_badge_groups_and_uses_unnumbered_contents() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for label in ("Language builds", "Quality gates", "Delivery"):
        assert f'<p align="center">\n  <strong>{label}:</strong><br>' in readme
    assert "## Contents" in readme
    assert "## 0. Contents" not in readme


def test_project_poster_has_dark_edge_to_edge_canvas() -> None:
    with Image.open(ROOT / "assets/vmx-poster.png") as poster:
        poster = poster.convert("RGB")
        assert poster.size == (1600, 900)
        width, height = poster.size
        edge_pixels = [
            *(poster.getpixel((x, 0)) for x in range(width)),
            *(poster.getpixel((x, height - 1)) for x in range(width)),
            *(poster.getpixel((0, y)) for y in range(height)),
            *(poster.getpixel((width - 1, y)) for y in range(height)),
        ]

    corners = [
        poster.getpixel((0, 0)),
        poster.getpixel((width - 1, 0)),
        poster.getpixel((0, height - 1)),
        poster.getpixel((width - 1, height - 1)),
    ]
    median_edge = tuple(median(pixel[channel] for pixel in edge_pixels) for channel in range(3))

    assert max(max(pixel) for pixel in corners) <= 35
    assert max(median_edge) <= 12


def test_project_opening_rejects_punctuation_only_drift(tmp_path: Path) -> None:
    (tmp_path / "docs/content").mkdir(parents=True)
    (tmp_path / "assets").mkdir()
    shutil.copy2(ROOT / "docs/opener.yaml", tmp_path / "docs/opener.yaml")
    shutil.copy2(ROOT / "README.md", tmp_path / "README.md")
    shutil.copy2(ROOT / "docs/content/index.md", tmp_path / "docs/content/index.md")
    shutil.copy2(ROOT / "assets/vmx-poster.png", tmp_path / "assets/vmx-poster.png")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    (tmp_path / "README.md").write_text(
        readme.replace("idiomatic APIs.", "idiomatic APIs!", 1),
        encoding="utf-8",
    )

    findings = check_project_opening(tmp_path)

    assert any("canonical summary" in finding.message for finding in findings)


@pytest.mark.parametrize("surface", ["site", "wiki"])
def test_project_poster_path_is_local_to_generated_surface(surface: str) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source = Path("docs/content/index.md")
    source_map = build_source_map(manifest, surface)

    rendered = rewrite_for_surface(
        '<img src="../../assets/vmx-poster.png" alt="VMx">\n',
        surface=surface,
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert 'src="assets/vmx-poster.png"' in rendered


def test_project_poster_is_copied_byte_identically_to_generated_surfaces(
    tmp_path: Path,
) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    site = tmp_path / "site"
    wiki = tmp_path / "wiki"

    build_docs.render_site(manifest, site, ROOT)
    build_docs.render_wiki(manifest, wiki, ROOT)

    expected = (ROOT / "assets/vmx-poster.png").read_bytes()
    assert (site / "assets/vmx-poster.png").read_bytes() == expected
    assert (wiki / "assets/vmx-poster.png").read_bytes() == expected
