# 1. VMx

VMx is a lifecycle-aware MVVM viewmodel framework: one language-neutral
specification, five idiomatic source flavors, and a conformance catalog that
keeps C#, Python, TypeScript, Swift, and Rust aligned.

<div class="vmx-card-grid">
  <div class="vmx-card">
    <p class="vmx-card-title"><a href="installation/">Install</a></p>
    <p>Check source-tree version status and package commands for each flavor.</p>
  </div>
  <div class="vmx-card">
    <p class="vmx-card-title"><a href="getting-started/">Quickstart</a></p>
    <p>Build the shared component-plus-composite contract in each idiomatic flavor.</p>
  </div>
  <div class="vmx-card">
    <p class="vmx-card-title"><a href="architecture/">Architecture Map</a></p>
    <p>Walk the system, class, and lifecycle diagrams, then browse the full gallery.</p>
  </div>
</div>

## 1.1. Why VMx

- `spec/` is the source of truth for behavior, lifecycle, and conformance.
- Every flavor implements the shared normative concepts while following native naming conventions.
- The conformance catalog keeps 395 library IDs aligned across all five
  catalog-complete source flavors, plus 5 scenario IDs for flagship examples.
- Catalog coverage is distinct from member-level surface parity; the remaining
  [Rust convergence backlog](../maintenance/2026-07-16-rust-capability-parity.md)
  is explicit.

## 1.2. Start Here

- Read [Installation](installation.md) for source-tree status and package availability.
- Use [Quickstart](getting-started/index.md) for the smallest multi-language setup.
- Read [Core Concepts](core-concepts.md) before choosing VM families or extension points.
- Use [Architecture Map](architecture/index.md) when you want the system view first.
