/**
 * Shared showcase scenarios `notes-lifecycle-v1` and `theme-v1` (#346).
 *
 * Runs `examples/notes-showcase-scenario.json` and
 * `examples/notes-showcase-theme-scenario.json` through this showcase's view
 * models and compares every step's semantic snapshot with the shared
 * expectation. The C#, Python, and Swift showcases run the same files through
 * their own adapters.
 */
import { describe, expect, it } from "vitest";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  type IAsyncCommand,
} from "@thekaveh/vmx";

import { ThemeChangedMessage } from "../src/messages/themeChanged.js";
import { InMemoryNoteRepository } from "../src/models/inMemoryRepository.js";
import { buildSeed } from "../src/models/seed.js";
import { LIGHT_PRESET, PRESETS, type ThemeModel } from "../src/models/themeModel.js";
import { NullDialogService } from "../src/viewmodels/dialogService.js";
import { ThemeVM } from "../src/viewmodels/themeVM.js";
import { WorkspaceVM } from "../src/viewmodels/workspaceVM.js";
import rawScenario from "../../../../notes-showcase-scenario.json";
import rawThemeScenario from "../../../../notes-showcase-theme-scenario.json";

const FLAVOR = "typescript";

interface Step {
  readonly action: string;
  readonly index?: number;
  readonly title?: string;
  readonly theme?: string;
  readonly accent?: string;
  readonly scale?: number;
  readonly expect: Record<string, unknown>;
}

interface Scenario {
  readonly id: string;
  readonly steps: readonly Step[];
}

const scenario = rawScenario as unknown as Scenario;
const themeScenario = rawThemeScenario as unknown as Scenario;

class Adapter {
  readonly hub = new MessageHub();
  readonly ws: WorkspaceVM;
  #events: string[] = [];
  #savedCompleted = false;

  constructor() {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
      addNotebookDelayMs: 0,
    });
    this.ws = WorkspaceVM.builder()
      .repository(repo)
      .dialogService(NullDialogService.INSTANCE)
      .messageHub(this.hub)
      .build();
    this.hub.messages.subscribe((message) => {
      if (message instanceof ThemeChangedMessage) {
        this.#events.push(`theme:${message.prev.name}->${message.curr.name}`);
      }
    });
    this.ws.noteForm.onSaved.subscribe({
      next: (model) => this.#events.push(`saved:${model.title}`),
      complete: () => { this.#savedCompleted = true; },
    });
  }

  async run(step: Step): Promise<string | null> {
    try {
      switch (step.action) {
        case "construct":
          await this.ws.constructAsync();
          break;
        case "create_note":
          await (this.ws.newNoteCommand as IAsyncCommand).executeAsync();
          break;
        case "select_note":
          this.ws.notesView.current = this.ws.notesView.inner[step.index!]!;
          break;
        case "edit_title":
          this.ws.noteForm.draft = { ...this.ws.noteForm.draft, title: step.title! };
          break;
        case "save":
          await this.ws.noteForm.approveAsync();
          break;
        case "delete_selected_declined": {
          // The default dialog service declines every confirmation.
          const current = this.ws.notesView.current;
          if (current === null) throw new Error("no selected note");
          await (current.deleteCommand as IAsyncCommand).executeAsync();
          break;
        }
        case "set_theme":
          this.ws.theme.setThemeCommand.execute(step.theme!);
          break;
        case "dispose":
          this.ws.dispose();
          break;
        default:
          throw new Error(`unknown scenario action ${step.action}`);
      }
    } catch (error) {
      if (step.action === "set_theme") return "invalid";
      throw error;
    }
    return null;
  }

  snapshot(error: string | null): Record<string, unknown> {
    if (this.#savedCompleted) return { events: this.#drain(), error, disposed: true };
    const view = this.ws.notesView;
    const form = this.ws.noteForm;
    return {
      notebook: view.boundNotebookId,
      notes: view.inner.map((note) => note.model.title),
      selected: view.current?.model.title ?? null,
      form: form.hasBoundNote
        ? { title: form.draft.title, dirty: form.isDirty, valid: form.isValid }
        : null,
      theme: this.ws.theme.currentTheme.value.name,
      events: this.#drain(),
      error,
      disposed: false,
    };
  }

  #drain(): string[] {
    const events = this.#events;
    this.#events = [];
    return events;
  }
}

