// Conformance tests: COL-024..COL-031 — token pagination and composite source paging.

import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  NullDispatcher,
  NullMessageHub,
  PagedComposition,
  TokenPagedComposition,
} from "../../src/index.js";

describe("COL-024", () => {
  it("TokenPagedComposition initial state is empty and loadable", () => {
    const sut = new TokenPagedComposition<number, string>((token) =>
      Promise.resolve(token === null ? { items: [1, 2], nextToken: "next" } : { items: [], nextToken: null }),
    );

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(true);
    expect(sut.loadMoreCommand.canExecute()).toBe(true);
  });
});

describe("COL-025", () => {
  it("loadMore appends items and advances the token", async () => {
    const calls: Array<string | null> = [];
    const sut = new TokenPagedComposition<number, string>((token) => {
      calls.push(token);
      return Promise.resolve(token === null
        ? { items: [1, 2], nextToken: "two" }
        : { items: [3], nextToken: null });
    });

    await sut.loadMoreCommand.executeAsync();
    expect(sut.items).toEqual([1, 2]);
    expect(sut.currentToken).toBe("two");
    expect(sut.hasMore).toBe(true);

    await sut.loadMoreCommand.executeAsync();
    expect(sut.items).toEqual([1, 2, 3]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
    expect(calls).toEqual([null, "two"]);
  });

  it("loadMore does not mutate or notify after disposal during fetch", async () => {
    let resolvePage!: (page: { items: number[]; nextToken: string | null }) => void;
    const pending = new Promise<{ items: number[]; nextToken: string | null }>((resolve) => {
      resolvePage = resolve;
    });
    const sut = new TokenPagedComposition<number, string>(() => pending);
    const collectionEvents: unknown[] = [];
    const propertyEvents: string[] = [];
    sut.collectionChanged.subscribe((event) => collectionEvents.push(event));
    sut.propertyChanged.subscribe((name) => propertyEvents.push(name));

    const load = sut.loadMoreCommand.executeAsync();
    sut.dispose();
    resolvePage({ items: [1, 2], nextToken: "next" });
    await load;

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(true);
    expect(collectionEvents).toEqual([]);
    expect(propertyEvents).toEqual([]);
  });

  it("auto construction may dispose reentrantly without committing the page", async () => {
    let sut!: TokenPagedComposition<ComponentVM, string>;
    const child = ComponentVM.builder()
      .name("child")
      .withNullServices()
      .onConstruct(() => { sut.dispose(); })
      .build();
    sut = new TokenPagedComposition<ComponentVM, string>(
      () => Promise.resolve({ items: [child], nextToken: "next" }),
      { autoConstructOnAdd: true },
    );
    const collectionEvents: unknown[] = [];
    const propertyEvents: string[] = [];
    sut.collectionChanged.subscribe((event) => collectionEvents.push(event));
    sut.propertyChanged.subscribe((name) => propertyEvents.push(name));

    await expect(sut.loadMoreCommand.executeAsync()).resolves.toBeUndefined();

    expect(child.isConstructed).toBe(true);
    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(true);
    expect(collectionEvents).toEqual([]);
    expect(propertyEvents).toEqual([]);
  });
});

describe("COL-026", () => {
  it("terminal token disables loadMore", async () => {
    const sut = new TokenPagedComposition<number, string>(() => Promise.resolve({
      items: [1],
      nextToken: null,
    }));

    await sut.loadMoreCommand.executeAsync();

    expect(sut.hasMore).toBe(false);
    expect(sut.loadMoreCommand.canExecute()).toBe(false);
  });
});

describe("COL-027", () => {
  it("refresh clears and refetches the first page", async () => {
    const pages = [
      { items: [1, 2], nextToken: "next" },
      { items: [9], nextToken: null },
    ];
    const sut = new TokenPagedComposition<number, string>((token) => {
      expect(token).toBeNull();
      return Promise.resolve(pages.shift()!);
    });

    await sut.loadMoreCommand.executeAsync();
    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([9]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
  });

  it("refresh supersedes an older in-flight loadMore", async () => {
    const resolvers: Array<(page: { items: number[]; nextToken: string | null }) => void> = [];
    const sut = new TokenPagedComposition<number, string>(() =>
      new Promise((resolve) => { resolvers.push(resolve); }),
    );

    const load = sut.loadMoreCommand.executeAsync();
    const refresh = sut.refreshCommand.executeAsync();
    resolvers[1]!({ items: [9], nextToken: "fresh" });
    await refresh;
    expect(sut.items).toEqual([9]);

    resolvers[0]!({ items: [1], nextToken: "stale" });
    await load;

    expect(sut.items).toEqual([9]);
    expect(sut.currentToken).toBe("fresh");
  });

  it("refresh does not mutate or notify after disposal during fetch", async () => {
    let resolvePage!: (page: { items: number[]; nextToken: string | null }) => void;
    const pending = new Promise<{ items: number[]; nextToken: string | null }>((resolve) => {
      resolvePage = resolve;
    });
    const sut = new TokenPagedComposition<number, string>(() => pending);
    const collectionEvents: unknown[] = [];
    const propertyEvents: string[] = [];
    sut.collectionChanged.subscribe((event) => collectionEvents.push(event));
    sut.propertyChanged.subscribe((name) => propertyEvents.push(name));

    const refresh = sut.refreshCommand.executeAsync();
    sut.dispose();
    resolvePage({ items: [9], nextToken: null });
    await refresh;

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(true);
    expect(collectionEvents).toEqual([]);
    expect(propertyEvents).toEqual([]);
  });

  it("a page comparer may dispose reentrantly without committing refresh state", async () => {
    let sut!: TokenPagedComposition<number, string>;
    sut = new TokenPagedComposition<number, string>(
      () => Promise.resolve({ items: [1], nextToken: "next" }),
      {
        pagesEqual: (left, right) => {
          sut.dispose();
          return left.length === right.length;
        },
      },
    );

    await expect(sut.refreshCommand.executeAsync()).resolves.toBeUndefined();

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(true);
  });
});

describe("COL-028", () => {
  it("refresh dedup guard suppresses redundant mutation", async () => {
    const sut = new TokenPagedComposition<number, string>(() => Promise.resolve({
      items: [1, 2],
      nextToken: "next",
    }));
    const events: unknown[] = [];
    sut.collectionChanged.subscribe((event) => events.push(event));

    await sut.loadMoreCommand.executeAsync();
    await sut.refreshCommand.executeAsync();

    expect(sut.items).toEqual([1, 2]);
    expect(events).toHaveLength(1);
  });
});

describe("COL-029", () => {
  it("collectionChanged uses reset events", async () => {
    const sut = new TokenPagedComposition<number, string>(() => Promise.resolve({
      items: [1, 2],
      nextToken: null,
    }));
    const actions: string[] = [];
    sut.collectionChanged.subscribe((event) => actions.push(event.action));

    await sut.loadMoreCommand.executeAsync();

    expect(actions).toEqual(["reset"]);
  });
});

describe("COL-030", () => {
  it("autoConstructOnAdd constructs component VMs added by a page", async () => {
    const child = ComponentVM.builder().name("child").withNullServices().build();
    const sut = new TokenPagedComposition<ComponentVM, string>(
      () => Promise.resolve({ items: [child], nextToken: null }),
      { autoConstructOnAdd: true },
    );

    await sut.loadMoreCommand.executeAsync();

    expect(child.isConstructed).toBe(true);
  });
});

describe("COL-031", () => {
  it("PagedComposition observes CompositeVM collection changes", () => {
    const composite = CompositeVM.builder<ComponentVM>()
      .name("source")
      .services(NullMessageHub.INSTANCE, NullDispatcher.INSTANCE)
      .children(() => [])
      .build();
    const sut = new PagedComposition<ComponentVM>(composite, 2);
    const seen: string[] = [];
    sut.propertyChanged.subscribe((name) => seen.push(name));

    composite.add(ComponentVM.builder().name("a").withNullServices().build());

    expect(sut.pageCount).toBe(1);
    expect(seen).toContain("items");
  });
});
