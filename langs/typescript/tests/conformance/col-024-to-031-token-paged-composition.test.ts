// Conformance tests: COL-024..COL-031 — token pagination and composite source paging.

import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  ContainerRollbackError,
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

  // ADR-0169: TypeScript runs the load body up to its first await in the
  // admission turn, so a terminal token cannot land between admission and the
  // body's hasMore check. This pins that admission-turn start (#1484).
  it("loadMore calls fetchNext in the admission turn, before executeAsync's promise is awaited", async () => {
    const calls: Array<string | null> = [];
    const sut = new TokenPagedComposition<number, string>((token) => {
      calls.push(token);
      return Promise.resolve({ items: [1], nextToken: null });
    });

    const run = sut.loadMoreCommand.executeAsync();
    expect(calls).toEqual([null]);

    await run;
    expect(calls).toEqual([null]);
    expect(sut.items).toEqual([1]);
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

    const constructedAtReset: boolean[] = [];
    const actions: string[] = [];
    sut.collectionChanged.subscribe((event) => {
      actions.push(event.action);
      constructedAtReset.push(child.isConstructed);
    });

    await sut.loadMoreCommand.executeAsync();

    // The child must already be constructed when the subscriber observes
    // the reset event, not merely by the time the load completes.
    expect(actions).toEqual(["reset"]);
    expect(constructedAtReset).toEqual([true]);
    expect(child.isConstructed).toBe(true);
  });
});

describe("COL-075", () => {
  const constructFails = (): void => {
    throw new Error("construct failed");
  };
  const destructFails = (): void => {
    throw new Error("destruct failed");
  };

  it("a failed auto-construct load rolls the page back and publishes nothing", async () => {
    const first = ComponentVM.builder().name("first").withNullServices().build();
    const second = ComponentVM.builder()
      .name("second")
      .withNullServices()
      .onConstruct(constructFails)
      .build();
    const third = ComponentVM.builder().name("third").withNullServices().build();
    const page = [first, second, third];
    const sut = new TokenPagedComposition<ComponentVM, string>(
      () => Promise.resolve({ items: page, nextToken: "next" }),
      { autoConstructOnAdd: true },
    );
    const notifications: string[] = [];
    sut.collectionChanged.subscribe((event) => notifications.push(event.action));
    sut.propertyChanged.subscribe((name) => notifications.push(name));

    await expect(sut.loadMoreCommand.executeAsync()).rejects.toThrow("construct failed");

    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(true);
    expect(notifications).toEqual([]);
    expect(page.map((vm) => vm.status)).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
  });

  it("a failed auto-construct refresh keeps the accumulator and publishes nothing", async () => {
    const kept = ComponentVM.builder().name("kept").withNullServices().build();
    const fresh = [
      ComponentVM.builder().name("fresh-1").withNullServices().build(),
      ComponentVM.builder().name("fresh-2").withNullServices().onConstruct(constructFails).build(),
      ComponentVM.builder().name("fresh-3").withNullServices().build(),
    ];
    const pages = [
      { items: [kept], nextToken: "next" },
      { items: fresh, nextToken: null },
    ];
    const sut = new TokenPagedComposition<ComponentVM, string>(
      () => {
        const page = pages.shift();
        if (page === undefined) return Promise.reject(new Error("no page left"));
        return Promise.resolve(page);
      },
      { autoConstructOnAdd: true },
    );
    await sut.loadMoreCommand.executeAsync();
    const notifications: string[] = [];
    sut.collectionChanged.subscribe((event) => notifications.push(event.action));
    sut.propertyChanged.subscribe((name) => notifications.push(name));

    await expect(sut.refreshCommand.executeAsync()).rejects.toThrow("construct failed");

    expect(sut.items.length).toBe(1);
    expect(sut.items[0]).toBe(kept);
    expect(sut.currentToken).toBe("next");
    expect(notifications).toEqual([]);
    expect(fresh.map((vm) => vm.status)).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(kept.status).toBe(ConstructionStatus.Constructed);
  });

  it("a failed auto-construct load keeps an item that was constructed before it", async () => {
    const prior = ComponentVM.builder().name("prior").withNullServices().build();
    prior.construct();
    const fresh = ComponentVM.builder().name("fresh").withNullServices().build();
    const bad = ComponentVM.builder().name("bad").withNullServices().onConstruct(constructFails).build();
    const sut = new TokenPagedComposition<ComponentVM, string>(
      () => Promise.resolve({ items: [prior, fresh, bad], nextToken: null }),
      { autoConstructOnAdd: true },
    );

    await expect(sut.loadMoreCommand.executeAsync()).rejects.toThrow("construct failed");

    expect(sut.items).toEqual([]);
    expect(prior.status).toBe(ConstructionStatus.Constructed);
    expect(fresh.status).toBe(ConstructionStatus.Destructed);
    expect(bad.status).toBe(ConstructionStatus.Destructed);
  });

  it("a failed rollback rejects once with the rollback failure carrying both errors", async () => {
    const stuck = ComponentVM.builder().name("stuck").withNullServices().onDestruct(destructFails).build();
    const bad = ComponentVM.builder().name("bad").withNullServices().onConstruct(constructFails).build();
    const sut = new TokenPagedComposition<ComponentVM, string>(
      () => Promise.resolve({ items: [stuck, bad], nextToken: "next" }),
      { autoConstructOnAdd: true },
    );

    let caught: unknown;
    try {
      await sut.loadMoreCommand.executeAsync();
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ContainerRollbackError);
    const rollback = caught as ContainerRollbackError;
    expect((rollback.cause as Error).message).toBe("construct failed");
    expect((rollback.rollbackError as Error).message).toBe("destruct failed");
    expect(sut.items).toEqual([]);
    expect(sut.currentToken).toBeNull();
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