function themeSnapshot(model: ThemeModel): Record<string, unknown> {
  const preset = PRESETS[model.name];
  return {
    name: model.name,
    high_contrast: model.highContrast,
    accent: preset !== undefined && model.accentColor === preset.accentColor ? "preset" : model.accentColor,
    font_scale: model.fontScaleFactor,
    follows_system: model.followsSystem,
  };
}

class ThemeAdapter {
  readonly hub = new MessageHub();
  readonly vm = new ThemeVM({
    name: "theme",
    hint: "",
    hub: this.hub,
    dispatcher: RxDispatcher.immediate(),
    initialModel: LIGHT_PRESET,
    systemResolver: () => "light",
  });
  #events: Record<string, unknown>[] = [];

  constructor() {
    this.hub.messages.subscribe((message) => {
      if (message instanceof ThemeChangedMessage) {
        this.#events.push({ previous: themeSnapshot(message.prev), current: themeSnapshot(message.curr) });
      }
    });
  }

  run(step: Step): string | null {
    try {
      switch (step.action) {
        case "construct":
          this.vm.construct();
          break;
        case "set_theme":
          this.vm.setThemeCommand.execute(step.theme!);
          break;
        case "set_accent":
          this.vm.setAccentColor.execute(step.accent!);
          break;
        case "toggle_high_contrast":
          this.vm.toggleHighContrast.execute();
          break;
        case "set_font_scale":
          this.vm.setFontScale.execute(step.scale!);
          break;
        case "follow_system":
          this.vm.followSystemCommand.execute();
          break;
        case "dispose":
          this.vm.dispose();
          break;
        default:
          throw new Error(`unknown scenario action ${step.action}`);
      }
    } catch (error) {
      if (step.action === "set_theme") return "invalid";
      throw error;
    }
    return null;
  }

  snapshot(error: string | null): Record<string, unknown> {
    const events = this.#events;
    this.#events = [];
    if (this.vm.status === ConstructionStatus.Disposed) return { events, error, disposed: true };
    return { theme: themeSnapshot(this.vm.currentTheme.value), events, error, disposed: false };
  }
}

/** JSON text with object keys sorted, so key order never decides equality. */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item !== null && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
      : item,
  );
}

function differences(expected: Record<string, unknown>, actual: Record<string, unknown>): string[] {
  return Object.keys(expected)
    .filter((key) => canonical(actual[key]) !== canonical(expected[key]))
    .map((key) => `${key}: expected ${canonical(expected[key])}, got ${canonical(actual[key])}`);
}

describe("shared notes scenario", () => {
  it(`${scenario.id} matches the semantic expectation`, async () => {
    const adapter = new Adapter();
    const failures: string[] = [];
    for (const [offset, step] of scenario.steps.entries()) {
      const actual = adapter.snapshot(await adapter.run(step));
      for (const difference of differences(step.expect, actual)) {
        failures.push(`${scenario.id} [${FLAVOR}] step ${offset + 1} ${step.action}: ${difference}`);
      }
    }
    expect(failures.join("\n")).toBe("");
  });
});

describe("shared theme scenario", () => {
  it(`${themeScenario.id} matches the semantic expectation`, () => {
    const adapter = new ThemeAdapter();
    const failures: string[] = [];
    for (const [offset, step] of themeScenario.steps.entries()) {
      const actual = adapter.snapshot(adapter.run(step));
      for (const difference of differences(step.expect, actual)) {
        failures.push(`${themeScenario.id} [${FLAVOR}] step ${offset + 1} ${step.action}: ${difference}`);
      }
    }
    expect(failures.join("\n")).toBe("");
  });
});
