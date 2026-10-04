// Conformance tests: COL-065 — a token-paged refresh keeps Items and
// CurrentToken describing one loaded prefix (spec 21 §6.2, ADR-0136).

import { describe, expect, it } from "vitest";
import { ComponentVM, ConstructionStatus, TokenPagedComposition } from "../../src/index.js";

type Page<T> = { items: T[]; nextToken: string | null };

/** A backend whose first page can change between calls; later pages are keyed by token. */
function backend(pages: Record<string, Page<number>>) {
  const requested: Array<string | null> = [];
  let firstPage: Page<number> = pages.first!;
  const fetch = (token: string | null): Promise<Page<number>> => {
    requested.push(token);
    return Promise.resolve(token === null ? firstPage : pages[token]!);
  };
  return {
    requested,
    fetch,
    setFirstPage(page: Page<number>) {
      firstPage = page;
    },
  };
}

const PAGES: Record<string, Page<number>> = {
  first: { items: [1, 2], nextToken: "t2" },
  t2: { items: [3, 4], nextToken: "t3" },
  t3: { items: [5, 6], nextToken: "t4" },
  t4: { items: [7], nextToken: null },
};

function recordTrace(sut: TokenPagedComposition<number, string>): string[] {
  const trace: string[] = [];
  sut.collectionChanged.subscribe((event) => trace.push(`collection:${event.action}`));
  sut.propertyChanged.subscribe((name) => trace.push(`property:${name}`));
  sut.loadMoreCommand.canExecuteChanged.subscribe(() => trace.push("loadMore:canExecuteChanged"));
  return trace;
}

async function loadPages(sut: TokenPagedComposition<number, string>, count: number) {
  for (let i = 0; i < count; i += 1) await sut.loadMoreCommand.executeAsync();
}

