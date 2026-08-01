from __future__ import annotations

import shutil
from pathlib import Path

import pytest
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
