# VMx TypeScript examples

Self-contained demos of the [VMx TypeScript package](../../langs/typescript/).

## 1. Setup

Examples here use [tsx](https://github.com/privatenumber/tsx) to run
TypeScript directly without a separate compile step. The run snippets below
invoke it via `npx`, which fetches `tsx` on demand — no global install
required (`npm install -g tsx` is optional if you prefer it available
on `$PATH`).

---

## 2. Example 1 — `hello-vmx/` (Node script)

Minimal console demo. Demonstrates:

1. Building a `ComponentVMOf<UserModel>` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` and
   `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub
   message.

**Run against the published package:**

```bash
cd examples/typescript/hello-vmx
npm install vmx
npx tsx index.ts
```

**Run against the local source build (from a clone of this repo):**

```bash
# From the repo root: build the local library once
cd langs/typescript
npm ci
npm run build

# Then resolve the example's file: dependency on the local build and run it
cd ../../examples/typescript/hello-vmx
npm install
npx tsx index.ts
```

---

## 3. Project layout

```
examples/typescript/
├── README.md          # this file
└── hello-vmx/
    ├── index.ts       # entry point
    ├── package.json   # standalone npm workspace (file: dep on ../../../langs/typescript)
    └── tsconfig.json  # ES2022 + bundler module resolution for `tsx index.ts`
```
