from __future__ import annotations

import re
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

    expected_parts = (
        '<p align="center">\n  <img ',
        f'<h1 align="center">{title}</h1>',
        "<!-- vmx-opener:start -->",
        f'<p align="center"><strong>{opener.tagline}</strong></p>',
        f'<p align="center">{opener.summary}</p>',
        "<!-- vmx-opener:end -->",
    )
    positions = [markdown.index(part) for part in expected_parts]

    assert positions == sorted(positions)
    assert positions[0] == 0


def test_readme_centers_badge_groups_and_uses_unnumbered_contents() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    expected_targets = {
        "Language builds": (
            "https://github.com/thekaveh/VMx/actions/workflows/csharp.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/python.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/typescript.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/swift.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/rust.yml",
        ),
        "Quality gates": (
            "https://github.com/thekaveh/VMx/actions/workflows/conformance.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/spec-discipline.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/examples-contract-checks.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/docs.yml",
            "https://github.com/thekaveh/VMx/actions/workflows/security-audit.yml",
        ),
        "Delivery": (
            "https://github.com/thekaveh/VMx/actions/workflows/release.yml",
            "LICENSE",
        ),
    }
    for label, targets in expected_targets.items():
        match = re.search(
            rf'<p align="center">\n  <strong>{re.escape(label)}:</strong><br>(?P<badges>.*?)\n</p>',
            readme,
            re.DOTALL,
        )
        assert match is not None
        assert re.findall(r'<a href="([^"]+)"><img ', match.group("badges")) == list(targets)
    assert "## Contents" in readme
    assert "## 0. Contents" not in readme


def test_project_poster_has_dark_edge_to_edge_canvas() -> None:
    with Image.open(ROOT / "assets/vmx-poster.png") as poster:
        poster = poster.convert("RGB")
        assert poster.size == (1600, 900)
        width, height = poster.size
        pixels = poster.load()
        edge_pixels = [
            *(pixels[x, 0] for x in range(width)),
            *(pixels[x, height - 1] for x in range(width)),
            *(pixels[0, y] for y in range(height)),
            *(pixels[width - 1, y] for y in range(height)),
        ]
        band_width = 16
        border_band = [
            pixels[x, y]
            for y in range(height)
            for x in range(width)
            if x < band_width
            or x >= width - band_width
            or y < band_width
            or y >= height - band_width
        ]
        corners = [
            pixels[0, 0],
            pixels[width - 1, 0],
            pixels[0, height - 1],
            pixels[width - 1, height - 1],
        ]
    median_edge = tuple(median(pixel[channel] for pixel in edge_pixels) for channel in range(3))
    olive_pixels = sum(
        green >= 60 and green - red >= 20 and green - blue >= 15 for red, green, blue in border_band
    )

    assert max(max(pixel) for pixel in corners) <= 35
    assert max(median_edge) <= 12
    assert olive_pixels / len(border_band) < 0.01


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


def test_project_opening_rejects_reordered_centered_title(tmp_path: Path) -> None:
    (tmp_path / "docs/content").mkdir(parents=True)
    (tmp_path / "assets").mkdir()
    shutil.copy2(ROOT / "docs/opener.yaml", tmp_path / "docs/opener.yaml")
    shutil.copy2(ROOT / "README.md", tmp_path / "README.md")
    shutil.copy2(ROOT / "docs/content/index.md", tmp_path / "docs/content/index.md")
    shutil.copy2(ROOT / "assets/vmx-poster.png", tmp_path / "assets/vmx-poster.png")
    landing_path = tmp_path / "docs/content/index.md"
    landing = landing_path.read_text(encoding="utf-8")
    title = '<h1 align="center">1. VMx</h1>\n\n'
    landing_path.write_text(
        landing.replace(title, "", 1).replace(
            "<!-- vmx-opener:end -->",
            f"<!-- vmx-opener:end -->\n\n{title.rstrip()}",
            1,
        ),
        encoding="utf-8",
    )

    findings = check_project_opening(tmp_path)

    assert any("ordered centered hero" in finding.message for finding in findings)


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
