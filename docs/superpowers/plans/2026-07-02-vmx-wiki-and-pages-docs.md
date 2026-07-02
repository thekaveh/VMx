# VMx Wiki And Pages Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build source-controlled VMx documentation that publishes to both GitHub Pages and the GitHub wiki, with a polished Lunar Reference `.io` theme, hierarchical wiki source, comprehensive Framework Primitives pages, and high-resolution diagrams.

**Architecture:** The canonical docs live in the VMx repo. `docs/site/` is the MkDocs Material source for `https://thekaveh.github.io/VMx/`; `docs/wiki/` is hierarchical source for GitHub wiki pages; scripts under `tools/docs/` validate and flatten wiki content and validate diagram assets. Diagrams are generated as HTML/SVG/PNG triplets and shared by both targets.

**Tech Stack:** MkDocs Material, Markdown, Python 3.12 stdlib scripts, GitHub Actions Pages deployment, GitHub wiki git remote publishing, generated HTML/SVG/PNG diagrams via the architecture-diagram skill, existing VMx Markdown/spec/example source material.

## Global Constraints

- Keep existing README/spec docs as source material; do not delete or flatten the current documentation surface.
- Use `docs/site/` as tracked MkDocs source; generated MkDocs output must go to `site/` or `docs/_build/`.
- Use `docs/wiki/` as hierarchical source; publishing may flatten only into a generated wiki output directory or `VMx.wiki.git`.
- Preserve cross-language parity: snippets should cover C#, Python, TypeScript, and Swift wherever the primitive exists.
- Use the Lunar Reference theme: polished, minimal, calm, light-mode-first, strong dark mode, cool neutrals, subtle cyan/blue accents.
- Every generated diagram must have `.html`, `.svg`, and high-resolution landscape `.png`.
- Do not publish wiki/pages until local validation passes.
- Avoid changing spec behavior, package versions, or public API as part of this docs work.

______________________________________________________________________

## File Structure

Create or modify these files:

- Modify `.gitignore` so `docs/site/` is tracked source while `site/` and `docs/_build/` remain ignored build output.
- Create `docs/requirements.txt` for MkDocs dependencies.
- Create `mkdocs.yml` for site metadata, Lunar Reference theme configuration, navigation, Markdown extensions, and strict build compatibility.
- Create `docs/site/stylesheets/extra.css` for the Lunar Reference theme.
- Create `docs/site/*.md` and nested `docs/site/**.md` content pages.
- Create `docs/assets/diagrams/` with HTML/SVG/PNG diagram triplets.
- Create `docs/wiki/**.md`, including hierarchical source pages, `_Sidebar.md`, and `_Footer.md`.
- Create `tools/docs/build_wiki.py` to flatten `docs/wiki/` into `docs/_build/wiki/` and validate sidebar links.
- Create `tools/docs/validate_diagrams.py` to assert required diagram triplets, landscape PNG dimensions, and references from site/wiki docs.
- Create `tools/tests/test_docs_wiki.py` and `tools/tests/test_docs_diagrams.py` for stdlib/unit coverage of validation helpers.
- Create `.github/workflows/docs.yml` for Pages build/deploy.
- Create `.github/workflows/wiki.yml` for wiki validation/publishing.
- Modify `README.md` and `docs/integration/README.md` only to add discoverability links to the new docs site/wiki when local docs pass.

______________________________________________________________________

### Task 1: Docs Tooling And Tracked Site Source

**Files:**

- Modify: `.gitignore`
- Create: `docs/requirements.txt`
- Create: `mkdocs.yml`
- Create: `docs/site/index.md`
- Create: `docs/site/stylesheets/extra.css`

**Interfaces:**

- Consumes: repository root docs and existing ignored build-output rules.

- Produces: a locally buildable MkDocs skeleton using tracked `docs/site/` source.

- [ ] **Step 1: Update `.gitignore` for docs source**

  Remove the `docs/site/` ignore entry and keep build outputs ignored:

  ```gitignore
  # ─── Docs builds ──────────────────────────────────────────────────────
  docs/_build/
  site/
  ```

- [ ] **Step 2: Add docs dependencies**

  Create `docs/requirements.txt`:

  ```text
  mkdocs>=1.6,<2
  mkdocs-material>=9.5,<10
  pymdown-extensions>=10,<11
  ```

- [ ] **Step 3: Add MkDocs configuration**

  Create `mkdocs.yml`:

  ```yaml
  site_name: VMx
  site_description: Language-neutral MVVM viewmodel framework with C#, Python, TypeScript, and Swift parity
  site_url: https://thekaveh.github.io/VMx/
  repo_url: https://github.com/thekaveh/VMx
  repo_name: thekaveh/VMx
  docs_dir: docs/site
  site_dir: site

  theme:
    name: material
    font:
      text: Inter
      code: JetBrains Mono
    features:
      - navigation.sections
      - navigation.expand
      - navigation.top
      - navigation.tracking
      - search.suggest
      - search.highlight
      - content.code.copy
      - content.tabs.link
      - toc.follow
    palette:
      - media: "(prefers-color-scheme: light)"
        scheme: default
        toggle:
          icon: material/weather-night
          name: Switch to dark mode
      - media: "(prefers-color-scheme: dark)"
        scheme: slate
        toggle:
          icon: material/weather-sunny
          name: Switch to light mode

  extra_css:
    - stylesheets/extra.css

  nav:
    - Home: index.md

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

  exclude_docs: |
    superpowers/
  ```

