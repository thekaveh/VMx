# Theme as a VM concern — scenario contract

**Status:** Accepted (2026-06-02); shipped in spec v2.4.0 — items 1–3 in §8 implemented across all three flagship Notes-Showcase apps; item 4 (WorkspaceVM arity-7 composition) deferred per ADR-0036 §2.C / §4 decision #3.
**Authored under:** ADR-0036 §2.C (theming-as-a-VM-concern decision within the v2.4.0 umbrella).
**Related artefacts:** the three flagship Notes-Showcase apps under `examples/csharp/avalonia/NotesShowcase/`, `examples/python/textual/notes_showcase/`, `examples/typescript/react/notes-showcase/`.

## 1. Why this exists

A consistent finding from the v2.3.0 builder-pattern audit + the v2.4.0 example-app audit: **theming has lived in views, never in the VM layer**. Each flagship hard-codes its palette in framework-native resources:

| Flavor | Where theme lives today | LOC |
|---|---|---|
| Avalonia | `App.axaml` `RequestedThemeVariant="Dark"` + `Views/Theme/DarkTheme.axaml` ResourceDictionary | ~30 |
| Textual | `views/theme.tcss` (selector-based palette) | ~135 |
| React | `views/theme.css` (CSS custom properties) | ~343 |

The consequence: a consumer who wants to add a light/dark toggle, an accent-color picker, a font-scale ramp, or a high-contrast switch must either (a) call into framework-native APIs from views (breaking the pure-VM contract that all three apps otherwise enforce strictly) or (b) reach across the adapter into private framework state. **There is no testable seam.** You cannot today write a unit test like

> "When `themeVM.setThemeCommand.execute('light')` runs, then `themeVM.currentTheme.value.accentColor == '#1F6FEB'`."

against any of the three flagships, because there is no `ThemeVM`.

This scenario contract specifies the missing seam.

## 2. Scope

This is a **scenario contract** in the same style as `spec/proposals/2026-05-29-notes-showcase-scenario.md` (the Notes-Workspace contract). It documents a normative *shape* for example-app theming, NOT new types in the core library. The core library already has every primitive needed: `ComponentVM<M>`, `DerivedProperty<T>`, `RelayCommand`, `MessageHub`, dispatcher.

A flavor implements this contract by:

1. Defining a `ThemeModel` (or equivalent record type) per §3.
2. Defining a `ThemeVM : ComponentVM<ThemeModel>` per §4 with the prescribed surface.
3. Wiring a thin per-framework `IThemeAdapter` (Avalonia / Textual / React / SwiftUI) per §5 that translates VM state into framework-native theme application.
4. Composing `ThemeVM` into the app root (in the Notes-Showcase apps, this is `WorkspaceVM`).

## 3. Model

```
ThemeModel {
  name:               "dark" | "light" | "high-contrast" | "system"
  accentColor:        # color in the flavor's idiomatic Color representation (hex string is the lingua franca)
  fontScaleFactor:    Double  # 1.0 = baseline; clamp [0.75 .. 1.75]
  highContrast:       Bool
  followSystem:       Bool    # when true, name is the system-derived value; setThemeCommand transitions to followSystem=false
}
```

Three presets are predefined and named: `"dark"`, `"light"`, `"high-contrast"`. A fourth pseudo-preset `"system"` defers to the OS-level theme when the host supports it (Avalonia: `Application.Current.PlatformSettings.ColorValues`; Textual: `App.dark` reactive; React: `prefers-color-scheme` media query; SwiftUI: `colorScheme` environment).

## 4. VM surface

```
ThemeVM : ComponentVM<ThemeModel>

  # required-services from base:
  hub          : IMessageHub
  dispatcher   : IDispatcher

  # state:
  currentTheme : DerivedProperty<ThemeModel>      # mirrors .model; conformance: every consumer subscribes via this, not via .model directly
  presets      : ReadonlyList<ThemeModel>          # the known named presets
  followsSystem: DerivedProperty<bool>             # mirrors model.followSystem

  # commands:
  setThemeCommand     : RelayCommand<string>       # arg is preset name; raises on unknown
  toggleHighContrast  : RelayCommand               # flips model.highContrast; non-destructive over current accent + scale
  setAccentColor      : RelayCommand<string>       # accepts a hex string; raises on parse failure
  setFontScale        : RelayCommand<Double>       # clamps to [0.75..1.75]
  followSystemCommand : RelayCommand               # sets followSystem=true and re-reads the host's current theme

  # events (via hub):
  ThemeChangedMessage(prev: ThemeModel, curr: ThemeModel)  # published after every effective change
```

