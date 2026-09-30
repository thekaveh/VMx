// @vitest-environment node
/**
 * Shared Notes scenario `notes-lifecycle-v1` (#346).
 *
 * Runs `examples/notes-showcase-scenario.json` through this showcase's view
 * models and compares every step's semantic snapshot with the shared
 * expectation. The C#, Python, and Swift showcases run the same file through
 * their own adapters.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MessageHub, type IAsyncCommand } from "@thekaveh/vmx";

import { ThemeChangedMessage } from "../src/messages/themeChanged.js";
import { InMemoryNoteRepository } from "../src/models/inMemoryRepository.js";
import { buildSeed } from "../src/models/seed.js";
import { NullDialogService } from "../src/viewmodels/dialogService.js";
import { WorkspaceVM } from "../src/viewmodels/workspaceVM.js";

const FLAVOR = "typescript";

interface Step {
  readonly action: string;
  readonly index?: number;
  readonly title?: string;
  readonly theme?: string;
  readonly expect: Record<string, unknown>;
}

interface Scenario {
  readonly id: string;
  readonly steps: readonly Step[];
}

const scenario = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../../../notes-showcase-scenario.json", import.meta.url)), "utf8"),
) as Scenario;

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

function differences(expected: Record<string, unknown>, actual: Record<string, unknown>): string[] {
  return Object.keys(expected)
    .filter((key) => JSON.stringify(actual[key]) !== JSON.stringify(expected[key]))
    .map((key) => `${key}: expected ${JSON.stringify(expected[key])}, got ${JSON.stringify(actual[key])}`);
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
