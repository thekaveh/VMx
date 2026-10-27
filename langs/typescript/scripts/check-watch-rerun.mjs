// Checks that a Vitest watch rerun runs the dist-build tests against the
// rebuilt dist/index.js (#781). The script adds a probe export to the source,
// starts `vitest --watch` on a probe test that imports the built entry point,
// then changes the export and touches the probe test. The rerun must rebuild
// dist and load the new value; a stale module cache loads the old one.
// It restores every file it changes. Run it from langs/typescript.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const indexPath = resolve(packageRoot, "src", "index.ts");
const probeTestPath = resolve(packageRoot, "tests", "dist-build", "watchRerunProbe.test.ts");
const outPath = resolve(tmpdir(), `vmx-watch-rerun-${process.pid}.txt`);
const timeoutMs = 300_000;
const isWindows = process.platform === "win32";

const originalIndex = readFileSync(indexPath, "utf8");

function writeProbe(value) {
  writeFileSync(indexPath, `${originalIndex}\nexport const __watchRerunProbe = "${value}";\n`);
  writeFileSync(
    probeTestPath,
    [
      'import { appendFileSync } from "node:fs";',
      'import { resolve } from "node:path";',
      'import { pathToFileURL } from "node:url";',
      'import { expect, it } from "vitest";',
      "",
      `const expected = "${value}";`,
      "",
      'it("loads the rebuilt dist entry point", async () => {',
      '  const entry = pathToFileURL(resolve(__dirname, "..", "..", "dist", "index.js")).href;',
      "  const built = (await import(entry)) as { __watchRerunProbe?: string };",
      `  appendFileSync(${JSON.stringify(outPath)}, \`\${built.__watchRerunProbe}\\n\`);`,
      "  expect(built.__watchRerunProbe).toBe(expected);",
      "});",
      "",
    ].join("\n"),
  );
}

function recorded() {
  return existsSync(outPath) ? readFileSync(outPath, "utf8").split("\n").filter(Boolean) : [];
}

async function waitForLines(count) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (recorded().length >= count) return recorded();
    await new Promise((done) => setTimeout(done, 500));
  }
  throw new Error(`timed out waiting for ${count} probe run(s); recorded ${JSON.stringify(recorded())}`);
}

function stop(child) {
  if (child.exitCode !== null) return;
  if (isWindows) {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {
      child.kill("SIGTERM");
    }
  }
}

let child;
let failure = null;
try {
  rmSync(outPath, { force: true });
  writeProbe("first");
  child = spawn("npx", ["vitest", "--watch", "tests/dist-build/watchRerunProbe.test.ts"], {
    cwd: packageRoot,
    detached: !isWindows,
    shell: isWindows,
    stdio: "inherit",
  });
  const first = await waitForLines(1);
  console.log(`check-watch-rerun: first run loaded ${first[0]}`);
  // Change the source, then touch the probe test so Vitest reruns it.
  writeFileSync(indexPath, `${originalIndex}\nexport const __watchRerunProbe = "second";\n`);
  await new Promise((done) => setTimeout(done, 1000));
  writeProbe("second");
  const runs = await waitForLines(2);
  console.log(`check-watch-rerun: rerun loaded ${runs[1]}`);
  if (runs[1] !== "second") {
    failure = `the watch rerun loaded a stale dist: expected "second", got "${runs[1]}"`;
  }
} catch (error) {
  failure = error instanceof Error ? error.message : String(error);
} finally {
  if (child) stop(child);
  writeFileSync(indexPath, originalIndex);
  rmSync(probeTestPath, { force: true });
  rmSync(outPath, { force: true });
}

if (failure) {
  console.error(`check-watch-rerun: FAIL: ${failure}`);
  process.exit(1);
}
console.log("check-watch-rerun: OK: the watch rerun ran against the rebuilt dist/index.js");
process.exit(0);