- [ ] **Step 4: Add Lunar Reference CSS**

  Create `docs/site/stylesheets/extra.css`:

  ```css
  @import url("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap");

  [data-md-color-scheme="default"] {
    --md-default-bg-color: #f8fbfd;
    --md-default-fg-color: #101820;
    --md-default-fg-color--light: #41515f;
    --md-default-fg-color--lighter: #647484;
    --md-default-fg-color--lightest: #dbe5eb;
    --md-primary-fg-color: #f8fbfd;
    --md-primary-bg-color: #101820;
    --md-accent-fg-color: #007ea7;
    --md-typeset-a-color: #007ea7;
    --md-code-bg-color: #eef4f7;
    --vmx-surface: #ffffff;
    --vmx-border: #dbe5eb;
  }

  [data-md-color-scheme="slate"] {
    --md-default-bg-color: #081018;
    --md-default-fg-color: #d8e3ea;
    --md-default-fg-color--light: #a8b7c2;
    --md-default-fg-color--lighter: #7f8f9a;
    --md-default-fg-color--lightest: #273542;
    --md-primary-fg-color: #081018;
    --md-primary-bg-color: #d8e3ea;
    --md-accent-fg-color: #7dd3fc;
    --md-typeset-a-color: #38bdf8;
    --md-code-bg-color: #101b26;
    --vmx-surface: #101b26;
    --vmx-border: #273542;
  }

  .md-typeset h1,
  .md-typeset h2,
  .md-typeset h3,
  .md-header__title,
  .md-nav__title {
    font-family: "Space Grotesk", var(--md-text-font), -apple-system, BlinkMacSystemFont, sans-serif;
    font-weight: 600;
  }

  .md-header,
  .md-tabs {
    box-shadow: 0 1px 0 var(--vmx-border);
  }

  .md-typeset .highlight {
    border: 1px solid var(--vmx-border);
    border-left: 3px solid var(--md-typeset-a-color);
    border-radius: 8px;
    overflow: hidden;
  }

  .md-typeset .admonition,
  .md-typeset details {
    border-radius: 8px;
  }

  .vmx-card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
    gap: 0.8rem;
  }

  .vmx-card {
    border: 1px solid var(--vmx-border);
    border-radius: 8px;
    background: var(--vmx-surface);
    padding: 0.9rem;
  }

  .vmx-card h3 {
    margin-top: 0;
  }

  .vmx-diagram {
    border: 1px solid var(--vmx-border);
    border-radius: 8px;
    background: var(--vmx-surface);
    padding: 0.5rem;
  }

  .md-grid {
    max-width: 68rem;
  }
  ```

- [ ] **Step 5: Add initial site home page**

  Create `docs/site/index.md`:

  ```markdown
  # VMx

  VMx is a lifecycle-aware MVVM viewmodel framework: one language-neutral
  specification, four idiomatic language flavors, and a conformance catalog that
  keeps C#, Python, TypeScript, and Swift aligned.

  <div class="vmx-card-grid">
    <div class="vmx-card">
      <h3>Start fast</h3>
      <p>Install a flavor, build a component, and compose your first VM tree.</p>
    </div>
    <div class="vmx-card">
      <h3>Choose a primitive</h3>
      <p>Compare Component, Aggregate, Group, Composite, Hierarchical, and specialized VMs.</p>
    </div>
    <div class="vmx-card">
      <h3>Study the examples</h3>
      <p>Trace the Notes Workspace flagship across all four supported languages.</p>
    </div>
  </div>

  ## Why VMx

  - The spec in `spec/` defines the contract.
  - Each flavor follows native naming conventions while preserving the same conceptual shape.
  - The examples show the same VM layer mapped into Avalonia, Textual, React, and SwiftUI.
  ```

- [ ] **Step 6: Verify the skeleton builds**

  Run:

  ```bash
  python3 -m venv .docs-venv
  .docs-venv/bin/python -m pip install -r docs/requirements.txt
  .docs-venv/bin/python -m mkdocs build --strict
  ```

  Expected: build exits 0 and writes `site/index.html`.

- [ ] **Step 7: Commit**

  ```bash
  git add .gitignore docs/requirements.txt mkdocs.yml docs/site/index.md docs/site/stylesheets/extra.css
  git commit -m "docs: add pages site skeleton"
  ```

______________________________________________________________________

### Task 2: Wiki Flattening And Validation Tool

**Files:**

- Create: `tools/docs/build_wiki.py`
- Create: `tools/tests/test_docs_wiki.py`
- Create: `docs/wiki/Home.md`
- Create: `docs/wiki/_Sidebar.md`
- Create: `docs/wiki/_Footer.md`

**Interfaces:**

- Consumes: hierarchical `docs/wiki/**/*.md`.

- Produces: `docs/_build/wiki/*.md` with flattened GitHub-wiki page names and validated sidebar links.

- [ ] **Step 1: Add minimal wiki source**

  Create `docs/wiki/Home.md`:

  ```markdown
  # VMx Wiki

  VMx is a language-neutral MVVM viewmodel framework with C#, Python,
  TypeScript, and Swift implementations kept in parity by the specification and
  conformance catalog.

  Start with [[Installation]], [[Quickstart]], or the
  [[Class Architecture|Architecture-Class-Architecture]] map.
  ```

  Create `docs/wiki/_Sidebar.md`:

  ```markdown
  ### VMx Wiki

  **Getting Started**
  - [[Home]]
  - [[Installation]]
  - [[Quickstart]]

  **Architecture**
  - [[Architecture Map|Architecture-Architecture-Map]]
  - [[Class Architecture|Architecture-Class-Architecture]]

  **Framework Primitives**
  - [[Overview|Framework-Primitives-Overview]]
  - **ViewModel Families**
    - [[Component Family|Framework-Primitives-ViewModel-Families-Component-Family]]
    - [[Aggregate Family|Framework-Primitives-ViewModel-Families-Aggregate-Family]]
    - [[Group Family|Framework-Primitives-ViewModel-Families-Group-Family]]
    - [[Composite Family|Framework-Primitives-ViewModel-Families-Composite-Family]]
    - [[Hierarchical Family|Framework-Primitives-ViewModel-Families-Hierarchical-Family]]
    - [[Forwarding & Wrapper Family|Framework-Primitives-ViewModel-Families-Forwarding-and-Wrapper-Family]]
    - **Specialized ViewModels & Coordinators**
      - [[FormVM|Framework-Primitives-ViewModel-Families-Specialized-FormVM]]
      - [[DiscriminatorVM|Framework-Primitives-ViewModel-Families-Specialized-DiscriminatorVM]]
      - [[NotificationVM|Framework-Primitives-ViewModel-Families-Specialized-NotificationVM]]
      - [[ConfirmationVM|Framework-Primitives-ViewModel-Families-Specialized-ConfirmationVM]]
      - [[ModalVM|Framework-Primitives-ViewModel-Families-Specialized-ModalVM]]

  **Examples**
  - [[Notes Workspace|Examples-Notes-Workspace]]
  - [[Integration Recipes|Examples-Integration-Recipes]]
  ```

  Create `docs/wiki/_Footer.md`:

  ```markdown
  VMx documentation is source-controlled in the main repository and published to
  this wiki from `docs/wiki/`.
  ```

