/**
 * themeAdapter — translates `themeVM.currentTheme` into CSS custom-property
 * writes on `document.documentElement`.
 *
 * Pure adapter per proposal §5 ("No business logic"). Two entry points:
 *
 *   * `useThemeAdapter(themeVM)` — React hook; wires a subscription for the
 *     lifetime of the host component (typically mounted once at app root).
 *   * `applyTheme(themeVM, document)` — non-hook form for tests and non-React
 *     hosts. Returns an `unsubscribe()` function.
 *
 * Both forms apply the *current* model immediately on subscribe, then update
 * on every subsequent `valueChanged` emission.
 *
 * The four CSS custom properties driven by this adapter:
 *
 *   * `--bg`        ← `themeVM.currentTheme.value.name` lookup table
 *   * `--accent`    ← `themeVM.currentTheme.value.accentColor`
 *   * `--pane`      ← preset-derived panel surface (`--panel` in proposal §5;
 *                     this flavor's css uses `--pane`, see views/theme.css)
 *   * `--text-dim`  ← preset-derived muted text color
 *
 * The `:root` font-size is set to `${fontScaleFactor * 14}px` (14 being the
 * baseline declared in `views/theme.css body { font-size: 14px }`).
 */
import { useEffect } from "react";
import type { Subscription } from "rxjs";

import type { ThemeModel } from "../../models/themeModel.js";
import type { ThemeVM } from "../../viewmodels/themeVM.js";

/** Resolved CSS variable values for a given ThemeModel. */
interface CssVars {
  readonly bg: string;
  readonly accent: string;
  readonly pane: string;
  readonly textDim: string;
}

const BASELINE_FONT_PX = 14;

/** Resolve `ThemeModel → CssVars` per the per-preset palette. */
function varsFor(model: ThemeModel): CssVars {
  // The proposal §3 names three presets but only specifies the `--bg` flip
  // and accent retention for light, plus black/white for high-contrast.
  // We materialize all four variables per preset here so the adapter is
  // self-contained — no need to round-trip through theme.css overrides.
  const accent = model.accentColor;
  switch (model.name) {
    case "light":
      return {
        bg: "#F4F7FC",
        accent,
        pane: "#FFFFFF",
        textDim: "#5A6275",
      };
    case "high-contrast":
      return {
        bg: "#000000",
        accent,
        pane: "#000000",
        textDim: "#FFFFFF",
      };
    case "dark":
    default:
      // The VM never publishes a "system"-named model (followSystemCommand
      // collapses to a concrete preset before commit); any unknown name falls
      // back to the dark preset here.
      return {
        bg: "#0e1320",
        accent,
        pane: "#141b2d",
        textDim: "#8a93a8",
      };
  }
}

/** Write a single `ThemeModel`'s CSS variables onto `:root`. */
function writeTheme(model: ThemeModel, doc: Document): void {
  const vars = varsFor(model);
  const root = doc.documentElement;
  root.style.setProperty("--bg", vars.bg);
  root.style.setProperty("--accent", vars.accent);
  root.style.setProperty("--pane", vars.pane);
  root.style.setProperty("--text-dim", vars.textDim);
  root.style.setProperty(
    "font-size",
    `${BASELINE_FONT_PX * model.fontScaleFactor}px`,
  );
}

/**
 * Non-hook entry point. Subscribes to `themeVM.currentTheme.valueChanged`
 * and applies each new model to `doc`. Applies the current model
 * synchronously before returning.
 *
 * Returns an `unsubscribe()` function for callers (and `useThemeAdapter`)
 * to tear down the subscription.
 */
export function applyTheme(themeVM: ThemeVM, doc: Document): () => void {
  // Apply the *current* model synchronously so the very first paint after
  // mount reflects the VM state. DerivedProperty.valueChanged only fires
  // on subsequent change emissions (spec ch. 15) — without this, the
  // document would stay on the boot-time CSS until the user toggled.
  try {
    writeTheme(themeVM.currentTheme.value, doc);
  } catch {
    // Pre-emission read — fall back to the VM's model directly.
    writeTheme(themeVM.model, doc);
  }

  const sub: Subscription = themeVM.currentTheme.valueChanged.subscribe({
    next: (model) => writeTheme(model, doc),
  });

  return (): void => sub.unsubscribe();
}

/**
 * React hook form. Calls `applyTheme(themeVM, document)` on mount and
 * tears it down on unmount. Re-subscribes when `themeVM` identity
 * changes (typically never — the workspace owns a single ThemeVM for
 * the app's lifetime).
 */
export function useThemeAdapter(themeVM: ThemeVM): void {
  useEffect(() => {
    const dispose = applyTheme(themeVM, document);
    return dispose;
  }, [themeVM]);
}