Every command MUST be `cancelable` (`CanExecute == false` while the dispatcher is mid-transition; this avoids the case where a user toggles theme 5 times in 50 ms during a SwiftUI animation and the adapter ends up in an intermediate state).

## 5. Per-flavor adapter

A `ThemeAdapter` subscribes to `themeVM.currentTheme.valueChanged` and applies the new model to the host framework:

- **Avalonia.** Hot-swap the active `ResourceDictionary` (one per preset, declared in `Views/Theme/{Dark,Light,HighContrast}.axaml`) on `Application.Current.Resources.MergedDictionaries`. Apply `RequestedThemeVariant` to the variant token (`Avalonia.Styling.ThemeVariant.Dark` etc.). Apply font scale via a singleton `FontSizeConverter` bound at app start.
- **Textual.** Maintain three `.tcss` stylesheets per preset; on theme change, swap the active stylesheet via `App.stylesheet`. Alternatively (preferred when feasible), rewrite the four CSS variables (`$bg`, `$accent`, `$panel`, `$text-muted`) by writing a small in-memory `.tcss` and applying it as a stylesheet.
- **React.** Update `document.documentElement.style.setProperty('--bg', value)` (etc.) for each token. The existing `views/theme.css` already exposes the four CSS custom properties — this just drives them from VM state instead of hard-coding.
- **SwiftUI.** Mirror `themeVM.currentTheme.value` into a `@StateObject ThemeStore` whose `@Published var current: ThemeModel` is read by `Color(...)` calls and `Font.system(size: 16 * fontScaleFactor)`.

Each adapter MUST be a single file under the flavor's `views/adapter/` directory. No business logic.

## 6. Conformance scenarios

Define five new conformance IDs under a new `THEME-NNN` family. Add to `spec/12-conformance.md` in PR #N.

- **THEME-001** — `setThemeCommand.execute("dark")` publishes `ThemeChangedMessage` exactly once; `currentTheme.value.name == "dark"`; `currentTheme.value.accentColor` equals the "dark" preset's accent.
- **THEME-002** — `setThemeCommand.execute("unknown-preset")` raises `BuilderValidationError` (or flavor-idiomatic exception) without publishing a message.
- **THEME-003** — `toggleHighContrast` toggles `currentTheme.value.highContrast` without changing accent or scale.
- **THEME-004** — `setFontScale(value)` clamps to `[0.75..1.75]` and publishes a single `ThemeChangedMessage`; values outside the range result in clamped emission, not rejection.
- **THEME-005** — `followSystemCommand.execute()` sets `followSystem=true` and re-reads the host's current theme; calling `setThemeCommand.execute("dark")` afterward sets `followSystem=false` automatically.

Each scenario MUST be tested in every flavor that implements the contract.

## 7. Out of scope

- Theme persistence across app restarts (a separate `IPreferencesService` port; flagships may opt in via a follow-up PR).
- Per-component theme overrides (e.g., "render this note in sepia mode regardless of app theme") — left to the host app.
- Animated theme transitions — explicitly NOT part of the contract; an animating adapter is allowed but not required.
- A theme picker UI — the flagships should ship a Settings menu in a later PR; this contract specifies the VM surface only.

## 8. Migration

The three flagship Notes-Showcase apps are updated in the same PR that lands this contract:

1. New `ViewModels/Theme/ThemeVM.{cs,py,ts}` per flavor.
2. New `Models/ThemeModel.{cs,py,ts}` per flavor.
3. New `Views/Adapter/ThemeAdapter.{cs,py,ts}` per flavor.
4. `WorkspaceVM` gains a new child `themeVM` once the `AggregateVM7`
   core-library extension lands — see ADR-0036 §2.C / §4 decision #3 for
   the deferral rationale.

**v2.4.0 cutoff (status as of 2026-06-02 ship):** items 1–3 are
implemented in all three flagships (C# Avalonia + Python Textual +
TypeScript React). Item 4 (the `WorkspaceVM` arity-7 composition) is
**deferred**. The host page subscribes to `ThemeVM.currentTheme` directly
in the meantime. The `AggregateVM7` library work, the WorkspaceVM
re-aggregation, and an end-to-end "settings drawer" UI for theme picking
are tracked under ADR-0036 §4 decision #3 and follow-up Swift work
under ADR-0036 §4 decision #6.

The existing hard-coded `Views/Theme/Dark.axaml` / `theme.tcss` /
`theme.css` files are kept as the *initial preset*; the theme system swaps
among them.