- [ ] **Step 2: Implement the wiki builder**

  Create `tools/docs/build_wiki.py`:

  ```python
  #!/usr/bin/env python3
  from __future__ import annotations

  import argparse
  import re
  import shutil
  from pathlib import Path

  WIKI_LINK_RE = re.compile(r"\[\[(?:(?P<label>[^\]|]+)\|)?(?P<page>[^\]]+)\]\]")

  def flattened_name(source: Path, root: Path) -> str:
      rel = source.relative_to(root)
      if source.name in {"Home.md", "_Sidebar.md", "_Footer.md"}:
          return source.name
      stem_parts = [*rel.with_suffix("").parts]
      return "-".join(stem_parts) + ".md"

  def collect_pages(source_root: Path) -> dict[str, Path]:
      pages: dict[str, Path] = {}
      for path in sorted(source_root.rglob("*.md")):
          flat = flattened_name(path, source_root)
          if flat in pages:
              raise ValueError(f"duplicate flattened wiki page {flat}: {pages[flat]} and {path}")
          pages[flat] = path
      return pages

  def rewrite_links(text: str, available_stems: set[str]) -> str:
      def replace(match: re.Match[str]) -> str:
          label = match.group("label")
          page = match.group("page").strip()
          if page.startswith(("http://", "https://")):
              return match.group(0)
          target = page if page.endswith(".md") else page
          stem = target[:-3] if target.endswith(".md") else target
          if stem not in available_stems:
              raise ValueError(f"wiki link points to missing page: {page}")
          return f"[[{label}|{stem}]]" if label else f"[[{stem}]]"
      return WIKI_LINK_RE.sub(replace, text)

  def build(source_root: Path, output_root: Path) -> list[Path]:
      pages = collect_pages(source_root)
      stems = {Path(name).stem for name in pages}
      if "Home" not in stems or "_Sidebar" not in stems:
          raise ValueError("docs/wiki must include Home.md and _Sidebar.md")
      if output_root.exists():
          shutil.rmtree(output_root)
      output_root.mkdir(parents=True)
      written: list[Path] = []
      for flat_name, source in pages.items():
          text = source.read_text(encoding="utf-8")
          text = rewrite_links(text, stems)
          target = output_root / flat_name
          target.write_text(text, encoding="utf-8")
          written.append(target)
      return written

  def main() -> int:
      parser = argparse.ArgumentParser()
      parser.add_argument("--source", default="docs/wiki")
      parser.add_argument("--out", default="docs/_build/wiki")
      args = parser.parse_args()
      written = build(Path(args.source), Path(args.out))
      print(f"wrote {len(written)} wiki page(s) to {args.out}")
      return 0

  if __name__ == "__main__":
      raise SystemExit(main())
  ```

- [ ] **Step 3: Add wiki builder tests**

  Create `tools/tests/test_docs_wiki.py`:

  ```python
  from pathlib import Path

  import pytest

  from tools.docs.build_wiki import build, flattened_name, rewrite_links

  def test_flattened_name_preserves_special_pages(tmp_path: Path) -> None:
      root = tmp_path / "wiki"
      root.mkdir()
      assert flattened_name(root / "Home.md", root) == "Home.md"
      assert flattened_name(root / "_Sidebar.md", root) == "_Sidebar.md"

  def test_flattened_name_encodes_hierarchy(tmp_path: Path) -> None:
      root = tmp_path / "wiki"
      page = root / "Framework-Primitives" / "ViewModel-Families" / "Composite-Family.md"
      assert flattened_name(page, root) == "Framework-Primitives-ViewModel-Families-Composite-Family.md"

  def test_rewrite_links_rejects_missing_page() -> None:
      with pytest.raises(ValueError, match="missing page"):
          rewrite_links("[[Missing]]", {"Home"})

  def test_build_flattens_pages_and_rewrites_sidebar(tmp_path: Path) -> None:
      source = tmp_path / "wiki"
      out = tmp_path / "out"
      (source / "Architecture").mkdir(parents=True)
      (source / "Home.md").write_text("# Home\n\n[[Architecture Map|Architecture-Architecture-Map]]\n", encoding="utf-8")
      (source / "_Sidebar.md").write_text("- [[Home]]\n- [[Architecture Map|Architecture-Architecture-Map]]\n", encoding="utf-8")
      (source / "Architecture" / "Architecture-Map.md").write_text("# Architecture Map\n", encoding="utf-8")
      written = build(source, out)
      assert out / "Architecture-Architecture-Map.md" in written
      assert "[[Architecture Map|Architecture-Architecture-Map]]" in (out / "Home.md").read_text(encoding="utf-8")
  ```

- [ ] **Step 4: Run tests and builder**

  Run:

  ```bash
  uv --project langs/python run pytest tools/tests/test_docs_wiki.py
  python3 tools/docs/build_wiki.py
  ```

  Expected: tests pass; builder prints `wrote 3 wiki page(s) to docs/_build/wiki`.

- [ ] **Step 5: Commit**

  ```bash
  git add tools/docs/build_wiki.py tools/tests/test_docs_wiki.py docs/wiki/Home.md docs/wiki/_Sidebar.md docs/wiki/_Footer.md
  git commit -m "docs: add wiki export validation"
  ```

______________________________________________________________________

### Task 3: Diagram Validation And Asset Registry

**Files:**

- Create: `docs/assets/diagrams/README.md`
- Create: `docs/assets/diagrams/diagram-registry.json`
- Create: `tools/docs/validate_diagrams.py`
- Create: `tools/tests/test_docs_diagrams.py`

**Interfaces:**

- Consumes: diagram registry entries with `id`, `title`, `html`, `svg`, `png`, and `referencedBy`.

- Produces: a validation command that fails if a diagram triplet is missing, if PNGs are not landscape, or if references are absent.

