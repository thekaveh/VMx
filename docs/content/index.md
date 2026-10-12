<p align="center">
  <img src="../../assets/vmx-poster.png" alt="VMx framework across C#, Python, TypeScript, Swift, and Rust" width="100%">
</p>

<h1 align="center">1. VMx</h1>

<!-- vmx-opener:start -->

<p align="center"><strong>One specification. Five idiomatic flavors. Predictable MVVM behavior across UI stacks.</strong></p>

<p align="center">VMx is a UI-neutral MVVM framework for building viewmodel trees with an explicit lifecycle, a message hub, commands, and observable collections. One language-neutral specification defines its behavior, and the C#, Python, TypeScript, Swift, and Rust flavors implement it in their own language idioms.</p>

<!-- vmx-opener:end -->

<div class="vmx-card-grid">
  <div class="vmx-card">
    <p class="vmx-card-title"><a href="installation.md">Install</a></p>
    <p>Install a public package or reference a VMx checkout, flavor by flavor.</p>
  </div>
  <div class="vmx-card">
    <p class="vmx-card-title"><a href="getting-started/index.md">Quickstart</a></p>
    <p>Build the shared component-plus-composite contract in each idiomatic flavor.</p>
  </div>
  <div class="vmx-card">
    <p class="vmx-card-title"><a href="architecture/index.md">Architecture Map</a></p>
    <p>Walk the system, class, and lifecycle diagrams, then browse the full gallery.</p>
  </div>
</div>

## 1.1. Availability

Python and Swift install from public registries. C#, TypeScript, the React
adapter, and Rust are complete in source but not yet published, so a project
uses them from a VMx checkout.

| Flavor        | Public package                                     | Source line |
| ------------- | -------------------------------------------------- | ----------- |
| Python        | `vmx` 3.23.0 on PyPI                               | 3.27.0      |
| Swift         | `VMx` 3.24.0 through SwiftPM                       | 3.28.0      |
| C#            | Not yet published to NuGet                         | 3.27.0      |
| TypeScript    | Not yet published to npm                           | 3.28.0      |
| React adapter | Not yet published to npm; follows the core package | 0.1.1       |
| Rust          | Not yet published to crates.io                     | 0.33.0      |

A source line can be ahead of its public package.
[Installation](installation.md) shows how to use each flavor today.

## 1.2. Why VMx

- Lifecycle is part of the contract: construction, destruction, and disposal
  follow one state machine in every flavor.
- `spec/` is the source of truth for behavior, and a shared conformance catalog
  checks every flavor against it.
- Each flavor keeps its language's naming and concurrency idioms instead of a
  lowest-common-denominator API.
- The core makes no UI assumption; the
  [integration recipes](integration/index.md) bind it to desktop, terminal, and
  web hosts.

## 1.3. Start Here

- [Installation](installation.md) — install a public package or reference a
  VMx checkout.
- [Quickstart](getting-started/index.md) — build the same small viewmodel tree
  in each flavor.
- [Core Concepts](core-concepts.md) — lifecycle, ownership, messaging, and the
  complete framework surface.
- [Architecture Map](architecture/index.md) — the system, class, and lifecycle
  diagrams.
