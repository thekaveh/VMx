/**
 * Browser smoke test: serve the built `dist/` with `vite preview`, drive it in
 * headless Chromium, and assert construct, edit, command, error and dispose.
 *
 * Run it with `npm run test:browser` after `npm run build`. It fails on any
 * console error or warning, which includes React's "Invalid hook call" from a
 * duplicate React copy, and when the rendered VMx version differs from the
 * exact pin in package.json.
 */
import { readFileSync } from "node:fs";

import { chromium } from "playwright";
import { preview } from "vite";

const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const pin = manifest.dependencies["@thekaveh/vmx"];
const TIMEOUT = 5_000;

const server = await preview({
  logLevel: "warn",
  preview: { host: "127.0.0.1", port: 4173, strictPort: false, open: false },
});
const url = server.resolvedUrls?.local[0];
if (url === undefined) throw new Error("vite preview reported no local URL");

const browser = await chromium.launch();
const problems = [];
let failed = false;

try {
  console.log(`browser: chromium ${browser.version()}`);
  const page = await browser.newPage();
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      problems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  await page.goto(url);

  const text = (testId) =>
    page
      .getByTestId(testId)
      .textContent({ timeout: 1_000 })
      .catch(() => "<missing element>");
  const expectText = async (testId, expected, label) => {
    try {
      await page.waitForFunction(
        ([id, value]) => document.querySelector(`[data-testid="${id}"]`)?.textContent === value,
        [testId, expected],
        { timeout: TIMEOUT },
      );
    } catch {
      throw new Error(`${label}: expected ${testId} "${expected}", found "${await text(testId)}"`);
    }
    console.log(`ok - ${label}`);
  };
  const save = page.getByRole("button", { name: "Save" });
  const expectSaveEnabled = async (enabled, label) => {
    await page.waitForFunction(
      (value) => {
        const button = [...document.querySelectorAll("button")].find((b) => b.textContent === "Save");
        return button !== undefined && button.disabled === !value;
      },
      enabled,
      { timeout: TIMEOUT },
    );
    console.log(`ok - ${label}`);
  };
  const title = page.getByTestId("title");

  // Construct: the effect builds and constructs the notebook.
  await expectText("vmx-version", pin, `the page renders VMx ${pin}, the package.json pin`);
  await expectText("lifecycle", "constructed", "the notebook is constructed");
  await expectText("hint", "Groceries", "the first note is current");

  // Edit: the input writes the VM model; the hub re-renders the hint.
  await title.fill("Groceries for Monday");
  await expectText("hint", "Groceries for Monday", "an edit re-renders the VM state");

  // Command: `useCommand` tracks canExecute; the task saves the note.
  await title.fill("   ");
  await expectSaveEnabled(false, "Save is disabled for a blank title");
  await title.fill("Groceries for Monday");
  await expectSaveEnabled(true, "Save is enabled for a valid title");
  await save.click();
  await expectText("saved", "Groceries for Monday", "the command saved the first note");

  // Error: the store rejects a duplicate title and the page shows it.
  await page.getByTestId("select-2").click();
  await expectText("hint", "Ideas", "selecting note 2 re-renders the current note");
  await title.fill("Groceries for Monday");
  await save.click();
  await expectText(
    "error",
    'another note already uses the title "Groceries for Monday"',
    "a duplicate title shows the store error",
  );

  // Recover: fix the title and save again.
  await title.fill("Ideas for Monday");
  await save.click();
  await expectText("saved", "Groceries for Monday, Ideas for Monday", "the fixed note saves");
  await expectText("error", "", "the error clears after a successful save");

  // Dispose: unmounting the notebook disposes the store, the VMs and the hub.
  await page.getByRole("button", { name: "Close notebook" }).click();
  await expectText("lifecycle", "disposed", "unmount disposes the notebook");

  if (problems.length > 0) throw new Error("the console reported problems");
  console.log("ok - no console errors or warnings (no invalid hook call)");
  console.log("PASSED: construct, edit, command, error and dispose in a real browser");
} catch (error) {
  failed = true;
  console.error(`FAILED: ${error instanceof Error ? error.message : String(error)}`);
  for (const problem of problems) console.error(`console: ${problem}`);
} finally {
  await browser.close();
  await server.close();
}

process.exitCode = failed ? 1 : 0;
