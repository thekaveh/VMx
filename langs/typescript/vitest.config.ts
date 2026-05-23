import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    setupFiles: ["./tests/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**"],
      exclude: ["src/fixtures/**"],
    },
  },
  resolve: {
    // Allow test files to import from src using the same module resolution
    // as the source code.
    conditions: ["import", "default"],
  },
});
