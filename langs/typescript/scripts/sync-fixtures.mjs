#!/usr/bin/env node
/**
 * Copies spec/fixtures/*.json into src/fixtures/ so they are available
 * both at test time (via fs.readFileSync relative to import.meta.url) and
 * inside a published npm package (the dist includes src/fixtures/).
 */

import { copyFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcFixtures = join(__dirname, "..", "..", "..", "spec", "fixtures");
const destFixtures = join(__dirname, "..", "src", "fixtures");
const srcSchemas = join(__dirname, "..", "..", "..", "spec", "schemas");
const destSchemas = join(__dirname, "..", "src", "conformance", "schemas");

if (!existsSync(srcFixtures)) {
  console.error(
    `sync-fixtures: source directory not found: ${srcFixtures}\n` +
      `Are you running this from inside a clone of the VMx monorepo?`,
  );
  process.exit(1);
}

mkdirSync(destFixtures, { recursive: true });

const files = readdirSync(srcFixtures).filter((f) => f.endsWith(".json"));
for (const file of files) {
  copyFileSync(join(srcFixtures, file), join(destFixtures, file));
}

console.log(`sync-fixtures: copied ${files.length} file(s) → src/fixtures/`);

if (!existsSync(srcSchemas)) {
  console.error(`sync-fixtures: source directory not found: ${srcSchemas}`);
  process.exit(1);
}

mkdirSync(destSchemas, { recursive: true });
const schemas = readdirSync(srcSchemas).filter((f) => f.endsWith(".json"));
for (const file of schemas) {
  copyFileSync(join(srcSchemas, file), join(destSchemas, file));
}

console.log(
  `sync-fixtures: copied ${schemas.length} file(s) → src/conformance/schemas/`,
);
