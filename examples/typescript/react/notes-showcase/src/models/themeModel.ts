/**
 * ThemeModel — pure-data record for the app theme.
 *
 * Conforms to `spec/proposals/2026-06-02-theme-vm-scenario.md` §3.
 *
 * Immutable. Three named presets (`DARK_PRESET`, `LIGHT_PRESET`,
 * `HIGH_CONTRAST_PRESET`) are frozen at module load and exposed via
 * the `PRESETS` registry. The fourth pseudo-preset `"system"` is not
 * materialized here — it's a transient state owned by the VM (see
 * `themeVM.followSystemCommand`).
 *
 * The dark preset mirrors the existing palette declared in
 * `views/theme.css` so that the initial CSS is byte-for-byte
 * equivalent to `DARK_PRESET` applied via the theme adapter — i.e.
 * the document boots already on the dark theme without any adapter
 * pass having to run.
 */

export type ThemeName = "dark" | "light" | "high-contrast" | "system";

export interface ThemeModel {
  readonly name: ThemeName;
  readonly accentColor: string;
  readonly fontScaleFactor: number;
  readonly highContrast: boolean;
  readonly followsSystem: boolean;
}

/** Inclusive clamp range for `fontScaleFactor` per proposal §3. */
export const FONT_SCALE_MIN = 0.75;
export const FONT_SCALE_MAX = 1.75;

/** Clamps the given factor into the spec-defined range. */
export function clampFontScale(factor: number): number {
  if (Number.isNaN(factor)) return 1.0;
  if (factor < FONT_SCALE_MIN) return FONT_SCALE_MIN;
  if (factor > FONT_SCALE_MAX) return FONT_SCALE_MAX;
  return factor;
}

/**
 * Dark preset — mirrors `views/theme.css` `:root` palette.
 * `--bg`, `--pane`, `--text-dim`, `--accent` are the four "key" CSS
 * variables driven by the theme adapter (proposal §5 React row).
 */
export const DARK_PRESET: ThemeModel = Object.freeze({
  name: "dark",
  accentColor: "#4f8cd9",
  fontScaleFactor: 1.0,
  highContrast: false,
  followsSystem: false,
});

/**
 * Light preset — flips `--bg` to a light surface and `--text-dim` to
 * a muted dark grey; the accent is preserved across light/dark so
 * brand identity is stable, per proposal §3 ("accent stays the same").
 */
export const LIGHT_PRESET: ThemeModel = Object.freeze({
  name: "light",
  accentColor: "#4f8cd9",
  fontScaleFactor: 1.0,
  highContrast: false,
  followsSystem: false,
});

/**
 * High-contrast preset — pure black/white with a bright accent.
 * `highContrast` flag is true so adapters can apply WCAG-bumped
 * focus rings, thicker borders, etc.
 */
export const HIGH_CONTRAST_PRESET: ThemeModel = Object.freeze({
  name: "high-contrast",
  accentColor: "#ffd400",
  fontScaleFactor: 1.0,
  highContrast: true,
  followsSystem: false,
});

/**
 * Registry of named presets, keyed by `ThemeModel.name`. Frozen.
 * The VM consults this map to resolve `setThemeCommand` payloads.
 */
export const PRESETS: Readonly<Record<string, ThemeModel>> = Object.freeze({
  dark: DARK_PRESET,
  light: LIGHT_PRESET,
  "high-contrast": HIGH_CONTRAST_PRESET,
});
