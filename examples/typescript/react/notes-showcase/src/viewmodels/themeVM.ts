/**
 * ThemeVM — modeled VM that owns the application theme.
 *
 * Conforms to `spec/proposals/2026-06-02-theme-vm-scenario.md` §4 ("VM surface").
 *
 * Wire-up (VMX-129): `WorkspaceVM` owns a `ThemeVM` as a sibling of the six
 * aggregate children (not a 7th aggregate child — that would require an
 * `AggregateVM7` in core, which ADR-0058 declined). The workspace drives its
 * lifecycle (construct/destruct/dispose) and `App.tsx` binds the React
 * `useThemeAdapter` hook to `workspace.theme`, so the THEME-001..005 scenario
 * is exercised in the running app.
 *
 * Design notes:
 *
 * - The VM extends `ComponentVMOf<ThemeModel>`. We do NOT use the
 *   inherited public `model =` setter for theme transitions, because
 *   ComponentVMOf's `_setModel` emits a `PropertyChangedMessage` (which
 *   is the right side-effect for "model"), but THEME-001/THEME-004
 *   require a dedicated `ThemeChangedMessage(prev, curr)` to be
 *   published in addition. We override `_setModel` to publish the
 *   theme message AFTER the inherited model-changed bookkeeping.
 *
 * - DerivedProperties (`currentTheme`, `followsSystem`) are sourced
 *   from a `BehaviorSubject<ThemeModel>` that we tick on every effective
 *   change. They give consumers a stable, equality-guarded view of
 *   the model (per ADR-0011 §DerivedProperty equality).
 *
 * - Commands follow the ADR-0006 camelCase idiom. Validation lives at
 *   command execution: unknown preset names throw `Error("unknown preset")`
 *   per task contract. `setFontScale` clamps to [0.75, 1.75] silently
 *   (THEME-004 specifies clamp-and-emit, not reject).
 *
 * - The presets list is a snapshot of the three named presets at
 *   construction time. The fourth pseudo-preset `"system"` is NOT a
 *   ThemeModel value — it's a transient state requested via
 *   `followSystemCommand`; the resulting model adopts the host's
 *   currently-resolved theme (defaulting to `DARK_PRESET` when the
 *   host has no `prefers-color-scheme` signal).
 */
import { BehaviorSubject, map } from "rxjs";
import {
  ComponentVMOf,
  DerivedProperty,
  RelayCommand,
  RelayCommandOf,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";

import {
  clampFontScale,
  DARK_PRESET,
  HIGH_CONTRAST_PRESET,
  LIGHT_PRESET,
  PRESETS,
  type ThemeModel,
} from "../models/themeModel.js";
import { ThemeChangedMessage } from "../messages/themeChanged.js";

/** Host-supplied probe returning the OS-level preferred theme name. */
export type SystemThemeResolver = () => "dark" | "light";

/**
 * Default system-theme resolver that consults `window.matchMedia`.
 * Falls back to `"dark"` when the media-query API is unavailable
 * (Node / jsdom in default config). Pure function — no listeners
 * are attached; the VM re-probes on each `followSystemCommand`.
 */
const defaultSystemResolver: SystemThemeResolver = () => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "dark";
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
};

export class ThemeVM extends ComponentVMOf<ThemeModel> {
  readonly #subject: BehaviorSubject<ThemeModel>;
  readonly #currentTheme: DerivedProperty<ThemeModel>;
  readonly #followsSystem: DerivedProperty<boolean>;
  readonly #presets: readonly ThemeModel[];
  readonly #systemResolver: SystemThemeResolver;

