import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";
import { execSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(here, "..", "..");
const require = createRequire(import.meta.url);
const conformanceSubpath = "@thekaveh/vmx/conformance";

describe("built consumer conformance entry point", () => {
  beforeAll(() => {
    execSync("npm run build", { cwd: packageRoot, stdio: "ignore" });
  }, 180_000);

  it("loads the same public API from ESM and CommonJS", async () => {
    const esm = (await import(conformanceSubpath)) as Record<string, unknown>;
    const commonjs = require(conformanceSubpath) as Record<string, unknown>;

    for (const module of [esm, commonjs]) {
      expect(module["parseConsumerConformance"]).toBeTypeOf("function");
      expect(module["runConsumerConformance"]).toBeTypeOf("function");
      expect(module["adaptCommandTruthTableFixture"]).toBeTypeOf("function");
      expect(module["consumerConformanceSchema"]).toBeTypeOf("object");
    }
  });

  it("keeps conformance tooling and Ajv out of the root entry", async () => {
    const root = (await import("@thekaveh/vmx")) as Record<string, unknown>;
    const rootEsm = readFileSync(resolve(packageRoot, "dist", "index.js"), "utf8");
    const rootCjs = readFileSync(resolve(packageRoot, "dist", "index.cjs"), "utf8");

    expect(root["runConsumerConformance"]).toBeUndefined();
    expect(rootEsm).not.toContain("Ajv2020");
    expect(rootCjs).not.toContain("Ajv2020");
  });
});
