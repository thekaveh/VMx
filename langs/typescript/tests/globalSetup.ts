import { execSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { TestProject } from "vitest/node";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const generatedDirectories = ["dist", "src/fixtures", "src/conformance/schemas"].map(
  (directory) => resolve(packageRoot, directory),
);

export function isGeneratedBuildPath(file: string): boolean {
  const absolute = resolve(file);
  return generatedDirectories.some(
    (directory) => absolute === directory || absolute.startsWith(`${directory}${sep}`),
  );
}

function generatedFiles(): string[] {
  return generatedDirectories.flatMap((directory) =>
    existsSync(directory)
      ? readdirSync(directory).map((file) => resolve(directory, file))
      : [],
  );
}

function build(project: TestProject): void {
  const previous = generatedFiles();
  execSync("npm run build", { cwd: packageRoot, stdio: "inherit" });
  // The watcher ignores generated writes; invalidate old and new chunk names.
  for (const file of new Set([...previous, ...generatedFiles()])) {
    project.vitest.invalidateFile(file);
  }
}

export default function setup(project: TestProject): void {
  build(project);
  project.onTestsRerun(async () => {
    // Manual reruns may be requested while the preceding workers are active.
    await project.vitest.waitForTestRunEnd();
    build(project);
  });
}
