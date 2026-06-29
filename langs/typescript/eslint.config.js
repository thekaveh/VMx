import tseslint from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";

/** @type {import("eslint").Linter.FlatConfig[]} */
export default [
  {
    ignores: ["dist/**", "coverage/**", "node_modules/**"],
  },
  // ── Source files (strict) ─────────────────────────────────────────────────
  {
    files: ["src/**/*.ts"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        project: "./tsconfig.json",
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
    },
    rules: {
      ...tseslint.configs["strict-type-checked"].rules,
      // Allow _private convention alongside TypeScript #private fields.
      "@typescript-eslint/naming-convention": "off",
      // Explicit return types improve readability in public APIs.
      "@typescript-eslint/explicit-function-return-type": [
        "error",
        { allowExpressions: true, allowTypedFunctionExpressions: true },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      // Allow void return on subscribe callbacks.
      "@typescript-eslint/no-invalid-void-type": "off",
      // Params prefixed with _ are intentionally unused (common TS convention).
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Arrow shorthands like `.task(() => this.select())` are intentional void
      // returns, not accidental promise-returning confusion.
      "@typescript-eslint/no-confusing-void-expression": "off",
    },
  },
  // ── Test files (relaxed) ─────────────────────────────────────────────────
  {
    files: ["tests/**/*.ts"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        // Uses tsconfig.tests.json which includes both src and tests.
        project: "./tsconfig.tests.json",
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
    },
    rules: {
      ...tseslint.configs["recommended-type-checked"].rules,
      // Params prefixed with _ are intentionally unused (common TS convention).
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Test helper functions with inferred return types are fine.
      "@typescript-eslint/explicit-function-return-type": "off",
      // Non-null assertions in tests verify expected non-null state.
      "@typescript-eslint/no-non-null-assertion": "off",
      // Floating promises in tests are handled by the test framework.
      "@typescript-eslint/no-floating-promises": "off",
      // Unbound method references in expect() matchers are intentional.
      "@typescript-eslint/unbound-method": "off",
    },
  },
];
