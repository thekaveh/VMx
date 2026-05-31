/* Pure-VM enforcement scope (spec §6.1) — components must route every piece
 * of state through the adapter hooks (useVm / useCommand / useDerivedProperty)
 * instead of reaching for `useState` / `useReducer`. The override below makes
 * those two imports a hard error inside the components tree, while leaving
 * the adapter (`src/views/adapter/**`) and hooks (`src/views/hooks/**`) free
 * to use them internally.
 */
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: 2022, sourceType: "module" },
  env: { browser: true, es2022: true, node: true },
  plugins: ["@typescript-eslint", "react"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  rules: {
    // `interface Foo { onSelect: (note: NoteVM) => void }` parameter names are
    // type-only and not bindings — the base `no-unused-vars` doesn't see that.
    // Defer to the TypeScript-aware rule, which does.
    "no-unused-vars": "off",
    "@typescript-eslint/no-unused-vars": [
      "error",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
  },
  overrides: [
    {
      files: ["src/views/components/**/*.{ts,tsx}"],
      rules: {
        "no-restricted-imports": ["error", {
          paths: [{
            name: "react",
            importNames: ["useState", "useReducer"],
            message:
              "Forbidden by Pure-VM contract (spec §6.1); use useVm / useCommand / useDerivedProperty from the adapter instead.",
          }],
        }],
      },
    },
  ],
};
