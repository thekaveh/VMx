import { defineConfig } from "vitest/config";
import { isGeneratedBuildPath } from "./tests/globalSetup.js";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    globalSetup: ["./tests/globalSetup.ts"],
    setupFiles: ["./tests/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**"],
      exclude: ["src/fixtures/**"],
      thresholds: {
        statements: 85,
        branches: 78,
        functions: 85,
        lines: 88,
      },
    },
  },
  server: {
    watch: {
      ignored: [isGeneratedBuildPath],
    },
  },
  resolve: {
    // Allow test files to import from src using the same module resolution
    // as the source code.
    conditions: ["import", "default"],
  },
});
