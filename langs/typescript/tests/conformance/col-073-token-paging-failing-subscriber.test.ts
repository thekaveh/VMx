// Conformance tests: COL-073 — a failing subscriber of a token-paging
// notification step skips no later step of the committed load or refresh
// (spec/21 §6.2, ADR-0234, extends ADR-0220). rxjs reports each subscriber error
// through config.onUnhandledError, so the load or refresh returns normally and
// every later step still runs.

import { config } from "rxjs";
import { describe, expect, it } from "vitest";
import { TokenPagedComposition } from "../../src/index.js";

type Page = { items: number[]; nextToken: string | null };

/** Runs act with rxjs unhandled-error reports recorded, then drains them. */
async function withUnhandledErrors(act: () => Promise<unknown>): Promise<unknown[]> {
  const unhandled: unknown[] = [];
  const previous = config.onUnhandledError;
  config.onUnhandledError = (error) => unhandled.push(error);
  try {
    await act();
    await new Promise((resolve) => setTimeout(resolve, 0));
  } finally {
    config.onUnhandledError = previous;
  }
  return unhandled;
}

function fail(): never {
  throw new Error("subscriber failed");
}

/** A first page that can change between calls; the page after it is terminal. */
function backend(first: Page) {
  let firstPage = first;
  return {
    fetch: (token: string | null): Promise<Page> =>
      Promise.resolve(token === null ? firstPage : { items: [3], nextToken: null }),
    setFirstPage(page: Page) {
      firstPage = page;
    },
  };
}

describe("COL-073", () => {
  it("a failing Reset subscriber skips no later step of a load", async () => {
    const api = backend({ items: [1, 2], nextToken: null });
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    const trace: string[] = [];
    sut.collectionChanged.subscribe(fail);
    sut.collectionChanged.subscribe((event) => trace.push(`collection:${event.action}`));
    sut.propertyChanged.subscribe((name) => trace.push(`property:${name}`));
    // The load command raises its own canExecuteChanged, so the trace observes the
    // refresh command, which only the composition's re-signal reaches during a load.
    sut.refreshCommand.canExecuteChanged.subscribe(() => trace.push("command:canExecuteChanged"));

    const unhandled = await withUnhandledErrors(() => sut.loadMoreCommand.executeAsync());

    expect(sut.items).toEqual([1, 2]);
    expect(sut.hasMore).toBe(false);
    expect(trace).toEqual([
      "collection:reset",
      "property:items",
      "property:currentToken",
      "property:hasMore",
      "command:canExecuteChanged",
    ]);
    expect(unhandled).toHaveLength(1);
  });

  it("a failing Reset subscriber skips no later step of a replacing refresh", async () => {
    const api = backend({ items: [1, 2], nextToken: "t2" });
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    await sut.loadMoreCommand.executeAsync();
    api.setFirstPage({ items: [9], nextToken: null });
    const trace: string[] = [];
    sut.collectionChanged.subscribe(fail);
    sut.collectionChanged.subscribe((event) => trace.push(`collection:${event.action}`));
    sut.propertyChanged.subscribe((name) => trace.push(`property:${name}`));
    // The refresh command raises its own canExecuteChanged, so the trace observes
    // the load command, which only the composition's re-signal reaches during a refresh.
    sut.loadMoreCommand.canExecuteChanged.subscribe(() => trace.push("command:canExecuteChanged"));

    const unhandled = await withUnhandledErrors(() => sut.refreshCommand.executeAsync());

    expect(sut.items).toEqual([9]);
    expect(sut.currentToken).toBeNull();
    expect(sut.hasMore).toBe(false);
    expect(trace).toEqual([
      "collection:reset",
      "property:items",
      "property:currentToken",
      "property:hasMore",
      "command:canExecuteChanged",
    ]);
    expect(unhandled).toHaveLength(1);
  });

  it("a failing property subscriber skips no later property or command step", async () => {
    const api = backend({ items: [1, 2], nextToken: null });
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    const names: string[] = [];
    let resignals = 0;
    sut.propertyChanged.subscribe(fail);
    sut.propertyChanged.subscribe((name) => names.push(name));
    sut.refreshCommand.canExecuteChanged.subscribe(() => {
      resignals += 1;
    });

    const unhandled = await withUnhandledErrors(() => sut.loadMoreCommand.executeAsync());

    expect(names).toEqual(["items", "currentToken", "hasMore"]);
    expect(resignals).toBe(1);
    expect(unhandled).toHaveLength(3);
  });

  it("a Reset subscriber that disposes the composition stops the later property and command steps", async () => {
    const api = backend({ items: [1, 2], nextToken: null });
    const sut = new TokenPagedComposition<number, string>(api.fetch);
    const names: string[] = [];
    let resignals = 0;
    sut.collectionChanged.subscribe(() => sut.dispose());
    sut.propertyChanged.subscribe((name) => names.push(name));
    sut.refreshCommand.canExecuteChanged.subscribe(() => {
      resignals += 1;
    });

    const unhandled = await withUnhandledErrors(() => sut.loadMoreCommand.executeAsync());

    expect(names).toEqual([]);
    expect(resignals).toBe(0);
    expect(unhandled).toEqual([]);
  });
});
