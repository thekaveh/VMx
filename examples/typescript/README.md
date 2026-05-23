# VMx TypeScript examples

| Directory     | Description                                      |
| ------------- | ------------------------------------------------ |
| `hello-vmx/`  | Minimal console demo — lifecycle + model changes |

## Running the hello-vmx example

From this directory, with [tsx](https://github.com/privatenumber/tsx) installed:

```bash
npm install vmx tsx
npx tsx hello-vmx/index.ts
```

Or run against the local source build:

```bash
# From the repo root
cd langs/typescript
npm ci
npm run build
cd ../../examples/typescript
npm install ../../langs/typescript tsx
npx tsx hello-vmx/index.ts
```
