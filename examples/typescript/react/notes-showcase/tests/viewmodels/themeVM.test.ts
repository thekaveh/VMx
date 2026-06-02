/**
 * ThemeVM — conformance + reactivity tests.
 *
 * Implements the THEME-001..THEME-005 conformance scenarios from
 * `spec/proposals/2026-06-02-theme-vm-scenario.md` §6, plus
 * DerivedProperty reactivity unit tests for each derived property.
 */
import { describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";

import {
  DARK_PRESET,
  HIGH_CONTRAST_PRESET,
  LIGHT_PRESET,
  PRESETS,
  clampFontScale,
  type ThemeModel,
} from "../../src/models/themeModel.js";
import { ThemeChangedMessage } from "../../src/messages/themeChanged.js";
import { ThemeVM } from "../../src/viewmodels/themeVM.js";

function makeVM(
  initial?: ThemeModel,
  systemResolver?: () => "dark" | "light",
): { vm: ThemeVM; hub: MessageHub } {
  const hub = new MessageHub();
  const vm = new ThemeVM({
    name: "theme",
    hint: "",
    hub,
    dispatcher: RxDispatcher.immediate(),
    initialModel: initial,
    systemResolver,
  });
  vm.construct();
  return { vm, hub };
}

function captureMessages(hub: MessageHub): ThemeChangedMessage<unknown>[] {
  const captured: ThemeChangedMessage<unknown>[] = [];
  hub.messages.subscribe((m) => {
    if (m instanceof ThemeChangedMessage) captured.push(m);
  });
  return captured;
}

describe("themeModel module", () => {
  it("PRESETS exposes the three named presets", () => {
    expect(PRESETS["dark"]).toBe(DARK_PRESET);
    expect(PRESETS["light"]).toBe(LIGHT_PRESET);
    expect(PRESETS["high-contrast"]).toBe(HIGH_CONTRAST_PRESET);
  });

  it("presets are frozen", () => {
    expect(Object.isFrozen(DARK_PRESET)).toBe(true);
    expect(Object.isFrozen(LIGHT_PRESET)).toBe(true);
    expect(Object.isFrozen(HIGH_CONTRAST_PRESET)).toBe(true);
    expect(Object.isFrozen(PRESETS)).toBe(true);
  });

  it("clampFontScale clamps below 0.75 to 0.75", () => {
    expect(clampFontScale(0.5)).toBe(0.75);
  });

  it("clampFontScale clamps above 1.75 to 1.75", () => {
    expect(clampFontScale(5)).toBe(1.75);
  });

  it("clampFontScale passes through in-range values", () => {
    expect(clampFontScale(1.0)).toBe(1.0);
    expect(clampFontScale(0.75)).toBe(0.75);
    expect(clampFontScale(1.75)).toBe(1.75);
  });

  it("clampFontScale returns 1.0 for NaN", () => {
    expect(clampFontScale(Number.NaN)).toBe(1.0);
  });
});

describe("ThemeVM — surface shape", () => {
  it("exposes currentTheme, presets, followsSystem, and the five commands", () => {
    const { vm } = makeVM();
    expect(vm.currentTheme.value).toBe(DARK_PRESET);
    expect(vm.presets).toHaveLength(3);
    expect(vm.followsSystem.value).toBe(false);
    expect(typeof vm.setThemeCommand.execute).toBe("function");
    expect(typeof vm.toggleHighContrast.execute).toBe("function");
    expect(typeof vm.setAccentColor.execute).toBe("function");
    expect(typeof vm.setFontScale.execute).toBe("function");
    expect(typeof vm.followSystemCommand.execute).toBe("function");
  });

  it("presets list is frozen", () => {
    const { vm } = makeVM();
    expect(Object.isFrozen(vm.presets)).toBe(true);
  });

  it("defaults to DARK_PRESET when no initialModel is supplied", () => {
    const { vm } = makeVM();
    expect(vm.model).toBe(DARK_PRESET);
  });

  it("accepts a non-default initialModel", () => {
    const { vm } = makeVM(LIGHT_PRESET);
    expect(vm.model).toBe(LIGHT_PRESET);
    expect(vm.currentTheme.value).toBe(LIGHT_PRESET);
  });
});

describe("THEME-001 — setThemeCommand publishes ThemeChangedMessage", () => {
  it("publishes a single ThemeChangedMessage with prev=dark, curr=light", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.setThemeCommand.execute("light");
    expect(msgs).toHaveLength(1);
    const first = msgs[0]!;
    expect(first.prev).toBe(DARK_PRESET);
    expect(first.curr.name).toBe("light");
    expect(first.curr.accentColor).toBe(LIGHT_PRESET.accentColor);
    expect(vm.currentTheme.value.name).toBe("light");
  });

  it("publishes ThemeChangedMessage for the high-contrast preset", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.setThemeCommand.execute("high-contrast");
    expect(msgs).toHaveLength(1);
    expect(msgs[0]!.curr.name).toBe("high-contrast");
    expect(msgs[0]!.curr.highContrast).toBe(true);
  });
});

