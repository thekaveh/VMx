import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Stubs Node built-ins for browser builds.
 *
 * VMx core's `lifecycle/transitionValidator.ts` imports `node:fs` / `node:path`
 * / `node:url` at module load to lazily read a JSON fixture; the validator is
 * only invoked during VM lifecycle transitions (an asynchronous code path
 * unused by the React UI's hot path). Vite's default `__vite-browser-external`
 * shim returns an empty module — but the validator destructures named exports
 * (`readFileSync`, `dirname`, `join`, `fileURLToPath`), which rollup flags at
 * parse time.
 *
 * This plugin maps each `node:*` builtin to a tiny shim that exports a getter
 * proxy: any access returns a function that throws *if invoked* at runtime,
 * but the named-export bindings exist so rollup's parser is satisfied. The
 * notes-showcase never exercises the validator, so the throw is dead code.
 */
function nodeBuiltinStub(): Plugin {
  const stubs: Record<string, string> = {
    "node:fs": "fs",
    "node:path": "path",
    "node:url": "url",
  };
  const stubBody = `
    const handler = {
      get(_target, prop) {
        return (..._args) => {
          throw new Error(
            "Node built-in '" + String(prop) + "' was invoked in a browser build. " +
            "This usually means VMx tried to read a fixture file — the React UI " +
            "should never trigger that code path.",
          );
        };
      },
    };
    export const readFileSync = new Proxy(() => {}, handler);
    export const dirname = new Proxy(() => {}, handler);
    export const join = new Proxy(() => {}, handler);
    export const fileURLToPath = new Proxy(() => {}, handler);
    export default new Proxy({}, handler);
  `;
  return {
    name: "node-builtin-browser-stub",
    enforce: "pre",
    resolveId(id) {
      if (id in stubs || Object.values(stubs).includes(id)) {
        return `\0node-stub:${id}`;
      }
      return null;
    },
    load(id) {
      if (id.startsWith("\0node-stub:")) return stubBody;
      return null;
    },
  };
}

// Vitest sets `process.env.VITEST` when it boots its own Vite server. The
// stub plugin must be excluded in that path so VMx's lifecycle validator can
// read the real fixture (tests run in Node, not the browser).
const isTest = process.env.VITEST === "true";

export default defineConfig({
  plugins: isTest ? [react()] : [react(), nodeBuiltinStub()],
  test: {
    environment: "jsdom",
    globals: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: [
        "src/models/**",
        "src/viewmodels/**",
        "src/views/adapter/**",
      ],
      thresholds: { lines: 90, functions: 90, branches: 80, statements: 90 },
    },
  },
});
