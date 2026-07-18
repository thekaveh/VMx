from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
from pathlib import Path

import yaml

from scripts.docs.manifest import Manifest, Section, load_manifest
from scripts.docs.transforms import build_source_map, rewrite_for_surface

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs/manifest.yaml"
GENERATED_ROOT = REPO_ROOT / "generated"
DIAGRAMS_DIR = REPO_ROOT / "docs/assets/diagrams"


MKDOCS_TEMPLATE = """site_name: VMx
site_description: Language-neutral MVVM framework in C#, Python, TypeScript, Swift, and Rust
site_url: https://thekaveh.github.io/VMx/
docs_dir: generated/site
site_dir: site
use_directory_urls: true

theme:
  name: material
  font:
    text: Inter
    code: JetBrains Mono
  features:
    - navigation.sections
    - navigation.indexes
    - navigation.top
    - navigation.tracking
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.tabs.link
    - toc.follow
  palette:
    - scheme: slate
      primary: cyan
      accent: cyan
      toggle:
        icon: material/weather-sunny
        name: Switch to light mode
    - scheme: default
      primary: cyan
      accent: cyan
      toggle:
        icon: material/weather-night
        name: Switch to dark mode

extra:
  generator: false

extra_css:
  - stylesheets/extra.css

nav:
{nav}

markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.highlight
  - pymdownx.inlinehilite
  - pymdownx.tabbed:
      alternate_style: true
  - toc:
      permalink: true

plugins:
  - search
"""


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def copy_diagrams(target: Path, repo_root: Path = REPO_ROOT) -> None:
    dest = target / "assets/diagrams"
    dest.mkdir(parents=True, exist_ok=True)
    diagrams_dir = repo_root / "docs/assets/diagrams"
    for pattern in ("*.html", "*.svg", "*.png", "*.json"):
        for source in diagrams_dir.glob(pattern):
            shutil.copy2(source, dest / source.name)


def copy_site_static(target: Path, repo_root: Path = REPO_ROOT) -> None:
    static_root = repo_root / "docs/content"
    for dirname in ("stylesheets", "javascripts"):
        source = static_root / dirname
        if source.exists():
            shutil.copytree(source, target / dirname, dirs_exist_ok=True)


def render_site(manifest: Manifest, out_dir: Path, repo_root: Path = REPO_ROOT) -> None:
    clean_dir(out_dir)
    source_map = build_source_map(manifest, "site")
    for source, output in source_map.items():
        target = out_dir / output
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (repo_root / source).read_text(encoding="utf-8")
        target.write_text(
            rewrite_for_surface(
                text,
                surface="site",
                current_source=source,
                current_output=output,
                source_map=source_map,
                repo_root=repo_root,
            ),
            encoding="utf-8",
        )
    copy_site_static(out_dir, repo_root)
    copy_diagrams(out_dir, repo_root)


def _wiki_sidebar(
    sections: tuple[Section, ...], source_map: dict[Path, Path], depth: int = 0
) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    for section in sections:
        if section.source is not None:
            page = source_map[section.source].stem
            lines.append(f"{indent}- [[{section.label}|{page}]]")
        else:
            lines.append(f"{indent}- **{section.label}**")
            lines.extend(_wiki_sidebar(section.children, source_map, depth + 1))
    return lines


def render_wiki(manifest: Manifest, out_dir: Path, repo_root: Path = REPO_ROOT) -> None:
    clean_dir(out_dir)
    source_map = build_source_map(manifest, "wiki")
    for source, output in source_map.items():
        target = out_dir / output
        text = (repo_root / source).read_text(encoding="utf-8")
        target.write_text(
            rewrite_for_surface(
                text,
                surface="wiki",
                current_source=source,
                current_output=output,
                source_map=source_map,
                repo_root=repo_root,
            ),
            encoding="utf-8",
        )
    (out_dir / "_Sidebar.md").write_text(
        "\n".join(_wiki_sidebar(manifest.sections, source_map)) + "\n", encoding="utf-8"
    )
    spec_version = (repo_root / "spec/VERSION").read_text(encoding="utf-8").strip()
    (out_dir / "_Footer.md").write_text(
        f"VMx · Specification {spec_version} · Apache-2.0 · thekaveh/VMx\n",
        encoding="utf-8",
    )
    copy_diagrams(out_dir, repo_root)


def _nav_item(section: Section, source_map: dict[Path, Path]) -> dict[str, object]:
    if section.source is not None:
        return {section.label: str(source_map[section.source])}
    return {section.label: [_nav_item(child, source_map) for child in section.children]}


def render_mkdocs_yml(manifest: Manifest, path: Path) -> None:
    source_map = build_source_map(manifest, "site")
    nav = [_nav_item(section, source_map) for section in manifest.sections]
    nav_yaml = yaml.safe_dump(nav, sort_keys=False, allow_unicode=True).rstrip()
    indented = "\n".join(f"  {line}" for line in nav_yaml.splitlines())
    path.write_text(MKDOCS_TEMPLATE.format(nav=indented), encoding="utf-8")


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def assert_dirs_equal(a: Path, b: Path) -> None:
    left = _file_hashes(a)
    right = _file_hashes(b)
    if left != right:
        missing = sorted(set(left) - set(right))
        extra = sorted(set(right) - set(left))
        changed = sorted(key for key in set(left) & set(right) if left[key] != right[key])
        raise AssertionError(
            "generated docs are not deterministic: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )


def build(*, site: bool, wiki: bool, check: bool, repo_root: Path = REPO_ROOT) -> None:
    manifest = load_manifest(repo_root / "docs/manifest.yaml", repo_root)
    generated_root = repo_root / "generated"
    if site:
        render_site(manifest, generated_root / "site", repo_root)
        render_mkdocs_yml(manifest, repo_root / "mkdocs.yml")
    if wiki:
        render_wiki(manifest, generated_root / "wiki", repo_root)
    if check:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            if site:
                render_site(manifest, temp_root / "site", repo_root)
                assert_dirs_equal(temp_root / "site", generated_root / "site")
            if wiki:
                render_wiki(manifest, temp_root / "wiki", repo_root)
                assert_dirs_equal(temp_root / "wiki", generated_root / "wiki")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="store_true")
    parser.add_argument("--wiki", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    site = args.site or not args.wiki
    wiki = args.wiki
    build(site=site, wiki=wiki, check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