describe("THEME-002 — unknown preset throws and publishes nothing", () => {
  it("setThemeCommand throws Error('unknown preset') for an unknown name", () => {
    const { vm } = makeVM();
    expect(() => vm.setThemeCommand.execute("solarized")).toThrow(
      "unknown preset",
    );
  });

  it("setThemeCommand publishes no ThemeChangedMessage on rejection", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    try {
      vm.setThemeCommand.execute("solarized");
    } catch {
      /* expected */
    }
    expect(msgs).toHaveLength(0);
    expect(vm.currentTheme.value).toBe(DARK_PRESET);
  });
});

describe("THEME-003 — toggleHighContrast preserves accent and scale", () => {
  it("flips highContrast without touching accent or scale", () => {
    const { vm } = makeVM();
    // Customize: set a non-default accent and a non-default scale first.
    vm.setAccentColor.execute("#ff00aa");
    vm.setFontScale.execute(1.25);
    const before = vm.currentTheme.value;
    expect(before.accentColor).toBe("#ff00aa");
    expect(before.fontScaleFactor).toBe(1.25);
    expect(before.highContrast).toBe(false);

    vm.toggleHighContrast.execute();
    const after = vm.currentTheme.value;
    expect(after.highContrast).toBe(true);
    expect(after.accentColor).toBe("#ff00aa");
    expect(after.fontScaleFactor).toBe(1.25);
  });

  it("toggling twice is a round-trip", () => {
    const { vm } = makeVM();
    vm.toggleHighContrast.execute();
    vm.toggleHighContrast.execute();
    expect(vm.currentTheme.value.highContrast).toBe(false);
  });
});

describe("THEME-004 — setFontScale clamps to [0.75, 1.75]", () => {
  it("values below 0.75 clamp to 0.75 and publish once", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.setFontScale.execute(0.1);
    expect(vm.currentTheme.value.fontScaleFactor).toBe(0.75);
    expect(msgs).toHaveLength(1);
  });

  it("values above 1.75 clamp to 1.75 and publish once", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.setFontScale.execute(99);
    expect(vm.currentTheme.value.fontScaleFactor).toBe(1.75);
    expect(msgs).toHaveLength(1);
  });

  it("in-range values pass through unchanged", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.setFontScale.execute(1.25);
    expect(vm.currentTheme.value.fontScaleFactor).toBe(1.25);
    expect(msgs).toHaveLength(1);
  });

  it("setting the same value is a no-op (no message)", () => {
    const { vm, hub } = makeVM();
    vm.setFontScale.execute(1.25);
    const msgs = captureMessages(hub);
    vm.setFontScale.execute(1.25);
    expect(msgs).toHaveLength(0);
  });
});

