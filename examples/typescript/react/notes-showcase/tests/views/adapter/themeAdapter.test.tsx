/**
 * themeAdapter — adapter tests.
 *
 * Asserts that `applyTheme(themeVM, jsdom.document)` writes the four key
 * CSS custom properties (`--bg`, `--accent`, `--pane`, `--text-dim`) and
 * the `:root` font-size onto `document.documentElement.style`, and that
 * subsequent `themeVM` state changes propagate to the document.
 *
 * Also exercises the React-hook entry point via @testing-library/react.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";

import {
  DARK_PRESET,
  HIGH_CONTRAST_PRESET,
  LIGHT_PRESET,
} from "../../../src/models/themeModel.js";
import { ThemeVM } from "../../../src/viewmodels/themeVM.js";
import {
  applyTheme,
  useThemeAdapter,
} from "../../../src/views/adapter/themeAdapter.js";

afterEach(() => {
  // Reset :root inline styles so tests don't leak into one another.
  document.documentElement.removeAttribute("style");
  cleanup();
});

function makeVM(initial = DARK_PRESET): ThemeVM {
  const vm = new ThemeVM({
    name: "theme",
    hint: "",
    hub: new MessageHub(),
    dispatcher: RxDispatcher.immediate(),
    initialModel: initial,
  });
  vm.construct();
  return vm;
}

describe("applyTheme — initial sync", () => {
  it("writes the four key CSS variables for the current model on subscribe", () => {
    const vm = makeVM(DARK_PRESET);
    applyTheme(vm, document);
    const s = document.documentElement.style;
    expect(s.getPropertyValue("--bg")).toBe("#0e1320");
    expect(s.getPropertyValue("--accent")).toBe(DARK_PRESET.accentColor);
    expect(s.getPropertyValue("--pane")).toBe("#141b2d");
    expect(s.getPropertyValue("--text-dim")).toBe("#8a93a8");
  });

  it("writes font-size derived from baseline × fontScaleFactor", () => {
    const vm = makeVM(DARK_PRESET);
    applyTheme(vm, document);
    // baseline 14px × 1.0 = 14px
    expect(document.documentElement.style.getPropertyValue("font-size")).toBe(
      "14px",
    );
  });

  it("applies the light preset's palette", () => {
    const vm = makeVM(LIGHT_PRESET);
    applyTheme(vm, document);
    const s = document.documentElement.style;
    expect(s.getPropertyValue("--bg")).toBe("#F4F7FC");
    expect(s.getPropertyValue("--accent")).toBe(LIGHT_PRESET.accentColor);
    expect(s.getPropertyValue("--pane")).toBe("#FFFFFF");
    expect(s.getPropertyValue("--text-dim")).toBe("#5A6275");
  });

  it("applies the high-contrast palette", () => {
    const vm = makeVM(HIGH_CONTRAST_PRESET);
    applyTheme(vm, document);
    const s = document.documentElement.style;
    expect(s.getPropertyValue("--bg")).toBe("#000000");
    expect(s.getPropertyValue("--accent")).toBe(
      HIGH_CONTRAST_PRESET.accentColor,
    );
    expect(s.getPropertyValue("--pane")).toBe("#000000");
    expect(s.getPropertyValue("--text-dim")).toBe("#FFFFFF");
  });
});

describe("applyTheme — reactive updates", () => {
  it("re-applies on every currentTheme change", () => {
    const vm = makeVM(DARK_PRESET);
    applyTheme(vm, document);
    vm.setThemeCommand.execute("light");
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe(
      "#F4F7FC",
    );
    vm.setThemeCommand.execute("high-contrast");
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe(
      "#000000",
    );
  });

  it("font-size updates on setFontScale", () => {
    const vm = makeVM(DARK_PRESET);
    applyTheme(vm, document);
    vm.setFontScale.execute(1.5);
    expect(document.documentElement.style.getPropertyValue("font-size")).toBe(
      "21px",
    );
  });

  it("accent change propagates without touching the bg", () => {
    const vm = makeVM(DARK_PRESET);
    applyTheme(vm, document);
    vm.setAccentColor.execute("#ff00aa");
    const s = document.documentElement.style;
    expect(s.getPropertyValue("--accent")).toBe("#ff00aa");
    expect(s.getPropertyValue("--bg")).toBe("#0e1320");
  });
});

describe("applyTheme — teardown", () => {
  it("unsubscribe stops further DOM writes", () => {
    const vm = makeVM(DARK_PRESET);
    const dispose = applyTheme(vm, document);
    dispose();
    vm.setThemeCommand.execute("light");
    // Still on dark — the post-dispose change was not applied.
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe(
      "#0e1320",
    );
  });
});

describe("useThemeAdapter — React hook", () => {
  function Probe({ vm }: { vm: ThemeVM }): JSX.Element {
    useThemeAdapter(vm);
    return <span data-testid="probe">ok</span>;
  }

  it("applies the theme to document on mount", () => {
    const vm = makeVM(LIGHT_PRESET);
    render(<Probe vm={vm} />);
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe(
      "#F4F7FC",
    );
  });

  it("updates on subsequent VM changes while mounted", () => {
    const vm = makeVM(DARK_PRESET);
    render(<Probe vm={vm} />);
    vm.setThemeCommand.execute("high-contrast");
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe(
      "#000000",
    );
  });

  it("unmount disposes the subscription", () => {
    const vm = makeVM(DARK_PRESET);
    const { unmount } = render(<Probe vm={vm} />);
    unmount();
    vm.setThemeCommand.execute("light");
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe(
      "#0e1320",
    );
  });
});