- [ ] **Step 1: Add diagram registry**

  Create `docs/assets/diagrams/diagram-registry.json`:

  ```json
  [
    {
      "id": "system-architecture",
      "title": "VMx System Architecture",
      "html": "system-architecture.html",
      "svg": "system-architecture.svg",
      "png": "system-architecture.png",
      "referencedBy": ["docs/site/architecture/system-architecture.md", "docs/wiki/Architecture/Architecture-Map.md"]
    },
    {
      "id": "class-architecture",
      "title": "Class Architecture Map",
      "html": "class-architecture.html",
      "svg": "class-architecture.svg",
      "png": "class-architecture.png",
      "referencedBy": ["docs/site/architecture/class-architecture.md", "docs/wiki/Architecture/Class-Architecture.md"]
    },
    {
      "id": "viewmodel-families",
      "title": "ViewModel Families Map",
      "html": "viewmodel-families.html",
      "svg": "viewmodel-families.svg",
      "png": "viewmodel-families.png",
      "referencedBy": ["docs/site/primitives/viewmodel-families/index.md", "docs/wiki/Framework-Primitives/ViewModel-Families/Overview.md"]
    },
    {
      "id": "lifecycle-messaging",
      "title": "Lifecycle And Messaging Flow",
      "html": "lifecycle-messaging.html",
      "svg": "lifecycle-messaging.svg",
      "png": "lifecycle-messaging.png",
      "referencedBy": ["docs/site/architecture/lifecycle-messaging.md", "docs/wiki/Architecture/Lifecycle-and-Messaging.md"]
    },
    {
      "id": "composite-family",
      "title": "Composite Family Deep Dive",
      "html": "composite-family.html",
      "svg": "composite-family.svg",
      "png": "composite-family.png",
      "referencedBy": ["docs/site/primitives/viewmodel-families/composite-family.md", "docs/wiki/Framework-Primitives/ViewModel-Families/Composite-Family.md"]
    },
    {
      "id": "commands-capabilities",
      "title": "Commands And Capabilities Map",
      "html": "commands-capabilities.html",
      "svg": "commands-capabilities.svg",
      "png": "commands-capabilities.png",
      "referencedBy": ["docs/site/primitives/command-families.md", "docs/wiki/Framework-Primitives/Command-Families.md"]
    },
    {
      "id": "forms-dialogs-notifications",
      "title": "Forms Dialogs And Notifications Flow",
      "html": "forms-dialogs-notifications.html",
      "svg": "forms-dialogs-notifications.svg",
      "png": "forms-dialogs-notifications.png",
      "referencedBy": ["docs/site/primitives/viewmodel-families/specialized/form-vm.md", "docs/wiki/Framework-Primitives/ViewModel-Families/Specialized/FormVM.md"]
    },
    {
      "id": "examples-vm-layer",
      "title": "Examples VM Layer Map",
      "html": "examples-vm-layer.html",
      "svg": "examples-vm-layer.svg",
      "png": "examples-vm-layer.png",
      "referencedBy": ["docs/site/examples/notes-workspace-vm-layer.md", "docs/wiki/Examples/Notes-Workspace-VM-Layer.md"]
    }
  ]
  ```

- [ ] **Step 2: Add diagram README**

  Create `docs/assets/diagrams/README.md`:

  ```markdown
  # VMx Documentation Diagrams

  Diagrams in this directory are generated assets used by the `.io` site and the
  GitHub wiki. Each diagram is stored as:

  - `.html` — standalone source page
  - `.svg` — vector embed
  - `.png` — high-resolution landscape image for GitHub/wiki rendering

  `diagram-registry.json` is the validation source of truth.
  ```

- [ ] **Step 3: Implement diagram validator**

  Create `tools/docs/validate_diagrams.py`:

  ```python
  #!/usr/bin/env python3
  from __future__ import annotations

  import argparse
  import json
  import struct
  from pathlib import Path
  from typing import TypedDict

  class Diagram(TypedDict):
      id: str
      title: str
      html: str
      svg: str
      png: str
      referencedBy: list[str]

  def png_size(path: Path) -> tuple[int, int]:
      data = path.read_bytes()
      if data[:8] != b"\x89PNG\r\n\x1a\n":
          raise ValueError(f"{path} is not a PNG")
      width, height = struct.unpack(">II", data[16:24])
      return width, height

  def load_registry(path: Path) -> list[Diagram]:
      return json.loads(path.read_text(encoding="utf-8"))

  def validate(root: Path, registry_path: Path, *, assets_only: bool = False) -> list[str]:
      errors: list[str] = []
      diagrams_dir = registry_path.parent
      for item in load_registry(registry_path):
          for key in ("html", "svg", "png"):
              asset = diagrams_dir / item[key]  # type: ignore[literal-required]
              if not asset.exists():
                  errors.append(f"{item['id']}: missing {asset}")
          png = diagrams_dir / item["png"]
          if png.exists():
              try:
                  width, height = png_size(png)
                  if width <= height:
                      errors.append(f"{item['id']}: PNG is not landscape ({width}x{height})")
                  if width < 2400:
                      errors.append(f"{item['id']}: PNG width {width} is below 2400px")
              except ValueError as exc:
                  errors.append(str(exc))
          if assets_only:
              continue
          for ref in item["referencedBy"]:
              ref_path = root / ref
              if not ref_path.exists():
                  errors.append(f"{item['id']}: missing reference file {ref}")
                  continue
              text = ref_path.read_text(encoding="utf-8")
              if item["svg"] not in text and item["png"] not in text and item["html"] not in text:
                  errors.append(f"{item['id']}: {ref} does not reference diagram asset")
      return errors

  def main() -> int:
      parser = argparse.ArgumentParser()
      parser.add_argument("--root", default=".")
      parser.add_argument("--registry", default="docs/assets/diagrams/diagram-registry.json")
      parser.add_argument("--assets-only", action="store_true")
      args = parser.parse_args()
      errors = validate(Path(args.root), Path(args.registry), assets_only=args.assets_only)
      if errors:
          for error in errors:
              print(f"ERROR: {error}")
          return 1
      print("diagram validation passed")
      return 0

  if __name__ == "__main__":
      raise SystemExit(main())
  ```

- [ ] **Step 4: Add validator tests**

  Create `tools/tests/test_docs_diagrams.py` with a minimal PNG fixture generator:

  ```python
  import struct
  import zlib
  from pathlib import Path

  from tools.docs.validate_diagrams import png_size, validate

  def write_png(path: Path, width: int, height: int) -> None:
      def chunk(kind: bytes, data: bytes) -> bytes:
          return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
      raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
      data = (
          b"\x89PNG\r\n\x1a\n"
          + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
          + chunk(b"IDAT", zlib.compress(raw))
          + chunk(b"IEND", b"")
      )
      path.write_bytes(data)

  def test_png_size_reads_dimensions(tmp_path: Path) -> None:
      png = tmp_path / "x.png"
      write_png(png, 3200, 1800)
      assert png_size(png) == (3200, 1800)

  def test_validate_accepts_complete_landscape_triplet(tmp_path: Path) -> None:
      diagrams = tmp_path / "docs" / "assets" / "diagrams"
      diagrams.mkdir(parents=True)
      (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
      (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
      write_png(diagrams / "one.png", 3200, 1800)
      ref = tmp_path / "docs" / "site" / "page.md"
      ref.parent.mkdir(parents=True)
      ref.write_text("![One](../assets/diagrams/one.svg)", encoding="utf-8")
      registry = diagrams / "diagram-registry.json"
      registry.write_text(
          '[{"id":"one","title":"One","html":"one.html","svg":"one.svg","png":"one.png","referencedBy":["docs/site/page.md"]}]',
          encoding="utf-8",
      )
      assert validate(tmp_path, registry) == []
      assert validate(tmp_path, registry, assets_only=True) == []
  ```

