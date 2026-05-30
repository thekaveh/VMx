/* Pure-VM enforcement scope is added in Phase 6 — this file just bootstraps. */
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: 2022, sourceType: "module" },
  env: { browser: true, es2022: true, node: true },
  plugins: ["@typescript-eslint", "react"],
  extends: ["eslint:recommended"],
};
