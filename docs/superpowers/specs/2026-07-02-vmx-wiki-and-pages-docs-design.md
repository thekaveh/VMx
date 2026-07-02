# VMx Wiki And Pages Documentation Design

## Goal

Create a source-controlled documentation system for VMx that publishes to both
the GitHub wiki and `https://thekaveh.github.io/VMx/`. The documentation should
feel complete, navigable, and precise: a polished `.io` site with a restrained
Lunar Reference visual language, plus a GitHub-native wiki with hierarchical
navigation and practical reference pages.

## Source-Controlled Architecture

Documentation has one repository-owned source of truth and two publish targets:

- `docs/site/` contains the MkDocs Material source for the public `.io` site.
- `docs/wiki/` contains hierarchical source Markdown for the GitHub wiki.
- `docs/assets/diagrams/` contains generated diagram HTML/SVG/PNG assets used
  by both targets.
- `mkdocs.yml` defines the `.io` site navigation, theme, extensions, and strict
  build behavior.
- `.github/workflows/docs.yml` builds and deploys the Pages site.
- `tools/publish-wiki.sh` flattens `docs/wiki/` into `VMx.wiki.git`.
- `.github/workflows/wiki.yml` runs the wiki validation/export script and
  publishes the generated wiki pages after the site/docs checks pass.

The site can be richer than the wiki, but the two targets must not drift into
separate documentation products. Shared concepts, diagrams, release facts, and
primitive taxonomy should stay aligned.

## Visual Direction

The `.io` site uses a Lunar Reference theme: polished, minimal, calm, and
slightly sci-fi. It should prioritize readability over spectacle.

- MkDocs Material base.
- Light mode first, with a strong dark mode.
- Inter or similar for body copy, Space Grotesk or similar for headings, and
  JetBrains Mono for code.
- Cool neutral surfaces, subtle cyan/blue accents, crisp borders, compact cards,
  and copyable code blocks.
- Diagrams provide the visual identity; avoid loud gradients or decorative
  effects that compete with long-form reference material.

## Site Navigation

The public site should use this primary navigation:

1. Home
1. Installation
1. Quickstart
1. Core Concepts
1. Architecture Map
1. Framework Primitives
1. Language Flavors
1. Examples
1. Integration Recipes
1. Specification & Conformance
1. Contributing & Releases
1. Diagram Gallery

## Framework Primitives Taxonomy

The main reference section is **Framework Primitives**. Its structure is
family-first rather than dependency-first: users should be able to choose the
right VMx primitive for the modeling problem in front of them.

### ViewModel Families

Order the family pages from the most primitive VM shape and direct composition
forms toward specialized shapes:

1. **Component Family** — `ComponentVMBase`, `ComponentVM`, modeled components,
   readonly modeled variants, modeled hints, property-change behavior.
1. **Aggregate Family** — `AggregateVM1..6`, heterogeneous fixed-slot
   composition, construction/destruction order, and when aggregate composition
   is better than a wrapper VM.
1. **Group Family** — `GroupVM`, homogeneous peer collections, lifecycle
   orchestration, batch updates, and no-current-selection semantics.
1. **Composite Family** — `CompositeVM`, modeled composites, current selection,
   current-selection hooks, filtered/scored composite views, `PagedComposition`,
   `TokenPagedComposition`, and composite forwarding wrappers where relevant.
   `PagedComposition` and `TokenPagedComposition` are not subclasses of
   `CompositeVM`, but they belong here because they solve adjacent homogeneous
   collection-view problems.
1. **Hierarchical Family** — `HierarchicalVM`, recursive/tree composition,
   lazy/eager children, materialized paths, mutation, and
   `TreeStructureChangedMessage`.
1. **Forwarding & Wrapper Family** — `ForwardingComponentVM`,
   `ForwardingCompositeVM`, instrumentation, adaptation, and wrapper patterns.
1. **Specialized ViewModels & Coordinators** — dedicated pages for each
   specialized VM/coordinator, not a single combined page:
   - `FormVM`
   - `DiscriminatorVM`
   - `NotificationVM`
   - `ConfirmationVM`
   - `ModalVM` / VM-backed modal primitives where applicable

### Other Primitive Families

The remaining Framework Primitives pages are:

- **Command Families** — `RelayCommand`, typed relay commands,
  `AsyncRelayCommand`, `CompositeCommand`, `DecoratorCommand`,
  `ConfirmationDecoratorCommand`, fluent helpers, and modeled CRUD.
- **Capability Families** — the 22 micro-interfaces grouped by role:
  selection, expansion, lifecycle, dialog/form, search/filter, CRUD,
  current-container, management, and paging.
- **State & Reactive Helpers** — `DerivedProperty`, `ExpandableState`,
  `SearchableState`, and hub property helpers.
- **Services, Messages & Dispatching** — `MessageHub`, dispatchers, null
  services, message types, ordering, and threading guarantees.
- **Builders, Collections & Tree Utilities** — fluent builders, positional
  options, raw observable collections, batch handles, `walk`, `find`, and
  `walkExpanded`. Composite-oriented paging remains documented under the
  Composite Family, with links back to this lower-level collection page.

Every major primitive page should explain purpose, when to use it, ownership and
lifecycle behavior, pitfalls, and concise code snippets in C#, Python,
TypeScript, and Swift where the primitive exists.

## Wiki Structure