- [ ] **Step 5: Run tests**

  ```bash
  uv --project langs/python run pytest tools/tests/test_docs_diagrams.py
  ```

  Expected: both tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add docs/assets/diagrams/README.md docs/assets/diagrams/diagram-registry.json tools/docs/validate_diagrams.py tools/tests/test_docs_diagrams.py
  git commit -m "docs: add diagram validation registry"
  ```

______________________________________________________________________

### Task 4: Generate Diagram Triplets

**Files:**

- Create: eight `docs/assets/diagrams/*.html`
- Create: eight `docs/assets/diagrams/*.svg`
- Create: eight `docs/assets/diagrams/*.png`
- Modify: existing diagram links only after replacement pages exist

**Interfaces:**

- Consumes: `docs/assets/diagrams/diagram-registry.json`, `README.md`, `spec/*.md`, `examples/notes-showcase-parity.md`.

- Produces: all diagram triplets required by the registry.

- [ ] **Step 1: Invoke the architecture-diagram skill**

  Before generating diagram files, read and follow the `architecture-diagram` skill. Use it to generate these eight landscape diagrams in the Lunar Reference style:

  ```text
  system-architecture
  class-architecture
  viewmodel-families
  lifecycle-messaging
  composite-family
  commands-capabilities
  forms-dialogs-notifications
  examples-vm-layer
  ```

- [ ] **Step 2: Ensure the class architecture map distinguishes relationships**

  The `class-architecture` diagram must use separate line styles or labels for:

  ```text
  extends
  implements
  owns
  wraps
  decorates
  adapts
  ```

  Required assertion in the diagram text: `PagedComposition` and `TokenPagedComposition` are composition/paging primitives, not `CompositeVM` subclasses.

- [ ] **Step 3: Export high-resolution PNGs**

  Generate each PNG at 3200px or wider, landscape. Use Playwright, `rsvg-convert`, `inkscape`, or another available renderer.

- [ ] **Step 4: Validate diagrams**

  Run:

  ```bash
  python3 tools/docs/validate_diagrams.py --assets-only
  ```

  Expected: exits 0, proving every diagram triplet exists and every PNG is high-resolution landscape. Full reference validation runs after Tasks 5-9 create the referencing pages.

- [ ] **Step 5: Commit diagram assets**

  ```bash
  git add docs/assets/diagrams
  git commit -m "docs: add documentation diagram set"
  ```

______________________________________________________________________

### Task 5: Site Architecture, Installation, Quickstart, And Core Pages

**Files:**

- Modify: `mkdocs.yml`
- Modify: `docs/site/index.md`
- Create: `docs/site/installation.md`
- Create: `docs/site/quickstart.md`
- Create: `docs/site/core-concepts.md`
- Create: `docs/site/architecture/index.md`
- Create: `docs/site/architecture/system-architecture.md`
- Create: `docs/site/architecture/class-architecture.md`
- Create: `docs/site/architecture/lifecycle-messaging.md`
- Create: `docs/site/architecture/diagram-gallery.md`

**Interfaces:**

- Consumes: generated diagrams and existing `README.md`, `docs/getting-started/*.md`, `spec/README.md`.

- Produces: a navigable `.io` site skeleton with architecture pages and four-language quickstart snippets.

- [ ] **Step 1: Add navigation entries**

  Expand `mkdocs.yml` `nav`:

  ```yaml
  nav:
    - Home: index.md
    - Installation: installation.md
    - Quickstart: quickstart.md
    - Core Concepts: core-concepts.md
    - Architecture Map:
        - Overview: architecture/index.md
        - System Architecture: architecture/system-architecture.md
        - Class Architecture: architecture/class-architecture.md
        - Lifecycle & Messaging: architecture/lifecycle-messaging.md
        - Diagram Gallery: architecture/diagram-gallery.md
  ```

- [ ] **Step 2: Create installation page**

  Include source-tree package status from `README.md` §3.1 and install snippets for all four flavors:

  ````markdown
  # Installation

  VMx has four source flavors. The source tree implements v3.1.0 for C#,
  Python, TypeScript, and Swift. Public package availability can lag the source
  tree; check the flavor README and registry before pinning a release.

  === "C#"

      ```bash
      dotnet add package VMx
      ```

  === "Python"

      ```bash
      pip install vmx
      # or
      uv add vmx
      ```

  === "TypeScript"

      ```bash
      npm install @thekaveh/vmx rxjs
      ```

  === "Swift"

      ```swift
      .package(url: "https://github.com/thekaveh/VMx.git", from: "3.1.0")
      ```
  ````

- [ ] **Step 3: Create quickstart page**

  Use four tabbed snippets showing the same component + composite shape. Source snippets from existing `docs/getting-started/*.md`; keep each snippet under 55 lines.

- [ ] **Step 4: Create core concepts page**

  Cover:

  ```text
  one spec / four flavors
  lifecycle-aware VMs
  message hub and dispatcher
  parent-child ownership
  idiomatic naming by flavor
  conformance catalog
  ```

- [ ] **Step 5: Create architecture pages**

  Each page embeds its diagram and adds a short explanation:

  ```markdown
  ![Class Architecture](../assets/diagrams/class-architecture.svg){ .vmx-diagram }

  [Open standalone diagram](../assets/diagrams/class-architecture.html) ·
  [PNG](../assets/diagrams/class-architecture.png)
  ```

- [ ] **Step 6: Build site**

  Run:

  ```bash
  .docs-venv/bin/python -m mkdocs build --strict
  ```

  Expected: build exits 0.

- [ ] **Step 7: Commit**

  ```bash
  git add mkdocs.yml docs/site
  git commit -m "docs: add core pages site structure"
  ```

______________________________________________________________________

### Task 6: Framework Primitives Site Pages

**Files:**

- Modify: `mkdocs.yml`
- Create: `docs/site/primitives/index.md`
- Create: `docs/site/primitives/viewmodel-families/index.md`
- Create: `docs/site/primitives/viewmodel-families/component-family.md`
- Create: `docs/site/primitives/viewmodel-families/aggregate-family.md`
- Create: `docs/site/primitives/viewmodel-families/group-family.md`
- Create: `docs/site/primitives/viewmodel-families/composite-family.md`
- Create: `docs/site/primitives/viewmodel-families/hierarchical-family.md`
- Create: `docs/site/primitives/viewmodel-families/forwarding-wrapper-family.md`
- Create: `docs/site/primitives/viewmodel-families/specialized/index.md`
- Create: `docs/site/primitives/viewmodel-families/specialized/form-vm.md`
- Create: `docs/site/primitives/viewmodel-families/specialized/discriminator-vm.md`
- Create: `docs/site/primitives/viewmodel-families/specialized/notification-vm.md`
- Create: `docs/site/primitives/viewmodel-families/specialized/confirmation-vm.md`
- Create: `docs/site/primitives/viewmodel-families/specialized/modal-vm.md`
- Create: `docs/site/primitives/command-families.md`
- Create: `docs/site/primitives/capability-families.md`
- Create: `docs/site/primitives/state-reactive-helpers.md`
- Create: `docs/site/primitives/services-messages-dispatching.md`
- Create: `docs/site/primitives/builders-collections-tree-utilities.md`

**Interfaces:**

- Consumes: `spec/05-component-vm.md`, `spec/06-composite-vm.md`, `spec/07-group-vm.md`, `spec/08-aggregate-vm.md`, `spec/18-hierarchical-vm.md`, `spec/20-form-vm.md`, `spec/21-collections.md`, `spec/22-discriminator-vm.md`, flavor READMEs, and examples.

- Produces: comprehensive Framework Primitives reference pages with four-language snippets.

- [ ] **Step 1: Add primitives navigation**

  Add this block to `mkdocs.yml`:

  ```yaml
    - Framework Primitives:
        - Overview: primitives/index.md
        - ViewModel Families:
            - Overview: primitives/viewmodel-families/index.md
            - Component Family: primitives/viewmodel-families/component-family.md
            - Aggregate Family: primitives/viewmodel-families/aggregate-family.md
            - Group Family: primitives/viewmodel-families/group-family.md
            - Composite Family: primitives/viewmodel-families/composite-family.md
            - Hierarchical Family: primitives/viewmodel-families/hierarchical-family.md
            - Forwarding & Wrapper Family: primitives/viewmodel-families/forwarding-wrapper-family.md
            - Specialized ViewModels & Coordinators:
                - Overview: primitives/viewmodel-families/specialized/index.md
                - FormVM: primitives/viewmodel-families/specialized/form-vm.md
                - DiscriminatorVM: primitives/viewmodel-families/specialized/discriminator-vm.md
                - NotificationVM: primitives/viewmodel-families/specialized/notification-vm.md
                - ConfirmationVM: primitives/viewmodel-families/specialized/confirmation-vm.md
                - ModalVM: primitives/viewmodel-families/specialized/modal-vm.md
        - Command Families: primitives/command-families.md
        - Capability Families: primitives/capability-families.md
        - State & Reactive Helpers: primitives/state-reactive-helpers.md
        - Services, Messages & Dispatching: primitives/services-messages-dispatching.md
        - Builders, Collections & Tree Utilities: primitives/builders-collections-tree-utilities.md
  ```

- [ ] **Step 2: Use a consistent primitive page template**

  Each primitive page must contain these headings:

  ```markdown
  # <Primitive Name>

  ## When To Use It

  ## Shape And Ownership

  ## Lifecycle And Messaging

  ## Cross-Language Surface

  ## Example

  ## Common Pitfalls

  ## Related Primitives
  ```

- [ ] **Step 3: Populate ViewModel family pages**

  Add source-derived snippets from all four flavors. For example, the Composite Family page must include:

  ````markdown
  === "C#"

      ```csharp
      var tabs = CompositeVM<ComponentVM<TabModel>>.Builder()
          .Name("tab-bar")
          .Services(hub, dispatcher)
          .Children(() => new[] { home, settings })
          .Build();
      ```

  === "Python"

      ```python
      tabs = (
          CompositeVM[ComponentVMOf[TabModel]]
          .builder()
          .name("tab-bar")
          .services(hub, dispatcher)
          .children(lambda: [home, settings])
          .build()
      )
      ```

  === "TypeScript"

      ```ts
      const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
        .name("tab-bar")
        .services(hub, dispatcher)
        .children(() => [home, settings])
        .build();
      ```

  === "Swift"

      ```swift
      let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
          .name("tab-bar")
          .services(hub: hub, dispatcher: dispatcher)
          .children { [home, settings] }
          .build()
      ```
  ````

- [ ] **Step 4: Give specialized VMs dedicated pages**

  The specialized section must include separate pages for `FormVM`, `DiscriminatorVM`, `NotificationVM`, `ConfirmationVM`, and `ModalVM`. Each page must link to the relevant Notes Workspace feature when used by the examples.

- [ ] **Step 5: Build site**

  Run:

  ```bash
  .docs-venv/bin/python -m mkdocs build --strict
  ```

  Expected: build exits 0.

- [ ] **Step 6: Commit**

  ```bash
  git add mkdocs.yml docs/site/primitives
  git commit -m "docs: add framework primitives reference"
  ```

______________________________________________________________________

### Task 7: Language Flavor, Examples, Integration, Spec, And Project Site Pages

**Files:**

- Modify: `mkdocs.yml`
- Create: `docs/site/flavors/index.md`
- Create: `docs/site/flavors/csharp.md`
- Create: `docs/site/flavors/python.md`
- Create: `docs/site/flavors/typescript.md`
- Create: `docs/site/flavors/swift.md`
- Create: `docs/site/flavors/cross-language-naming.md`
- Create: `docs/site/examples/index.md`
- Create: `docs/site/examples/notes-workspace.md`
- Create: `docs/site/examples/notes-workspace-vm-layer.md`
- Create: `docs/site/examples/global-search-token-paging.md`
- Create: `docs/site/examples/editor-mode-discriminator-vm.md`
- Create: `docs/site/examples/tag-autocomplete-searchable-state.md`
- Create: `docs/site/examples/smaller-examples.md`
- Create: `docs/site/integration-recipes.md`
- Create: `docs/site/specification-conformance.md`
- Create: `docs/site/contributing-releases.md`

**Interfaces:**

- Consumes: `langs/*/README.md`, `docs/integration/*.md`, `examples/notes-showcase-parity.md`, example READMEs, `spec/README.md`, `CONTRIBUTING.md`, release runbooks.

- Produces: the rest of the public site navigation.

- [ ] **Step 1: Add navigation sections**

  Append these sections to `mkdocs.yml`:

  ```yaml
    - Language Flavors:
        - Overview: flavors/index.md
        - C#: flavors/csharp.md
        - Python: flavors/python.md
        - TypeScript: flavors/typescript.md
        - Swift: flavors/swift.md
        - Cross-Language Naming: flavors/cross-language-naming.md
    - Examples:
        - Overview: examples/index.md
        - Notes Workspace: examples/notes-workspace.md
        - VM Layer Map: examples/notes-workspace-vm-layer.md
        - Global Search & Token Paging: examples/global-search-token-paging.md
        - Editor Mode & DiscriminatorVM: examples/editor-mode-discriminator-vm.md
        - Tag Autocomplete & SearchableState: examples/tag-autocomplete-searchable-state.md
        - Smaller Examples: examples/smaller-examples.md
    - Integration Recipes: integration-recipes.md
    - Specification & Conformance: specification-conformance.md
    - Contributing & Releases: contributing-releases.md
  ```

- [ ] **Step 2: Create flavor pages**

  Each flavor page must include:

  ```text
  install command
  package/publication status
  reactive primitive
  idiomatic naming
  quick link to flavor README
  quick link to getting-started guide
  quick link to examples
  ```

- [ ] **Step 3: Create examples pages**

  The Notes Workspace pages must reference:

  ```text
  examples/assets/notes-showcase-vm-hierarchy.svg
  docs/assets/diagrams/examples-vm-layer.svg
  examples/notes-showcase-parity.md
  examples/csharp/avalonia/NotesShowcase/README.md
  examples/python/textual/notes_showcase/README.md
  examples/typescript/react/notes-showcase/README.md
  examples/swift/notes-showcase/README.md
  ```

- [ ] **Step 4: Create integration/spec/project pages**

  Reuse existing source docs by linking to them and summarizing the current entry points. Do not duplicate every integration recipe in full; link the per-framework recipe pages under `docs/integration/`.

- [ ] **Step 5: Build site**

  ```bash
  .docs-venv/bin/python -m mkdocs build --strict
  ```

  Expected: build exits 0.

- [ ] **Step 6: Commit**

  ```bash
  git add mkdocs.yml docs/site/flavors docs/site/examples docs/site/integration-recipes.md docs/site/specification-conformance.md docs/site/contributing-releases.md
  git commit -m "docs: add flavor examples and project pages"
  ```

______________________________________________________________________

### Task 8: Complete Hierarchical Wiki Source

**Files:**

- Create: all `docs/wiki/Architecture/*.md`
- Create: all `docs/wiki/Framework-Primitives/**/*.md`
- Create: all `docs/wiki/Language-Flavors/*.md`
- Create: all `docs/wiki/Examples/*.md`
- Create: all `docs/wiki/Specification-and-Conformance/*.md`
- Create: all `docs/wiki/Project/*.md`
- Modify: `docs/wiki/Home.md`
- Modify: `docs/wiki/_Sidebar.md`

**Interfaces:**

- Consumes: site pages from Tasks 5-7 and generated diagrams.

- Produces: source-controlled wiki pages that flatten and validate.

- [ ] **Step 1: Create required wiki directories**

  ```bash
  mkdir -p \
    docs/wiki/Architecture \
    docs/wiki/Framework-Primitives/ViewModel-Families/Specialized \
    docs/wiki/Language-Flavors \
    docs/wiki/Examples \
    docs/wiki/Specification-and-Conformance \
    docs/wiki/Project
  ```

- [ ] **Step 2: Create wiki pages**

  For each wiki page in the approved source layout, add GitHub-native Markdown. Use PNG diagram links, not SVG-only links. Every page must start with a heading matching its sidebar label.

- [ ] **Step 3: Ensure wiki hierarchy in `_Sidebar.md`**

  `_Sidebar.md` must include these top-level sections:

  ```markdown
  **Getting Started**
  **Architecture**
  **Framework Primitives**
  **Language Flavors**
  **Examples**
  **Specification & Conformance**
  **Project**
  ```

  Under Framework Primitives, keep the nested ViewModel Families and Specialized ViewModels & Coordinators structure.

- [ ] **Step 4: Build flattened wiki**

  Run:

  ```bash
  python3 tools/docs/build_wiki.py
  find docs/_build/wiki -maxdepth 1 -type f -name '*.md' | wc -l
  ```

  Expected: builder exits 0 and produces at least 35 Markdown files.

- [ ] **Step 5: Commit**

  ```bash
  git add docs/wiki
  git commit -m "docs: add hierarchical wiki source"
  ```

______________________________________________________________________

### Task 9: GitHub Actions For Pages And Wiki

**Files:**

- Create: `.github/workflows/docs.yml`
- Create: `.github/workflows/wiki.yml`
- Create: `tools/docs/publish_wiki.sh`

**Interfaces:**

- Consumes: MkDocs site, wiki build script, diagram validator.

- Produces: CI validation and deploy/publish workflows.

- [ ] **Step 1: Add Pages workflow**

  Create `.github/workflows/docs.yml`:

  ```yaml
  name: docs

  on:
    push:
      branches: [main]
      paths:
        - "docs/**"
        - "mkdocs.yml"
        - "tools/docs/**"
        - ".github/workflows/docs.yml"
    pull_request:
      paths:
        - "docs/**"
        - "mkdocs.yml"
        - "tools/docs/**"
        - ".github/workflows/docs.yml"
    workflow_dispatch:

  permissions:
    contents: read
    pages: write
    id-token: write

  concurrency:
    group: pages
    cancel-in-progress: false

  jobs:
    build:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
          with:
            python-version: "3.12"
        - name: Install docs dependencies
          run: |
            python -m pip install --upgrade pip
            python -m pip install -r docs/requirements.txt
        - name: Validate wiki export
          run: python3 tools/docs/build_wiki.py
        - name: Validate diagrams
          run: python3 tools/docs/validate_diagrams.py
        - name: Build site
          run: mkdocs build --strict
        - name: Configure Pages
          if: github.event_name != 'pull_request'
          uses: actions/configure-pages@983d7736d9b0ae728b81ab479565c72886d7745b
          with:
            enablement: true
        - name: Upload Pages artifact
          if: github.event_name != 'pull_request'
          uses: actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa
          with:
            path: site
    deploy:
      if: github.event_name != 'pull_request'
      needs: build
      runs-on: ubuntu-latest
      environment:
        name: github-pages
        url: ${{ steps.deployment.outputs.page_url }}
      steps:
        - id: deployment
          uses: actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e
  ```

- [ ] **Step 2: Add wiki publish script**

  Create `tools/docs/publish_wiki.sh`:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  repo_url="${1:-https://github.com/thekaveh/VMx.wiki.git}"
  workdir="${2:-docs/_build/wiki-repo}"

  python3 tools/docs/build_wiki.py --out docs/_build/wiki
  rm -rf "$workdir"
  git clone "$repo_url" "$workdir"
  find "$workdir" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  cp docs/_build/wiki/*.md "$workdir"/
  (
    cd "$workdir"
    git add .
    if git diff --cached --quiet; then
      echo "wiki already up to date"
      exit 0
    fi
    git commit -m "docs: publish VMx wiki"
    git push
  )
  ```

- [ ] **Step 3: Add wiki workflow**

  Create `.github/workflows/wiki.yml`:

  ```yaml
  name: wiki

  on:
    push:
      branches: [main]
      paths:
        - "docs/wiki/**"
        - "tools/docs/build_wiki.py"
        - "tools/docs/publish_wiki.sh"
        - ".github/workflows/wiki.yml"
    workflow_dispatch:

  permissions:
    contents: write

  jobs:
    publish:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
          with:
            python-version: "3.12"
        - name: Validate wiki export
          run: python3 tools/docs/build_wiki.py
        - name: Publish wiki
          env:
            GIT_AUTHOR_NAME: github-actions[bot]
            GIT_AUTHOR_EMAIL: 41898282+github-actions[bot]@users.noreply.github.com
            GIT_COMMITTER_NAME: github-actions[bot]
            GIT_COMMITTER_EMAIL: 41898282+github-actions[bot]@users.noreply.github.com
          run: tools/docs/publish_wiki.sh "https://x-access-token:${{ github.token }}@github.com/thekaveh/VMx.wiki.git"
  ```

- [ ] **Step 4: Make script executable and validate YAML**

  Run:

  ```bash
  chmod +x tools/docs/publish_wiki.sh
  python3 tools/docs/build_wiki.py
  ```

  Expected: wiki build exits 0.

- [ ] **Step 5: Commit**

  ```bash
  git add .github/workflows/docs.yml .github/workflows/wiki.yml tools/docs/publish_wiki.sh
  git commit -m "ci: add docs and wiki publishing workflows"
  ```

______________________________________________________________________

### Task 10: Link Public Docs From Existing Repository Entrypoints

**Files:**

- Modify: `README.md`
- Modify: `docs/integration/README.md`
- Modify: `examples/notes-showcase-parity.md`

**Interfaces:**

- Consumes: completed site/wiki pages.

- Produces: discoverability links from current docs into the new docs surfaces.

- [ ] **Step 1: Update root README documentation map**

  Add links near `README.md` §5.1:

  ```markdown
  - Public documentation site: [thekaveh.github.io/VMx](https://thekaveh.github.io/VMx/)
  - GitHub wiki: [github.com/thekaveh/VMx/wiki](https://github.com/thekaveh/VMx/wiki)
  ```

- [ ] **Step 2: Update integration README**

  Add a short line after the opening paragraph:

  ```markdown
  The published documentation site also groups these recipes under
  [Integration Recipes](https://thekaveh.github.io/VMx/integration-recipes/).
  ```

- [ ] **Step 3: Update Notes Showcase parity page**

  Add links to the new examples site pages:

  ```markdown
  Published walkthroughs:
  [Notes Workspace](https://thekaveh.github.io/VMx/examples/notes-workspace/),
  [VM layer map](https://thekaveh.github.io/VMx/examples/notes-workspace-vm-layer/).
  ```

- [ ] **Step 4: Run docs checks**

  ```bash
  .docs-venv/bin/python -m mkdocs build --strict
  python3 tools/docs/build_wiki.py
  python3 tools/docs/validate_diagrams.py
  git diff --check
  ```

  Expected: all commands exit 0.

- [ ] **Step 5: Commit**

  ```bash
  git add README.md docs/integration/README.md examples/notes-showcase-parity.md
  git commit -m "docs: link published documentation surfaces"
  ```

______________________________________________________________________

### Task 11: Final Verification

**Files:**

- All changed docs, workflows, tools, and assets.

**Interfaces:**

- Consumes: all prior tasks.

- Produces: a verified branch ready for review.

- [ ] **Step 1: Run site build**

  ```bash
  .docs-venv/bin/python -m mkdocs build --strict
  ```

  Expected: exits 0.

- [ ] **Step 2: Run wiki export**

  ```bash
  python3 tools/docs/build_wiki.py
  ```

  Expected: exits 0 and writes flattened wiki pages.

- [ ] **Step 3: Run diagram validation**

  ```bash
  python3 tools/docs/validate_diagrams.py
  ```

  Expected: exits 0.

- [ ] **Step 4: Run docs tests**

  ```bash
  uv --project langs/python run pytest tools/tests/test_docs_wiki.py tools/tests/test_docs_diagrams.py
  ```

  Expected: exits 0.

- [ ] **Step 5: Run existing examples parity check**

  ```bash
  python3 tools/check-showcase-parity.py
  ```

  Expected: exits 0.

- [ ] **Step 6: Run final hygiene checks**

  ```bash
  git diff --check
  git status --short
  ```

  Expected: no whitespace errors; only intentional committed changes or a clean worktree.

- [ ] **Step 7: Prepare review summary**

  Summarize:

  ```text
  Docs site path: docs/site/
  Wiki source path: docs/wiki/
  Diagram registry: docs/assets/diagrams/diagram-registry.json
  Local build command: .docs-venv/bin/python -m mkdocs build --strict
  Wiki export command: python3 tools/docs/build_wiki.py
  Diagram validation command: python3 tools/docs/validate_diagrams.py
  ```