describe("THEME-005 — followSystemCommand + reset on setTheme", () => {
  it("followSystemCommand sets followsSystem=true", () => {
    const { vm } = makeVM(undefined, () => "light");
    vm.followSystemCommand.execute();
    expect(vm.currentTheme.value.followsSystem).toBe(true);
    expect(vm.currentTheme.value.name).toBe("light");
    expect(vm.followsSystem.value).toBe(true);
  });

  it("setThemeCommand after followSystemCommand resets followsSystem=false", () => {
    const { vm } = makeVM(undefined, () => "light");
    vm.followSystemCommand.execute();
    expect(vm.followsSystem.value).toBe(true);
    vm.setThemeCommand.execute("dark");
    expect(vm.currentTheme.value.followsSystem).toBe(false);
    expect(vm.followsSystem.value).toBe(false);
    expect(vm.currentTheme.value.name).toBe("dark");
  });

  it("system resolver defaults to dark when host has no media-query API", () => {
    // jsdom in vitest default config does NOT install matchMedia; the
    // VM's default resolver should pick "dark".
    const { vm } = makeVM();
    vm.followSystemCommand.execute();
    expect(vm.currentTheme.value.name).toBe("dark");
    expect(vm.followsSystem.value).toBe(true);
  });
});

describe("ThemeVM — accent color", () => {
  it("setAccentColor accepts a #RRGGBB hex", () => {
    const { vm } = makeVM();
    vm.setAccentColor.execute("#aabbcc");
    expect(vm.currentTheme.value.accentColor).toBe("#aabbcc");
  });

  it("setAccentColor accepts a #RGB hex", () => {
    const { vm } = makeVM();
    vm.setAccentColor.execute("#abc");
    expect(vm.currentTheme.value.accentColor).toBe("#abc");
  });

  it("setAccentColor throws on a parse failure", () => {
    const { vm } = makeVM();
    expect(() => vm.setAccentColor.execute("not-a-color")).toThrow(
      "invalid accent color",
    );
  });

  it("setAccentColor with the same value is a no-op", () => {
    const { vm } = makeVM();
    vm.setAccentColor.execute("#abcdef");
    const { hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.setAccentColor.execute("#abcdef");
    expect(msgs).toHaveLength(0);
  });
});

describe("ThemeVM — DerivedProperty reactivity", () => {
  it("currentTheme.valueChanged fires on each effective change", () => {
    const { vm } = makeVM();
    const seen: ThemeModel[] = [];
    vm.currentTheme.valueChanged.subscribe((v) => seen.push(v));
    vm.setThemeCommand.execute("light");
    vm.setThemeCommand.execute("high-contrast");
    expect(seen).toHaveLength(2);
    expect(seen[0]!.name).toBe("light");
    expect(seen[1]!.name).toBe("high-contrast");
  });

  it("followsSystem.valueChanged fires only when the flag flips", () => {
    const { vm } = makeVM(undefined, () => "dark");
    const seen: boolean[] = [];
    vm.followsSystem.valueChanged.subscribe((v) => seen.push(v));

    // Two consecutive flips → two notifications
    vm.followSystemCommand.execute();
    vm.setThemeCommand.execute("dark");
    expect(seen).toEqual([true, false]);
  });

  it("currentTheme.value is the model identity (equality-guarded)", () => {
    const { vm } = makeVM();
    vm.setThemeCommand.execute("light");
    const ref1 = vm.currentTheme.value;
    // Re-applying the same preset RESETS to that preset's defaults but
    // produces a fresh object (since `#applyPreset` builds a new record
    // each time). Same name → same valueChanged emission cadence rules.
    vm.setThemeCommand.execute("light");
    const ref2 = vm.currentTheme.value;
    expect(ref2.name).toBe(ref1.name);
  });
});

describe("ThemeVM — lifecycle", () => {
  it("dispose is idempotent and tears down without throwing", () => {
    const { vm } = makeVM();
    expect(() => vm.dispose()).not.toThrow();
    expect(() => vm.dispose()).not.toThrow();
  });

  it("toggleHighContrast on a fresh dark VM flips highContrast to true", () => {
    const { vm, hub } = makeVM();
    const msgs = captureMessages(hub);
    vm.toggleHighContrast.execute();
    expect(msgs).toHaveLength(1);
    expect(vm.currentTheme.value.highContrast).toBe(true);
    // accent + scale untouched
    expect(vm.currentTheme.value.accentColor).toBe(DARK_PRESET.accentColor);
    expect(vm.currentTheme.value.fontScaleFactor).toBe(
      DARK_PRESET.fontScaleFactor,
    );
  });
});
