from __future__ import annotations

import re
from pathlib import Path

from scripts.docs import build_docs
from scripts.docs.check_docs import _check_descendant_heading_numbers, check
from scripts.docs.links import is_forbidden
from scripts.docs.manifest import load_manifest
from scripts.docs.transforms import build_source_map

ROOT = Path(__file__).resolve().parents[2]


def test_descendant_heading_numbers_require_hierarchy_and_sequence() -> None:
    valid = """# 5.2. Page

## 5.2.1. First

### 5.2.1.1. Detail

## 5.2.2. Second
"""
    assert _check_descendant_heading_numbers(valid, "5.2", Path("page.md")) == []

    invalid = """# 5.2. Page

## 5.2.2. Skipped first section

#### 5.2.2.1.1. Missing H3 parent
"""
    findings = _check_descendant_heading_numbers(invalid, "5.2", Path("page.md"))
    assert any("expected heading number '5.2.1.'" in item.message for item in findings)
    assert any("skips its H3 parent" in item.message for item in findings)


def test_descendant_heading_numbers_ignore_fenced_code() -> None:
    markdown = """# 3.1. Page

## 3.1.1. Real

```markdown
## Not a real heading
```
"""
    assert _check_descendant_heading_numbers(markdown, "3.1", Path("page.md")) == []


def test_manifest_loads_all_canonical_pages() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    sources = {section.source for section in manifest.pages()}
    content = {path.relative_to(ROOT) for path in (ROOT / "docs/content").rglob("*.md")}
    assert content <= sources


def test_source_maps_preserve_site_paths_and_flatten_wiki() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    site_map = build_source_map(manifest, "site")
    wiki_map = build_source_map(manifest, "wiki")

    assert site_map[Path("docs/content/index.md")] == Path("index.md")
    assert site_map[Path("docs/content/architecture/system-architecture.md")] == Path(
        "architecture/system-architecture.md"
    )
    assert wiki_map[Path("docs/content/index.md")] == Path("Home.md")
    assert wiki_map[Path("docs/content/architecture/system-architecture.md")].name.endswith(
        "System-Architecture.md"
    )


def test_forbidden_link_matrix_keeps_surfaces_self_contained() -> None:
    assert is_forbidden("https://github.com/thekaveh/VMx/blob/main/README.md", "site")
    assert is_forbidden("https://thekaveh.github.io/VMx/quickstart/", "wiki")
    assert is_forbidden("https://github.com/thekaveh/VMx/wiki", "repo")
    assert not is_forbidden("https://example.com/VMx", "site")


def test_build_generates_self_contained_surfaces() -> None:
    build_docs.build(site=True, wiki=True, check=True, repo_root=ROOT)

    site_page = ROOT / "generated/site/flavors/csharp.md"
    wiki_page = ROOT / "generated/wiki/7-2-C.md"
    assert site_page.exists()
    assert wiki_page.exists()
    assert "github.com/thekaveh/VMx/blob/main" not in site_page.read_text(encoding="utf-8")
    assert "thekaveh.github.io/VMx" not in wiki_page.read_text(encoding="utf-8")
    assert (ROOT / "mkdocs.yml").read_text(encoding="utf-8").find("repo_url") == -1


def test_docs_check_passes() -> None:
    assert check(ROOT) == []


def test_generated_wiki_has_sidebar_footer_and_diagram_assets() -> None:
    build_docs.build(site=True, wiki=True, check=True, repo_root=ROOT)
    assert (ROOT / "generated/wiki/_Sidebar.md").exists()
    assert (ROOT / "generated/wiki/_Footer.md").exists()
    assert (ROOT / "generated/wiki/assets/diagrams/system-architecture.png").exists()
    sidebar = (ROOT / "generated/wiki/_Sidebar.md").read_text(encoding="utf-8")
    assert re.search(r"\[\[5\.2\. System Architecture\|5-2-System-Architecture\]\]", sidebar)
