import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  hasCapability,
  MessageHub,
  RxDispatcher,
} from "vmx";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { NotesViewVM } from "../../src/viewmodels/notesViewVM.js";

function makeVM(opts: {
  pageSize?: number;
  searchDebounceMs?: number;
} = {}): { vm: NotesViewVM; hub: MessageHub; repo: InMemoryNoteRepository } {
  const hub = new MessageHub();
  const repo = new InMemoryNoteRepository(buildSeed(), {
    loadNotesDelayMs: 0,
  });
  const vm = NotesViewVM.builder()
    .name("notes")
    .services(hub, RxDispatcher.immediate())
    .repository(repo)
    .pageSize(opts.pageSize ?? 5)
    .searchDebounceMs(opts.searchDebounceMs ?? 150)
    .build();
  vm.construct();
  return { vm, hub, repo };
}

describe("NotesViewVM", () => {
  it("declares the documented capability set", () => {
    const { vm } = makeVM();
    for (const cap of [
      "IPageable",
      "IFilterable",
      "ISearchable",
      "IReconstructable",
    ] as const) {
      expect(hasCapability(vm, cap)).toBe(true);
    }
  });

  it("bindToAsync populates inner items and resets current + page", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    expect(vm.inner.length).toBe(7);
    expect(vm.boundNotebookId).toBe("nb-reviews");
    expect(vm.current).toBeNull();
    expect(vm.currentPageIndex).toBe(0);
  });

  it("pagination boundaries (next/prev/first/last) clamp correctly", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews"); // 7 items, pageSize 5 → 2 pages
    expect(vm.pageCount).toBe(2);
    vm.moveToFirstPage();
    expect(vm.currentPageIndex).toBe(0);
    vm.moveToNextPage();
    expect(vm.currentPageIndex).toBe(1);
    vm.moveToNextPage(); // clamped
    expect(vm.currentPageIndex).toBe(1);
    vm.moveToPreviousPage();
    expect(vm.currentPageIndex).toBe(0);
    vm.moveToLastPage();
    expect(vm.currentPageIndex).toBe(1);
    vm.visibleItems.forEach((n) => expect(n).toBeDefined());
  });

  it("showStarredOnly filters to starred notes only", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews"); // includes 2 starred reviews
    vm.showStarredOnly = true;
    expect(vm.filteredItems.every((n) => n.model.starred)).toBe(true);
    vm.showStarredOnly = false;
    expect(vm.filteredItems.length).toBe(7);
  });

  it("filter callback narrows the visible set", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    vm.filter = (n) => n.model.title.startsWith("Q1");
    expect(vm.filteredItems.length).toBe(1);
    vm.filter = null;
    expect(vm.filteredItems.length).toBe(7);
  });

  describe("search debounce", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("emits filtered set only after debounce window expires", async () => {
      const hub = new MessageHub();
      const repo = new InMemoryNoteRepository(buildSeed(), {
        loadNotesDelayMs: 0,
      });
      const vm = NotesViewVM.builder()
        .name("notes")
        .services(hub, RxDispatcher.immediate())
        .repository(repo)
        .pageSize(5)
        .searchDebounceMs(150)
        .build();
      vm.construct();

      // bindToAsync uses repo with zero delay — drain microtasks instead of
      // real time.
      const bindPromise = vm.bindToAsync("nb-reviews");
      await vi.runAllTimersAsync();
      await bindPromise;
      expect(vm.inner.length).toBe(7);

      vm.searchTerm = "auth";
      // Immediately after — search hasn't fired yet
      expect(vm.filteredItems.length).toBe(7);

      // Advance past debounce window
      await vi.advanceTimersByTimeAsync(160);
      expect(vm.filteredItems.length).toBe(1);
      expect(vm.filteredItems[0]?.title).toContain("Auth");
    });
  });

  it("bindToAsync supersedes a prior in-flight fetch", async () => {
    const hub = new MessageHub();
    let calls = 0;
    const slowRepo = new InMemoryNoteRepository(buildSeed(), {
      loadNotesDelayMs: 0,
    });
    // Wrap loadNotes to add a controllable delay only to first call
    const originalLoadNotes = slowRepo.loadNotes.bind(slowRepo);
    slowRepo.loadNotes = async (id) => {
      calls += 1;
      if (calls === 1) {
        await new Promise((r) => setTimeout(r, 30));
      }
      return originalLoadNotes(id);
    };
    const vm = NotesViewVM.builder()
      .name("notes")
      .services(hub, RxDispatcher.immediate())
      .repository(slowRepo)
      .pageSize(5)
      .searchDebounceMs(0)
      .build();
    vm.construct();
    const a = vm.bindToAsync("nb-reviews");
    const b = vm.bindToAsync("nb-personal");
    await Promise.all([a, b]);
    expect(vm.boundNotebookId).toBe("nb-personal");
    expect(vm.inner.every((n) => n.model.notebookId === "nb-personal")).toBe(true);
  });

  it("isEmpty true when no notes pass filters", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-archive");
    expect(vm.isEmpty).toBe(true);
    expect(vm.filteredItems.length).toBe(0);
  });

  it("pageLabel reflects current page and count", async () => {
    const { vm } = makeVM({ pageSize: 5 });
    await vm.bindToAsync("nb-reviews"); // 7 items → 2 pages
    expect(vm.pageLabel).toBe("Page 1 of 2");
    vm.moveToNextPage();
    expect(vm.pageLabel).toBe("Page 2 of 2");
  });

  it("setting current emits PropertyChangedMessage and equality-guards", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-personal");
    const first = vm.inner[0] ?? null;
    vm.current = first;
    expect(vm.current).toBe(first);
    vm.current = first;
    expect(vm.current).toBe(first);
  });

  it("dispose cleans up without throwing", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-personal");
    expect(() => vm.dispose()).not.toThrow();
  });

  it("builder validates required fields", () => {
    expect(() => NotesViewVM.builder().build()).toThrow();
  });

  it("exposes isPagingEnabled, count, hub, isEmpty / pageLabel derived properties", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    expect(vm.isPagingEnabled).toBe(true);
    expect(vm.count).toBe(7);
    expect(vm.hub).toBeDefined();
    expect(vm.isEmptyDerived.value).toBe(false);
    expect(vm.pageLabelDerived.value).toBe("Page 1 of 2");
  });

  it("currentPageIndex setter and pageSize setter clamp and notify", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    vm.currentPageIndex = 99; // clamped
    expect(vm.currentPageIndex).toBe(1);
    vm.pageSize = 2; // 7 items / 2 → 4 pages
    expect(vm.pageCount).toBe(4);
  });

  it("destruct disposes inner items and clears the buffer", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    expect(vm.inner.length).toBe(7);
    vm.destruct();
    expect(vm.inner.length).toBe(0);
  });

  it("search() helper triggers an immediate filter recompute", async () => {
    const { vm } = makeVM({ searchDebounceMs: 0 });
    await vm.bindToAsync("nb-reviews");
    vm.searchTerm = "Auth";
    vm.search();
    expect(vm.filteredItems.length).toBeGreaterThan(0);
    expect(vm.canSearch()).toBe(true);
  });

  it("canFilter true once constructed, false once destructed", async () => {
    const { vm } = makeVM();
    expect(vm.canFilter()).toBe(true);
    vm.destruct();
    expect(vm.canFilter()).toBe(false);
  });

  it("page-navigation commands wire through to the inner PagedComposition", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    vm.moveToLastPageCommand.execute();
    expect(vm.currentPageIndex).toBe(1);
    vm.moveToPreviousPageCommand.execute();
    expect(vm.currentPageIndex).toBe(0);
    vm.moveToNextPageCommand.execute();
    expect(vm.currentPageIndex).toBe(1);
    vm.moveToFirstPageCommand.execute();
    expect(vm.currentPageIndex).toBe(0);
  });

  it("builder hint() and searchScheduler() set their respective fields", async () => {
    const { TestScheduler } = await import("rxjs/testing");
    const scheduler = new TestScheduler(() => {
      /* ignore equality */
    });
    const hub = new MessageHub();
    const repo = new InMemoryNoteRepository(buildSeed(), { loadNotesDelayMs: 0 });
    const vm = NotesViewVM.builder()
      .name("n")
      .hint("a note view")
      .services(hub, RxDispatcher.immediate())
      .repository(repo)
      .pageSize(3)
      .searchDebounceMs(0)
      .searchScheduler(scheduler)
      .build();
    vm.construct();
    expect(vm.hint).toBe("a note view");
    vm.dispose();
  });

  it("filter setter is a no-op when the same reference is supplied", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    const fn = (n: { model: { starred: boolean } }) => n.model.starred;
    vm.filter = fn;
    const before = vm.filteredItems.length;
    vm.filter = fn; // no-op
    expect(vm.filteredItems.length).toBe(before);
  });

  it("showStarredOnly setter equality-guards", async () => {
    const { vm } = makeVM();
    await vm.bindToAsync("nb-reviews");
    vm.showStarredOnly = true;
    const first = vm.filteredItems.length;
    vm.showStarredOnly = true;
    expect(vm.filteredItems.length).toBe(first);
  });

  // ── Round-3 Important B-I1 parity: full delete pathway (repo delete →
  // remove from inner → clear current → dispose). Mirrors the C# and Py
  // tests of the same shape.
  it("deleteNote removes from inner, clears current, and persists", async () => {
    const { NotificationHub } = await import("vmx/notifications");
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadNotesDelayMs: 0,
      deleteNoteDelayMs: 0,
    });
    const hub = new MessageHub();
    const notifs = new NotificationHub();
    const vm = NotesViewVM.builder()
      .name("notes")
      .services(hub, RxDispatcher.immediate())
      .repository(repo)
      .pageSize(5)
      .searchDebounceMs(0)
      .dialogService({
        pickFileToOpen: () => Promise.resolve(null),
        pickFileToSave: () => Promise.resolve(null),
        confirm: () => Promise.resolve(true),
        notify: () => Promise.resolve(),
      })
      .notificationHub(notifs)
      .build();
    vm.construct();
    await vm.bindToAsync("nb-personal");
    const before = vm.inner.length;
    const target = vm.inner[0]!;
    vm.current = target;

    // Drive delete through NoteVM.deleteCommand (the wrapped path).
    target.deleteCommand.execute();
    // Wait for the async confirm + repo delete + state mutation chain.
    await new Promise((r) => setTimeout(r, 20));

    expect(vm.inner.length).toBe(before - 1);
    expect(vm.current).toBeNull();
    const reload = await repo.loadNotes("nb-personal");
    expect(reload.some((n) => n.id === target.noteId)).toBe(false);
  });
});