`docs/wiki/` should be hierarchical in source control even though GitHub wiki
publishes flat files. The publish script flattens paths into stable page names
and generates a hierarchical `_Sidebar.md`.

Recommended source layout:

```text
docs/wiki/
  Home.md
  _Sidebar.md
  _Footer.md
  Getting-Started.md
  Installation.md
  Quickstart.md
  Architecture/
    Architecture-Map.md
    Class-Architecture.md
    Lifecycle-and-Messaging.md
    Diagram-Gallery.md
  Framework-Primitives/
    Overview.md
    ViewModel-Families/
      Overview.md
      Component-Family.md
      Aggregate-Family.md
      Group-Family.md
      Composite-Family.md
      Hierarchical-Family.md
      Forwarding-and-Wrapper-Family.md
      Specialized/
        Overview.md
        FormVM.md
        DiscriminatorVM.md
        NotificationVM.md
        ConfirmationVM.md
        ModalVM.md
    Command-Families.md
    Capability-Families.md
    State-and-Reactive-Helpers.md
    Services-Messages-and-Dispatching.md
    Builders-Collections-and-Tree-Utilities.md
  Language-Flavors/
    Overview.md
    CSharp.md
    Python.md
    TypeScript.md
    Swift.md
    Cross-Language-Naming.md
  Examples/
    Overview.md
    Notes-Workspace.md
    Notes-Workspace-VM-Layer.md
    Global-Search-and-Token-Paging.md
    Editor-Mode-and-DiscriminatorVM.md
    Tag-Autocomplete-and-SearchableState.md
    Smaller-Examples.md
    Integration-Recipes.md
  Specification-and-Conformance/
    Overview.md
    Spec-Discipline.md
    ADRs.md
    Conformance-Catalog.md
    Fixtures.md
  Project/
    Contributing.md
    Releases.md
    FAQ.md
```

Flattened wiki page names should preserve hierarchy in the title, for example
`Framework-Primitives-ViewModel-Families-Composite-Family.md`. The sidebar
should render nested sections for Architecture, Framework Primitives,
ViewModel Families, Specialized ViewModels & Coordinators, Language Flavors,
Examples, Specification & Conformance, and Project.

## Diagram Plan

Diagrams are first-class documentation. Each generated diagram should have a
standalone HTML source, SVG export, and high-resolution landscape PNG export.
Use the diagram generation skill for visual consistency and export validation.

Initial diagram set:

1. **VMx System Architecture** — spec, shared concepts, four flavors, examples,
   CI, and docs/publishing.
1. **Class Architecture Map** — subclass/inheritance edges separated from
   composition, wrapper, decorator, owns, and adapts relationships. This diagram
   must not imply inheritance for composition-based primitives such as
   `PagedComposition` and `TokenPagedComposition`.
1. **ViewModel Families Map** — reader-facing taxonomy of Component, Aggregate,
   Group, Composite, Hierarchical, Forwarding, and Specialized families.
1. **Lifecycle & Messaging Flow** — lifecycle status transitions, hub emissions,
   dispatcher handoff, and parent-child cascades.
1. **Composite Family Deep Dive** — plain composites, current selection,
   filtered/scored views, finite paging, and token paging with when-to-use notes.
1. **Commands & Capabilities Map** — command families and capability groups with
   capability-aware consumers.
1. **Forms, Dialogs & Notifications Flow** — `FormVM`, validation,
   approve/deny, `IDialogService`, notification hub, render VMs, and confirmation
   decorators.
1. **Examples VM Layer Map** — how the Notes Workspace example VMs compose VMx
   primitives across all four supported languages.

The `.io` site should embed diagrams inline and link to standalone pages. The
wiki should use PNGs for reliable GitHub rendering and link to richer `.io`
diagram pages.

## Examples Documentation

The Notes Workspace flagship deserves a dedicated examples chapter:

- scenario overview
- cross-language implementation matrix
- VM hierarchy diagram
- VMx component-composition diagram
- `WorkspaceVM` and `AggregateVM6`
- global search via `TokenPagedComposition`
- editor mode via `DiscriminatorVM`
- tag autocomplete via `SearchableState`
- links to C# Avalonia, Python Textual, TypeScript React, and SwiftUI sources

Smaller examples should get a catalog with purpose, run command, platform,
featured VMx primitives, and links to source.

## Validation And Maintenance

Add lightweight checks so docs do not drift:

- `mkdocs build --strict` for the `.io` site.
- A wiki export validation script that flattens `docs/wiki/**.md`, checks
  generated `_Sidebar.md` links, and verifies required pages exist.
- A diagram validation step that checks every diagram has `.html`, `.svg`, and
  `.png`, verifies landscape dimensions, and confirms references from site or
  wiki pages.
- `git diff --check` and existing Markdown formatting hooks.

Maintenance rule: any public API or spec change that affects VMx primitives must
update the relevant primitive page, language snippets when public shape changes,
class architecture diagram when relationships change, and examples docs when a
showcased behavior changes.

## Implementation Constraints

- Keep existing README/spec docs as source material; do not delete or flatten
  the current documentation surface.
- Prefer source-derived snippets from examples and existing README guides.
- Preserve cross-language parity: examples and snippets should cover C#,
  Python, TypeScript, and Swift wherever the primitive exists.
- Use the Lunar Reference theme for the `.io` site.
- Do not publish wiki/pages until local validation passes.