describe("COL-065", () => {
  it("an unchanged-head refresh keeps the loaded prefix's cursor, so load-more never refetches page two", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 3);

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2, 3, 4, 5, 6]);
    expect(sut.currentToken).toBe("t4");
    expect(sut.hasMore).toBe(true);

    await sut.loadMoreCommand.executeAsync();

    expect(sut.items).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(api.requested).toEqual([null, "t2", "t3", null, "t4"]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
  });

  it("a shorter non-terminal head that matches keeps the accumulator and cursor", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 2);
    api.setFirstPage({ items: [1], nextToken: "u1" });

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2, 3, 4]);
    expect(sut.currentToken).toBe("t3");
  });

  it("an unchanged single loaded page adopts a changed opaque token without mutating items", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 1);
    api.setFirstPage({ items: [1, 2], nextToken: "fresh-t2" });
    const trace = recordTrace(sut);

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2]);
    expect(sut.currentToken).toBe("fresh-t2");
    expect(trace).not.toContain("collection:reset");
  });

  it("an unchanged single loaded page adopts a newly terminal token", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 1);
    api.setFirstPage({ items: [1, 2], nextToken: null });

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
    expect(sut.loadMoreCommand.canExecute()).toBe(false);
  });

  it("a changed head replaces the accumulator and adopts the refreshed token", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 2);
    api.setFirstPage({ items: [9, 2], nextToken: "u2" });
    const trace = recordTrace(sut);

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([9, 2]);
    expect(sut.currentToken).toBe("u2");
    expect(trace.filter((entry) => entry === "collection:reset")).toHaveLength(1);
  });

  it("a terminal first page shorter than the accumulator replaces it", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 2);
    api.setFirstPage({ items: [1, 2], nextToken: null });

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
  });

  it("an empty terminal first page clears a non-empty accumulator", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 2);
    api.setFirstPage({ items: [], nextToken: null });
    const trace = recordTrace(sut);

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
    expect(trace).toContain("collection:reset");
  });

  it("an empty first page with a continuation replaces the accumulator and adopts the token", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 2);
    api.setFirstPage({ items: [], nextToken: "u1" });

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBe("u1");
    expect(sut.hasMore).toBe(true);
  });

  it("a refresh after reaching the end keeps the terminal cursor while the head matches", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 4);
    const trace = recordTrace(sut);

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
    expect(sut.loadMoreCommand.canExecute()).toBe(false);
    expect(trace).not.toContain("collection:reset");
  });

  it("the no-mutation branch publishes properties then re-signals commands, with no collection event", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 3);
    const trace = recordTrace(sut);

    await sut.refreshCommand.executeAsync();

    expect(trace).toEqual([
      "property:items",
      "property:currentToken",
      "property:hasMore",
      "loadMore:canExecuteChanged",
    ]);
  });

  it("the replacement branch publishes one reset, then properties, then re-signals commands", async () => {
    const api = backend(PAGES);
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await loadPages(sut, 3);
    api.setFirstPage({ items: [8, 9], nextToken: "u2" });
    const trace = recordTrace(sut);

    await sut.refreshCommand.executeAsync();

    expect(trace).toEqual([
      "collection:reset",
      "property:items",
      "property:currentToken",
      "property:hasMore",
      "loadMore:canExecuteChanged",
    ]);
  });

  it("a load started during a refresh makes the refresh result stale", async () => {
    const resolvers: Array<(page: Page<number>) => void> = [];
    const requested: Array<string | null> = [];
    const sut = new TokenPagedComposition<number, string>((token) => {
      requested.push(token);
      return new Promise((resolve) => { resolvers.push(resolve); });
    });
    const firstLoad = sut.loadMoreCommand.executeAsync();
    resolvers[0]!({ items: [1, 2], nextToken: "t2" });
    await firstLoad;

    const refresh = sut.refreshCommand.executeAsync();
    const load = sut.loadMoreCommand.executeAsync();
    resolvers[1]!({ items: [9], nextToken: "stale" });
    await refresh;
    resolvers[2]!({ items: [3, 4], nextToken: "t3" });
    await load;

    expect(requested).toEqual([null, null, "t2"]);
    expect(sut.items).toEqual([1, 2, 3, 4]);
    expect(sut.currentToken).toBe("t3");
  });

  it("a failed refresh fetch leaves items, cursor, and notifications untouched", async () => {
    const api = backend(PAGES);
    let fail = false;
    const sut = new TokenPagedComposition<number, string>((token) =>
      fail ? Promise.reject(new Error("offline")) : api.fetch(token),
    );
    await loadPages(sut, 2);
    fail = true;
    const trace = recordTrace(sut);

    await expect(sut.refreshCommand.executeAsync()).rejects.toThrow("offline");

    expect(sut.items).toEqual([1, 2, 3, 4]);
    expect(sut.currentToken).toBe("t3");
    expect(trace).toEqual([]);
    expect(sut.refreshCommand.isExecuting).toBe(false);
  });

  it("a throwing page comparer leaves items, cursor, and notifications untouched", async () => {
    const api = backend(PAGES);
    let fail = false;
    const sut = new TokenPagedComposition<number, string>(api.fetch, {
      pagesEqual: (left, right) => {
        if (fail) throw new Error("comparer failed");
        return left.length === right.length && left.every((item, index) => item === right[index]);
      },
    });
    await loadPages(sut, 2);
    fail = true;
    const trace = recordTrace(sut);

    await expect(sut.refreshCommand.executeAsync()).rejects.toThrow("comparer failed");

    expect(sut.items).toEqual([1, 2, 3, 4]);
    expect(sut.currentToken).toBe("t3");
    expect(trace).toEqual([]);
  });

  it("disposal before a retained-prefix refresh completes leaves state and notifications untouched", async () => {
    let releaseRefresh!: (page: Page<number>) => void;
    const api = backend(PAGES);
    let hold = false;
    const sut = new TokenPagedComposition<number, string>((token) =>
      hold
        ? new Promise((resolve) => { releaseRefresh = resolve; })
        : api.fetch(token),
    );
    await loadPages(sut, 2);
    hold = true;
    const trace = recordTrace(sut);

    const refresh = sut.refreshCommand.executeAsync();
    sut.dispose();
    releaseRefresh({ items: [1, 2], nextToken: "t2" });
    await refresh;

    expect(sut.items).toEqual([1, 2, 3, 4]);
    expect(sut.currentToken).toBe("t3");
    expect(trace).toEqual([]);
  });

  it("retained and replaced item VMs are never disposed by the composition", async () => {
    const vm = (name: string) => ComponentVM.builder().name(name).withNullServices().build();
    const loaded = [vm("a"), vm("b"), vm("c"), vm("d")];
    const equalHead = [vm("a"), vm("b")];
    const changedHead = [vm("x"), vm("y")];
    let refreshPage = equalHead;
    const sut = new TokenPagedComposition<ComponentVM, string>(
      (token) => Promise.resolve(
        token === null
          ? (sut.items.length === 0
            ? { items: loaded.slice(0, 2), nextToken: "t2" }
            : { items: refreshPage, nextToken: "t2" })
          : { items: loaded.slice(2), nextToken: "t3" },
      ),
      {
        autoConstructOnAdd: true,
        pagesEqual: (left, right) =>
          left.length === right.length && left.every((item, index) => item.name === right[index]?.name),
      },
    );
    await sut.loadMoreCommand.executeAsync();
    await sut.loadMoreCommand.executeAsync();

    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual(loaded);
    expect(sut.currentToken).toBe("t3");
    expect(equalHead.map((item) => item.status)).toEqual([ConstructionStatus.Destructed, ConstructionStatus.Destructed]);

    refreshPage = changedHead;
    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual(changedHead);
    expect(changedHead.every((item) => item.isConstructed)).toBe(true);
    expect(loaded.every((item) => item.status === ConstructionStatus.Constructed)).toBe(true);
  });
});
