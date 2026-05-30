# VMx TypeScript examples

Self-contained demos of the [VMx TypeScript package](../../langs/typescript/).

## 1. Setup

Examples here use [tsx](https://github.com/privatenumber/tsx) to run
TypeScript directly without a separate compile step. Install once:

```bash
npm install -g tsx
```

---

## 2. Example 1 — `console/hello-vmx/` (Node script)

Minimal console demo. Demonstrates:

1. Building a `ComponentVMOf<UserModel>` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` and
   `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub
   message.

**Run against the published package:**

```bash
npm install vmx
npx tsx console/hello-vmx/index.ts
```

**Run against the local source build (from a clone of this repo):**

```bash
# From the repo root
cd langs/typescript
npm ci
npm run build
cd ../../examples/typescript
npm install ../../langs/typescript
npx tsx console/hello-vmx/index.ts
```

---

## 3. Example 2 — `react/notes-showcase/` (React 18 + Vite, flagship)

The Notes Workspace flagship app — a single-page web app on React 18 + Vite
that exercises **15 distinct VMx features** in one cohesive scenario
(notebooks tree, paged + filterable notes list, FormVM editor,
capability-aware action bar, notifications, async lifecycle, dialogs,
`AggregateVM6` root). Pure-VM contract enforced via ESLint's
`no-restricted-imports` rule — view components never call `useState` /
`useReducer`.

**Run (dev server):**

```bash
cd react/notes-showcase
npm install
npm run dev         # http://localhost:5173
```

**Production build:**

```bash
cd react/notes-showcase
npm run build       # static bundle in dist/
```

See [`react/notes-showcase/README.md`](react/notes-showcase/README.md) for
the project layout, feature-traceability, keybindings (`Mod+N`, `Mod+S`,
etc.), and a note on the temporary Vite plugin stubbing `node:fs|path|url`
for browser builds. Cross-flavor parity is documented in
[`../notes-showcase-parity.md`](../notes-showcase-parity.md); the canonical
scenario contract lives at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md).

---

## 4. Project layout

```
examples/typescript/
├── README.md              # this file
├── console/
│   └── hello-vmx/
│       └── index.ts       # entry point
└── react/
    └── notes-showcase/
        ├── package.json, vite.config.ts, tsconfig.json
        ├── src/{models,viewmodels,views}/
        └── tests/{models,viewmodels,views}/
```
