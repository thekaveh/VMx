import { describe, expect, it } from "vitest";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";

describe("InMemoryNoteRepository", () => {
  it("loadAll returns seed after the default delay", async () => {
    const repo = new InMemoryNoteRepository(buildSeed());
    const t = performance.now();
    const { notebooks, notes } = await repo.loadAll();
    const dt = performance.now() - t;
    // Assert the latency contract, not runner speed under contention.
    expect(dt).toBeGreaterThan(200);
    expect(notebooks.length).toBe(5);
    expect(notes.length).toBe(12);
  });

  it("loadNotes returns notes for the given notebook", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadNotesDelayMs: 0,
    });
    const reviews = await repo.loadNotes("nb-reviews");
    expect(reviews.length).toBe(7);
    expect(reviews.every((n) => n.notebookId === "nb-reviews")).toBe(true);
  });

  it("saveNote persists an update and is observable via loadNotes", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
    });
    const { notes } = await repo.loadAll();
    const [first] = notes;
    if (!first) throw new Error("expected a seeded note");
    await repo.saveNote({ ...first, title: "Updated" });
    const after = await repo.loadNotes(first.notebookId);
    expect(after.find((n) => n.id === first.id)?.title).toBe("Updated");
  });

  it("saveNote appends when the id is new", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
    });
    await repo.saveNote({
      id: "note-99",
      notebookId: "nb-work",
      title: "New",
      tags: [],
      body: "",
      starred: false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    const work = await repo.loadNotes("nb-work");
    expect(work.some((n) => n.id === "note-99")).toBe(true);
  });

  it("deleteNote removes the note", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadNotesDelayMs: 0,
      deleteNoteDelayMs: 0,
    });
    await repo.deleteNote("note-01");
    const reviews = await repo.loadNotes("nb-reviews");
    expect(reviews.some((n) => n.id === "note-01")).toBe(false);
  });

  it("deleteNote is a no-op for unknown ids", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      deleteNoteDelayMs: 0,
    });
    await repo.deleteNote("does-not-exist");
    const { notes } = await repo.loadAll();
    expect(notes.length).toBe(12);
  });

  it("addNotebook appends a notebook", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      addNotebookDelayMs: 0,
    });
    await repo.addNotebook({ id: "nb-new", name: "New", parentId: null });
    const { notebooks } = await repo.loadAll();
    expect(notebooks.some((n) => n.id === "nb-new")).toBe(true);
  });

  it("export invokes the supplied exporter with a JSON payload", async () => {
    let captured: { path: string; payload: string } | null = null;
    const repo = new InMemoryNoteRepository(
      buildSeed(),
      { exportDelayMs: 0, loadAllDelayMs: 0 },
      async (path, payload) => {
        captured = { path, payload };
      },
    );
    const { notebooks, notes } = await repo.loadAll();
    await repo.export(notebooks, notes, "/tmp/notes.json");
    expect(captured).not.toBeNull();
    expect(captured!.path).toBe("/tmp/notes.json");
    const parsed = JSON.parse(captured!.payload);
    expect(parsed.notebooks.length).toBe(5);
    expect(parsed.notes.length).toBe(12);
  });

  it("export with no exporter is a no-op (jsdom-safe)", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      exportDelayMs: 0,
      loadAllDelayMs: 0,
    });
    const { notebooks, notes } = await repo.loadAll();
    await expect(
      repo.export(notebooks, notes, "/tmp/x.json"),
    ).resolves.toBeUndefined();
  });

  it("concurrent saves serialize through the gate", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
    });
    const reviews = await repo.loadNotes("nb-reviews");
    const [a, b] = reviews;
    if (!a || !b) throw new Error("expected seeded reviews");
    await Promise.all([
      repo.saveNote({ ...a, title: "A" }),
      repo.saveNote({ ...b, title: "B" }),
    ]);
    const after = await repo.loadNotes("nb-reviews");
    expect(after.find((n) => n.id === a.id)?.title).toBe("A");
    expect(after.find((n) => n.id === b.id)?.title).toBe("B");
  });

  it("seed is deterministic — 3 starred notes across canonical ids", () => {
    const { notes } = buildSeed();
    const starred = notes.filter((n) => n.starred);
    expect(starred.map((n) => n.id).sort()).toEqual([
      "note-02",
      "note-07",
      "note-10",
    ]);
  });
});
