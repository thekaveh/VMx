/**
 * VMX-024 regression — shared first-party class identity across published
 * entry points.
 *
 * The dual-entry build (`.` and `./notifications`) previously bundled with
 * `splitting:false`, which re-emitted `RelayCommand` into BOTH the main and the
 * notifications bundles. A command obtained from `@thekaveh/vmx/notifications`
 * therefore failed `instanceof RelayCommand` against the class exported from
 * `@thekaveh/vmx`, breaking any consumer that mixed the two entry points.
 *
 * This guarantee can only be proven against the BUILT dist — the source tree
 * shares a single module, so the bug is invisible to source-level tests. The
 * test builds the package (idempotent) and dynamically imports both built entry
 * points.
 */
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { queueScheduler } from "rxjs";
import { beforeAll, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..", "..");
const distIndex = resolve(pkgRoot, "dist", "index.js");
const distNotifications = resolve(pkgRoot, "dist", "notifications.js");
const require = createRequire(import.meta.url);
const rootSubpath = "@thekaveh/vmx";
const conformanceSubpath = "@thekaveh/vmx/conformance";

type MainModule = typeof import("../../src/index.js");
type NotificationsModule = typeof import("../../src/notifications/index.js");

beforeAll(() => {
  // Build once for every assertion in this file. Multiple dist test files must
  // not run concurrent `tsup --clean` builds against the same output directory.
  execSync("npm run build", { cwd: pkgRoot, stdio: "ignore" });
}, 180_000);

describe("VMX-024: shared class identity across published entry points", () => {
  it("a ./notifications command is instanceof RelayCommand from the main entry", async () => {
    const main = (await import(pathToFileURL(distIndex).href)) as MainModule;
    const notifications = (await import(
      pathToFileURL(distNotifications).href
    )) as NotificationsModule;

    const hub = new notifications.NotificationHub();
    const notification = new notifications.Notification(
      notifications.NotificationType.Confirmation,
      "confirm?",
    );
    void hub.post(notification);
    const vm = new notifications.ConfirmationVM(
      notification,
      hub,
      queueScheduler,
    );

    // Before VMX-024 (splitting:true) these were FALSE — each entry point
    // carried its own re-bundled RelayCommand class.
    expect(vm.approveCommand).toBeInstanceOf(main.RelayCommand);
    expect(vm.rejectCommand).toBeInstanceOf(main.RelayCommand);
    expect(vm.dismissCommand).toBeInstanceOf(main.RelayCommand);

    vm.dispose();
    hub.dispose();
  });
});

describe("built consumer conformance entry point", () => {
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
    const root = (await import(rootSubpath)) as Record<string, unknown>;
    const rootEsm = readFileSync(resolve(pkgRoot, "dist", "index.js"), "utf8");
    const rootCjs = readFileSync(resolve(pkgRoot, "dist", "index.cjs"), "utf8");

    expect(root["runConsumerConformance"]).toBeUndefined();
    expect(rootEsm).not.toContain("Ajv2020");
    expect(rootCjs).not.toContain("Ajv2020");
  });
});
