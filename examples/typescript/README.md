# VMx TypeScript examples

Self-contained demos of the [VMx TypeScript package](../../langs/typescript/).
The [Example Diagram Gallery](../../docs/content/examples/example-diagram-gallery.md)
collects the generated architecture diagrams for all examples.

## 1. Setup

Examples here use each example's checked-in `package-lock.json` and local npm
scripts. Run `npm ci` in the example directory before starting it.

Prerequisite: Node.js 20.19+, 22.13+, or 24+. Each example's `engines` field
sets this range.

---

## 2. Example 1 — `console/hello-vmx/` (Node script)

Minimal console demo. Demonstrates:

1. Building a `ComponentVMOf<UserModel>` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` and
   `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub
   message.

Diagram:
[`typescript-console-hello-vmx.svg`](../../docs/assets/diagrams/typescript-console-hello-vmx.svg)
([HTML](../../docs/assets/diagrams/typescript-console-hello-vmx.html),
[PNG](../../docs/assets/diagrams/typescript-console-hello-vmx.png)).

**Run against the local source build (from a clone of this repo):**

```bash
cd examples/typescript/console/hello-vmx
npm ci
npm start          # runs the local VMx build first
```

---

## 3. Example 2 — `react/notes-showcase/` (React 19 + Vite, flagship)

The Notes Workspace flagship app is a single-page web app on React 19 + Vite
that exercises 19 VMx features in one scenario. The
[parity matrix](../notes-showcase-parity.md) lists them. ESLint's
`no-restricted-imports` rule enforces the Pure-VM contract: view components
never call `useState` or `useReducer`.

Diagram:
[`typescript-react-notes-showcase.svg`](../../docs/assets/diagrams/typescript-react-notes-showcase.svg)
([HTML](../../docs/assets/diagrams/typescript-react-notes-showcase.html),
[PNG](../../docs/assets/diagrams/typescript-react-notes-showcase.png)).

**Run (dev server):**

```bash
cd examples/typescript/react/notes-showcase
npm ci
npm run dev         # builds local VMx and @thekaveh/vmx-react, then serves http://localhost:5173
```

**Production build** (from the same directory):

```bash
npm run build       # builds local VMx and @thekaveh/vmx-react, then writes dist/
```

See [`react/notes-showcase/README.md`](react/notes-showcase/README.md) for
the project layout, feature traceability, and keybindings (`Mod+N`, `Mod+S`,
and others). The canonical scenario contract is at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md).

---

## 4. Example 3 — `integration-recipes/` (Vue, Svelte, Solid)

This project is not an app. It holds the Vue, Svelte, and Solid recipe files
that the integration guides embed, and tests them on jsdom. Its `npm test` and
`npm run typecheck` scripts do not build VMx, so build the local VMx package
first. Run these commands from the repository root:

```bash
npm --prefix langs/typescript ci
npm --prefix langs/typescript run build
cd examples/typescript/integration-recipes
npm ci
npm test            # runs the Vue, Svelte, and Solid recipe tests
npm run typecheck   # compile-only check, including .vue and .svelte shims
```

The [Vue](../../docs/content/integration/vue.md),
[Svelte](../../docs/content/integration/svelte.md), and
[Solid](../../docs/content/integration/solid.md) guides show these files.

---

## 5. Project layout

```
examples/typescript/
├── README.md              # this file
├── console/
│   └── hello-vmx/
│       └── index.ts       # entry point
├── integration-recipes/   # Vue, Svelte, and Solid recipes (§4)
└── react/
    └── notes-showcase/
        ├── package.json, vite.config.ts, tsconfig.json
        ├── src/{messages,models,viewmodels,views}/
        └── tests/{models,recipes,viewmodels,views}/
```
