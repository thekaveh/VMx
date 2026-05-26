import { defineConfig } from "tsup";

export default defineConfig({
  entry: {
    index: "src/index.ts",
    notifications: "src/notifications/index.ts",
  },
  format: ["esm", "cjs"],
  dts: true,
  sourcemap: true,
  clean: true,
  splitting: false,
  treeshake: true,
});
