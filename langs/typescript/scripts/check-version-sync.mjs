#!/usr/bin/env node
/**
 * Fails the build if src/version.ts is out of sync with package.json.
 *
 * version.ts hardcodes `__version__` so the bundled package can advertise its
 * own version without a runtime package.json read. Drift between the two would
 * surface as MinSpecVersion checks reporting the wrong number, so we gate it
 * here as part of `prebuild`.
 */

import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf-8"));
const versionTs = readFileSync(join(root, "src", "version.ts"), "utf-8");

const m = versionTs.match(/__version__\s*=\s*"([^"]+)"/);
if (!m) {
  console.error("check-version-sync: could not find __version__ in src/version.ts");
  process.exit(1);
}

const versionInTs = m[1];
const versionInPkg = pkg.version;

if (versionInTs !== versionInPkg) {
  console.error(
    `check-version-sync: drift detected.\n` +
      `  package.json:   ${versionInPkg}\n` +
      `  src/version.ts: ${versionInTs}\n` +
      `Update src/version.ts to match package.json.`,
  );
  process.exit(1);
}

console.log(`check-version-sync: package.json and src/version.ts agree on ${versionInPkg}`);
