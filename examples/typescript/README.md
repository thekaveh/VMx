# VMx TypeScript examples

Self-contained demos of the [VMx TypeScript package](../../langs/typescript/).

## 1. Setup

Examples here use [tsx](https://github.com/privatenumber/tsx) to run
TypeScript directly without a separate compile step. Install once:

```bash
npm install -g tsx
```

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
npm install vmx
npx tsx hello-vmx/index.ts
```

**Run against the local source build (from a clone of this repo):**

```bash
# From the repo root
cd langs/typescript
npm ci
npm run build
cd ../../examples/typescript
npm install ../../langs/typescript
npx tsx hello-vmx/index.ts
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
