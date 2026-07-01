# VMx Docs And Diagrams Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring repository documentation and diagram assets into sync with the current v3.1.0 VMx surface and the 19-feature Notes Showcase examples.

**Architecture:** Documentation stays source-controlled as Markdown. Diagrams stay as paired standalone HTML/SVG files, with high-resolution PNG exports generated beside the SVGs. Existing diagram locations are preserved, and one new examples diagram documents how the Notes Showcase VM layer composes VMx primitives.

**Tech Stack:** Markdown, inline SVG/HTML using the architecture-diagram skill design system, local Node/Playwright or browser tooling for PNG export, repository validation scripts.

## Global Constraints

- Preserve existing diagram paths: `assets/architecture.*`, `assets/class-diagram.*`, and `examples/assets/notes-showcase-vm-hierarchy.*`.
- Add PNG exports next to each SVG: `assets/architecture.png`, `assets/class-diagram.png`, `examples/assets/notes-showcase-vm-hierarchy.png`.
- Add a new examples component diagram: `examples/assets/notes-showcase-vmx-components.{html,svg,png}`.
- Keep diagrams landscape-oriented and readable at high resolution.
- Documentation must reflect spec v3.1.0, 23 spec chapters, 79 ADRs, 281 library IDs + 5 THEME IDs = 286 total IDs, and four full-parity flavors.
- Notes Showcase documentation must describe 19 features, including `TokenPagedComposition`, `DiscriminatorVM`, and tag autocomplete via `SearchableState`.

______________________________________________________________________

### Task 1: Documentation Sync

**Files:**

- Modify: `README.md`
- Modify: `examples/notes-showcase-parity.md`
- Modify: `examples/*/README.md`
- Modify: `examples/*/*/README.md` where stale Notes Showcase claims appear

**Interfaces:**

- Consumes: Current docs and recent example implementation commits.

- Produces: Markdown that matches the current examples and diagram assets.

- [ ] **Step 1: Find stale claims**

Run:

```bash
rg -n "16 distinct|2\\.6\\.0|237 conformance|41/237|46 ADRs|22 numbered|Swift.*subset|total parity|TokenPaged|Discriminator|Tag autocomplete" README.md examples docs spec langs -g '*.md'
```

Expected: stale root diagram/example claims are identified before editing.

- [ ] **Step 2: Update root README**

Change the examples section to say 19 features and name the three newly showcased components. Update diagram prose so SVG, HTML, and PNG variants are all discoverable.

- [ ] **Step 3: Update examples docs**

Ensure Notes Showcase READMEs and the parity matrix mention all four flavors and the 19 rows consistently.

- [ ] **Step 4: Re-run stale scan**

Run:

```bash
rg -n "16 distinct|2\\.6\\.0|237 conformance|41/237|46 ADRs|22 numbered|Swift.*subset" README.md examples docs spec langs -g '*.md' || true
```

Expected: no current-facing stale claims remain; historical plans/proposals may still contain old values.

### Task 2: Regenerate Existing Diagrams

**Files:**

- Modify: `assets/architecture.html`
- Modify: `assets/architecture.svg`
- Modify: `assets/class-diagram.html`
- Modify: `assets/class-diagram.svg`
- Modify: `examples/assets/notes-showcase-vm-hierarchy.html`
- Modify: `examples/assets/notes-showcase-vm-hierarchy.svg`

**Interfaces:**

- Consumes: Current spec and examples docs.

- Produces: Landscape SVG/HTML diagrams using the architecture-diagram skill palette and current v3.1.0 labels.

- [ ] **Step 1: Update architecture diagram**

Represent the current source-of-truth stack: spec, four flavors, core VM family, services/messages, state helpers, collections, notifications, dialogs/forms, and examples.

- [ ] **Step 2: Update class map**

Include current specialized primitives: `TokenPagedComposition`, filtered/scored composite views, `FormVM` validation, modal presentation, `DiscriminatorVM`, and full Swift parity.

- [ ] **Step 3: Update Notes Showcase hierarchy**

Keep the pane-oriented hierarchy and include the current right-pane editor mode, tag suggestions, global search, and deterministic workspace refresh wiring.

### Task 3: Add Examples VMx Components Diagram

**Files:**

- Create: `examples/assets/notes-showcase-vmx-components.html`
- Create: `examples/assets/notes-showcase-vmx-components.svg`
- Modify: `README.md`
- Modify: `examples/notes-showcase-parity.md`
- Modify: per-example README links where appropriate

**Interfaces:**

- Consumes: Notes Showcase VM structure across C#, Python, TypeScript, and Swift.

- Produces: A new diagram showing which VMx primitive each example VM composes.

- [ ] **Step 1: Author diagram**

Create a landscape diagram with lanes for root composition, navigation/list state, editor/form state, cross-cutting services, and view adapters.

- [ ] **Step 2: Link it from docs**

Add links near existing hierarchy diagram references so contributors can find both the hierarchy view and the component-composition view.

### Task 4: Generate High-Resolution PNGs

**Files:**

- Create: `assets/architecture.png`
- Create: `assets/class-diagram.png`
- Create: `examples/assets/notes-showcase-vm-hierarchy.png`
- Create: `examples/assets/notes-showcase-vmx-components.png`

**Interfaces:**

- Consumes: SVG files from Tasks 2 and 3.

- Produces: PNG exports at high resolution, preserving landscape composition.

- [ ] **Step 1: Export PNGs**

Use an available local renderer (`rsvg-convert`, `inkscape`, `magick`, or Playwright screenshot of the SVG/HTML) to generate high-resolution PNGs.

- [ ] **Step 2: Inspect dimensions**

Run:

```bash
file assets/architecture.png assets/class-diagram.png examples/assets/notes-showcase-vm-hierarchy.png examples/assets/notes-showcase-vmx-components.png
```

Expected: PNG dimensions are landscape and high resolution.

### Task 5: Verify And Commit

**Files:**

- All changed docs and assets.

**Interfaces:**

- Consumes: Tasks 1-4.

- Produces: A clean, committed maintenance branch.

- [ ] **Step 1: Run docs checks**

Run:

```bash
python3 tools/check-showcase-parity.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 2: Run link/stale scans**

Run:

```bash
rg -n "16 distinct|2\\.6\\.0|237 conformance|41/237|46 ADRs|22 numbered|Swift.*subset" README.md examples docs spec langs -g '*.md' || true
rg -n "notes-showcase-vmx-components|architecture.png|class-diagram.png|notes-showcase-vm-hierarchy.png" README.md examples -g '*.md'
```

Expected: no current stale claims; new diagrams are linked.

- [ ] **Step 3: Commit**

Run:

```bash
git add README.md examples assets docs/superpowers/plans/2026-07-01-vmx-docs-and-diagrams-refresh.md
git commit -m "docs: refresh diagrams and examples documentation"
```