  readonly #setThemeCommand: RelayCommandOf<string>;
  readonly #toggleHighContrast: RelayCommand;
  readonly #setAccentColor: RelayCommandOf<string>;
  readonly #setFontScale: RelayCommandOf<number>;
  readonly #followSystemCommand: RelayCommand;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    initialModel?: ThemeModel;
    systemResolver?: SystemThemeResolver;
  }) {
    const initial = opts.initialModel ?? DARK_PRESET;
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
      initialModel: initial,
      modeledHinter: (m): string => m.name,
    });

    this.#systemResolver = opts.systemResolver ?? defaultSystemResolver;
    this.#presets = Object.freeze([
      DARK_PRESET,
      LIGHT_PRESET,
      HIGH_CONTRAST_PRESET,
    ]);

    this.#subject = new BehaviorSubject<ThemeModel>(initial);
    this.#currentTheme = new DerivedProperty<ThemeModel>(
      this.#subject.asObservable(),
      null,
      null,
    );
    this.#followsSystem = new DerivedProperty<boolean>(
      this.#subject.asObservable().pipe(map((m) => m.followsSystem)),
      null,
      null,
    );

    this.#setThemeCommand = RelayCommandOf.builder<string>()
      .task((presetName) => this.#applyPreset(presetName))
      .build();

    this.#toggleHighContrast = RelayCommand.builder()
      .task(() => this.#applyToggleHighContrast())
      .build();

    this.#setAccentColor = RelayCommandOf.builder<string>()
      .task((hex) => this.#applyAccentColor(hex))
      .build();

    this.#setFontScale = RelayCommandOf.builder<number>()
      .task((factor) => this.#applyFontScale(factor))
      .build();

    this.#followSystemCommand = RelayCommand.builder()
      .task(() => this.#applyFollowSystem())
      .build();
  }

  // ── Public surface (proposal §4) ─────────────────────────────────────────

  get currentTheme(): DerivedProperty<ThemeModel> {
    return this.#currentTheme;
  }

  get presets(): readonly ThemeModel[] {
    return this.#presets;
  }

  get followsSystem(): DerivedProperty<boolean> {
    return this.#followsSystem;
  }

  get setThemeCommand(): RelayCommandOf<string> {
    return this.#setThemeCommand;
  }

  get toggleHighContrast(): RelayCommand {
    return this.#toggleHighContrast;
  }

  get setAccentColor(): RelayCommandOf<string> {
    return this.#setAccentColor;
  }

  get setFontScale(): RelayCommandOf<number> {
    return this.#setFontScale;
  }

  get followSystemCommand(): RelayCommand {
    return this.#followSystemCommand;
  }

  // ── Effective transitions ────────────────────────────────────────────────

  /** Replaces `this.model` and publishes `ThemeChangedMessage(prev, curr)`. */
  #commit(next: ThemeModel): void {
    const prev = this.model;
    if (prev === next) return;
    // _setModel (inherited from ComponentVMOf) emits the "model"
    // PropertyChangedMessage and updates the modeledHint. Our override
    // (below) additionally publishes ThemeChangedMessage and ticks the
    // BehaviorSubject driving DerivedProperty subscribers.
    this.model = next;
  }

  /**
   * Override of ComponentVMOf's protected setter so a model change goes
   * through a single funnel — whether triggered by a command or by an
   * external `themeVM.model = ...` write. This is the only place that
   * publishes ThemeChangedMessage and ticks the subject.
   */
  protected override _setModel(value: ThemeModel): void {
    const prev = this.model;
    if (prev === value) return;
    super._setModel(value);
    // After super: model is now `value`. Notify derived-prop subscribers
    // and publish the theme-changed message for hub listeners.
    this.#subject.next(value);
    this._hub.send(ThemeChangedMessage.create(this, this._name, prev, value));
  }

  #applyPreset(presetName: string): void {
    const preset = PRESETS[presetName];
    if (preset === undefined) {
      throw new Error("unknown preset");
    }
    // Preserve user-customized accent and scale when crossing a preset
    // boundary? The proposal §3 says only follow-system flips; the
    // conformance scenarios THEME-001 ("setThemeCommand publishes ...
    // accentColor equals the 'dark' preset's accent") imply preset
    // swap RESETS accent + scale to the preset's defaults. Match that.
    const next: ThemeModel = {
      name: preset.name,
      accentColor: preset.accentColor,
      fontScaleFactor: preset.fontScaleFactor,
      highContrast: preset.highContrast,
      // Per THEME-005: a subsequent `setThemeCommand` after `followSystem`
      // must reset `followsSystem` back to false automatically.
      followsSystem: false,
    };
    this.#commit(next);
  }

  #applyToggleHighContrast(): void {
    const prev = this.model;
    const next: ThemeModel = {
      name: prev.name,
      accentColor: prev.accentColor,
      fontScaleFactor: prev.fontScaleFactor,
      highContrast: !prev.highContrast,
      followsSystem: prev.followsSystem,
    };
    this.#commit(next);
  }

  #applyAccentColor(hex: string): void {
    // Minimal validation: must be a #RRGGBB or #RGB hex literal.
    // Per proposal §4 ("raises on parse failure"), reject otherwise.
    if (!/^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(hex)) {
      throw new Error("invalid accent color");
    }
    const prev = this.model;
    if (prev.accentColor === hex) return;
    const next: ThemeModel = {
      name: prev.name,
      accentColor: hex,
      fontScaleFactor: prev.fontScaleFactor,
      highContrast: prev.highContrast,
      followsSystem: prev.followsSystem,
    };
    this.#commit(next);
  }

  #applyFontScale(factor: number): void {
    const clamped = clampFontScale(factor);
    const prev = this.model;
    if (prev.fontScaleFactor === clamped) return;
    const next: ThemeModel = {
      name: prev.name,
      accentColor: prev.accentColor,
      fontScaleFactor: clamped,
      highContrast: prev.highContrast,
      followsSystem: prev.followsSystem,
    };
    this.#commit(next);
  }

  #applyFollowSystem(): void {
    const resolved = this.#systemResolver();
    const base = PRESETS[resolved] ?? DARK_PRESET;
    const next: ThemeModel = {
      name: base.name,
      accentColor: base.accentColor,
      fontScaleFactor: base.fontScaleFactor,
      highContrast: base.highContrast,
      followsSystem: true,
    };
    this.#commit(next);
  }

  protected override _onDispose(): void {
    this.#currentTheme.dispose();
    this.#followsSystem.dispose();
    this.#subject.complete();
    this.#setThemeCommand.dispose();
    this.#toggleHighContrast.dispose();
    this.#setAccentColor.dispose();
    this.#setFontScale.dispose();
    this.#followSystemCommand.dispose();
    super._onDispose();
  }
}
