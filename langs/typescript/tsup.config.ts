import { defineConfig } from "tsup";

export default defineConfig({
  entry: {
    index: "src/index.ts",
    notifications: "src/notifications/index.ts",
    conformance: "src/conformance/index.ts",
  },
  format: ["esm", "cjs"],
  dts: true,
  sourcemap: true,
  clean: true,
  // VMX-024: code-splitting hoists first-party classes shared by both the main
  // (`.`) and the `./notifications` entry points into a single shared chunk
  // (per format), instead of re-bundling them into each entry. Without this,
  // `RelayCommand` was emitted twice — once per bundle — so a command obtained
  // from `@thekaveh/vmx/notifications` failed `instanceof RelayCommand` against
  // the class exported from `@thekaveh/vmx`. esbuild splits both the ESM and CJS
  // outputs here, so the shared class identity holds across every published entry.
  splitting: true,
  treeshake: true,
});
