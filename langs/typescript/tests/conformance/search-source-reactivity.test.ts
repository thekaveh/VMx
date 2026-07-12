import { Observable, Subject } from "rxjs";
import { describe, expect, it, vi } from "vitest";

import { SearchableState } from "../../src/index.js";

function matches(item: string, term: string): boolean {
  return term === "" || item.toLowerCase().includes(term.toLowerCase());
}

describe("SRCH-001", () => {
  it("refreshes an unchanged term from a source signal", () => {
    const items = ["one"];
    const sourceChanges = new Subject<void>();
    const state = new SearchableState<string>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
      sourceChanges,
    });
    const snapshots: (readonly string[])[] = [];
    state.filtered.subscribe((snapshot) => snapshots.push(snapshot));
    const before = snapshots.length;

    items.push("two");
    sourceChanges.next();

    expect(snapshots).toHaveLength(before + 1);
    expect(snapshots.at(-1)).toEqual(["one", "two"]);
  });
});

describe("SRCH-002", () => {
  it("reads each latest ordered source snapshot", () => {
    const items = ["a", "b", "c"];
    const sourceChanges = new Subject<void>();
    const state = new SearchableState<string>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
      sourceChanges,
    });
    const snapshots: (readonly string[])[] = [];
    state.filtered.subscribe((snapshot) => snapshots.push(snapshot));

    items.splice(1, 1);
    sourceChanges.next();
    expect(snapshots.at(-1)).toEqual(["a", "c"]);

    items[1] = "replacement";
    sourceChanges.next();
    expect(snapshots.at(-1)).toEqual(["a", "replacement"]);

    items.splice(0, items.length, "reset-1", "reset-2", "reset-3");
    sourceChanges.next();
    expect(snapshots.at(-1)).toEqual(["reset-1", "reset-2", "reset-3"]);

    items.reverse();
    sourceChanges.next();
    expect(snapshots.at(-1)).toEqual(["reset-3", "reset-2", "reset-1"]);
  });
});

describe("SRCH-003", () => {
  it("preserves equal pulses and upstream coalescing", () => {
    const items = ["same"];
    const sourceChanges = new Subject<void>();
    const state = new SearchableState<string>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
      sourceChanges,
    });
    const snapshots: (readonly string[])[] = [];
    state.filtered.subscribe((snapshot) => snapshots.push(snapshot));
    const before = snapshots.length;

    sourceChanges.next();
    sourceChanges.next();
    expect(snapshots).toHaveLength(before + 2);

    items.push("batched-1", "batched-2");
    sourceChanges.next();
    expect(snapshots).toHaveLength(before + 3);
    expect(snapshots.at(-1)).toEqual(["same", "batched-1", "batched-2"]);
  });
});

describe("SRCH-004", () => {
  it("does not reset a pending term debounce", () => {
    vi.useFakeTimers();
    try {
      const items = ["alpha", "beta"];
      const sourceChanges = new Subject<void>();
      const state = new SearchableState<string>({
        items: () => items,
        predicate: matches,
        debounceMs: 1_000,
        sourceChanges,
      });
      const snapshots: (readonly string[])[] = [];
      state.filtered.subscribe((snapshot) => snapshots.push(snapshot));

      state.searchTerm = "alp";
      items.push("alpine");
      const beforeSignal = snapshots.length;
      sourceChanges.next();

      expect(snapshots).toHaveLength(beforeSignal + 1);
      expect(snapshots.at(-1)).toEqual(["alpha", "alpine"]);

      vi.advanceTimersByTime(999);
      expect(snapshots).toHaveLength(beforeSignal + 1);
      vi.advanceTimersByTime(1);
      expect(snapshots).toHaveLength(beforeSignal + 2);
      expect(snapshots.at(-1)).toEqual(["alpha", "alpine"]);
      state.dispose();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("SRCH-005", () => {
  it("isolates source errors from manual search", () => {
    const items = ["one"];
    const sourceChanges = new Subject<void>();
    const state = new SearchableState<string>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
      sourceChanges,
    });
    const snapshots: (readonly string[])[] = [];
    const errors: unknown[] = [];
    let completed = false;
    state.filtered.subscribe({
      next: (snapshot) => snapshots.push(snapshot),
      error: (error: unknown) => errors.push(error),
      complete: () => {
        completed = true;
      },
    });

    sourceChanges.error(new Error("source failed"));
    items.push("two");
    state.search();

    expect(errors).toEqual([]);
    expect(completed).toBe(false);
    expect(snapshots.at(-1)).toEqual(["one", "two"]);
  });
});

describe("SRCH-006", () => {
  it("cancels its subscription once without owning the signal", () => {
    let subscribeCount = 0;
    let disposeCount = 0;
    let sourceSubscriber: { next(value?: unknown): void } | undefined;
    const sourceChanges = new Observable<unknown>((subscriber) => {
      subscribeCount += 1;
      sourceSubscriber = subscriber;
      return () => {
        disposeCount += 1;
      };
    });
    const items = ["one"];
    const state = new SearchableState<string>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
      sourceChanges,
    });
    const snapshots: (readonly string[])[] = [];
    state.filtered.subscribe((snapshot) => snapshots.push(snapshot));

    state.dispose();
    state.dispose();
    sourceSubscriber?.next();

    expect(subscribeCount).toBe(1);
    expect(disposeCount).toBe(1);
    expect(snapshots).toHaveLength(1);

    const independent = sourceChanges.subscribe();
    expect(subscribeCount).toBe(2);
    independent.unsubscribe();
  });
});

class OwnedItem {
  disposeCount = 0;

  constructor(readonly value: string) {}

  dispose(): void {
    this.disposeCount += 1;
  }
}

describe("SRCH-007", () => {
  it("preserves explicit refresh and item ownership without a signal", () => {
    const first = new OwnedItem("one");
    const second = new OwnedItem("two");
    const items = [first];
    const state = new SearchableState<OwnedItem>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
    });
    const snapshots: (readonly OwnedItem[])[] = [];
    state.filtered.subscribe((snapshot) => snapshots.push(snapshot));
    const beforeMutation = snapshots.length;

    items.push(second);
    expect(snapshots).toHaveLength(beforeMutation);

    state.search();
    expect(snapshots.at(-1)).toEqual([first, second]);
    state.dispose();

    expect(first.disposeCount).toBe(0);
    expect(second.disposeCount).toBe(0);
  });
});
