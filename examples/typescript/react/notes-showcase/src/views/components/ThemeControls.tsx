/**
 * ThemeControls — the theme control strip in the workspace toolbar.
 *
 * ADR-0201 §2.4: one button per preset runs `setThemeCommand`, "HC" runs
 * `toggleHighContrast`, and "A-" / "A+" run `setFontScale` with the current
 * factor minus or plus 0.1 (`ThemeVM` clamps it). There is no accent or
 * follow-system control. Mirrors the Swift `ThemeControlsView`.
 *
 * Pure-VM contract (§6.1): no React state. Each handler reads the current
 * theme from the VM when it runs.
 */
import type React from "react";

import type { ThemeVM } from "../../viewmodels/themeVM.js";

export interface ThemeControlsProps {
  readonly theme: ThemeVM;
}

const FONT_SCALE_STEP = 0.1;

export const ThemeControls: React.FC<ThemeControlsProps> = ({ theme }) => {
  const stepFontScale = (delta: number): void => {
    theme.setFontScale.execute(theme.currentTheme.value.fontScaleFactor + delta);
  };
  return (
    <div className="theme-controls" role="group" aria-label="Theme controls">
      {theme.presets.map((preset) => (
        <button
          key={preset.name}
          type="button"
          onClick={() => theme.setThemeCommand.execute(preset.name)}
        >
          {preset.name}
        </button>
      ))}
      <button
        type="button"
        aria-label="Toggle high contrast"
        onClick={() => theme.toggleHighContrast.execute()}
      >
        HC
      </button>
      <button
        type="button"
        aria-label="Decrease font size"
        onClick={() => stepFontScale(-FONT_SCALE_STEP)}
      >
        A-
      </button>
      <button
        type="button"
        aria-label="Increase font size"
        onClick={() => stepFontScale(FONT_SCALE_STEP)}
      >
        A+
      </button>
    </div>
  );
};
