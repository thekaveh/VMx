/**
 * Deterministic cross-language seed data.
 *
 * Mirrors the C# `SeedData` / Python `build_seed` content (same notebook ids,
 * note ids, and starred flags) so cross-language parity audits compare
 * identically.
 */
import type { NotebookModel } from "./notebookModel.js";
import type { NoteModel } from "./noteModel.js";

const NOW_MS = Date.UTC(2026, 4, 29, 12, 0, 0); // 2026-05-29T12:00:00Z

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

/**
 * Returns the canonical seed: 5 notebooks (1 nested), 12 notes, 3 starred.
 *
 * Returned arrays are frozen so callers cannot mutate the seed source.
 */
export function buildSeed(): {
  notebooks: readonly NotebookModel[];
  notes: readonly NoteModel[];
} {
  const notebooks: NotebookModel[] = [
    { id: "nb-work", name: "Work", parentId: null },
    { id: "nb-specs", name: "Specs", parentId: "nb-work" },
    { id: "nb-reviews", name: "Reviews", parentId: null },
    { id: "nb-personal", name: "Personal", parentId: null },
    { id: "nb-archive", name: "Archive", parentId: null },
  ];

  const notes: NoteModel[] = [];
  let idx = 0;

  function add(
    notebookId: string,
    title: string,
    opts: { starred?: boolean; tags?: readonly string[] } = {},
  ): void {
    idx += 1;
    notes.push({
      id: `note-${String(idx).padStart(2, "0")}`,
      notebookId,
      title,
      tags: Object.freeze([...(opts.tags ?? [])]),
      body: `(seed body for ${title})`,
      starred: opts.starred ?? false,
      createdAt: iso(NOW_MS - idx * DAY_MS),
      updatedAt: iso(NOW_MS - idx * HOUR_MS),
    });
  }

  add("nb-reviews", "Q1 design review");
  add("nb-reviews", "Auth migration plan", { starred: true, tags: ["security", "q2"] });
  add("nb-reviews", "Vendor shortlist");
  add("nb-reviews", "Onboarding draft");
  add("nb-reviews", "Privacy review notes");
  add("nb-reviews", "Disaster recovery plan");
  add("nb-reviews", "Cross-team review log", { starred: true });
  add("nb-work", "Standup notes");
  add("nb-work", "Roadmap snapshot");
  add("nb-specs", "MVx capability brief", { starred: true });
  add("nb-personal", "Reading list");
  add("nb-personal", "Travel ideas");

  return {
    notebooks: Object.freeze(notebooks),
    notes: Object.freeze(notes),
  };
}
