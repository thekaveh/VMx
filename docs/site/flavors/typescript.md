# TypeScript

## Snapshot

- Install: `npm install @thekaveh/vmx rxjs`
- Publication status: the scoped package name is the supported surface, but it
  has not been published yet; use a local workspace or source reference until a
  `typescript-v*` release publishes it.
- Reactive primitive: `rxjs`
- Naming idiom: camelCase

## What To Reach For

TypeScript is the best fit when you want browser-safe VMx usage with modern
bundlers, React-style external-store wiring, or a shared VM layer across web
and desktop webview hosts.

## Pointers

- Flavor README:
  [langs/typescript/README.md](https://github.com/thekaveh/VMx/blob/main/langs/typescript/README.md)
- Getting started guide:
  [docs/getting-started/typescript.md](https://github.com/thekaveh/VMx/blob/main/docs/getting-started/typescript.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- React recipe:
  [docs/integration/react.md](https://github.com/thekaveh/VMx/blob/main/docs/integration/react.md)

## Current Example Coverage

- Console: `examples/typescript/console/hello-vmx/`
- React flagship: `examples/typescript/react/notes-showcase/`

The TypeScript README also documents the browser-safety contract and the peer
dependency requirement for `rxjs`.
