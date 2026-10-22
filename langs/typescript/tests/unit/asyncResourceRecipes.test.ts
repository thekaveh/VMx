/**
 * Executable form of the AsyncResourceVM recipes in
 * docs/content/primitives/state-reactive-helpers.md and the token-paging
 * failure recipe in docs/content/primitives/builders-collections-tree-utilities.md.
 * The docs-snippet regions are shown there verbatim, dedented, and
 * `make docs-check` keeps them equal. No conformance ID (recipes; #657).
 */
import { asyncScheduler, timer, type Subscription } from "rxjs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AsyncResourceRetention,
  AsyncResourceStatus,
  AsyncResourceVM,
  ComponentVMBase,
  MessageHub,
  RxDispatcher,
  TokenPagedComposition,
  ViewModelType,
  wrapWith,
  type DecoratorCommand,
  type IDispatcher,
  type IMessageHub,
  type TokenPage,
} from "../../src/index.js";

interface Metric {
  value: number;
}

interface MetricsApi {
  fetch(signal: AbortSignal): Promise<Metric[]>;
}

// docs-snippet:start polling-panel
class MetricsPanelVM extends ComponentVMBase {
  readonly resource: AsyncResourceVM<Metric[]>;
  readonly retryCommand: DecoratorCommand;
  #poll: Subscription | null = null;

  constructor(api: MetricsApi, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "metrics-panel", hub, dispatcher });
    this.resource = this.own(
      new AsyncResourceVM({
        name: "metrics",
        hub,
        dispatcher,
        loader: (signal) => api.fetch(signal),
        // A reload keeps the last value visible instead of blanking the view.
        retention: AsyncResourceRetention.RetainPrevious,
      }),
    );
    // Retry is a reload, offered only after a failure.
    this.retryCommand = this.own(
      wrapWith(
        this.resource.reloadCommand,
        () => this.resource.state.status === AsyncResourceStatus.Error,
      ),
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  // Poll while constructed: load at once, then reload every 30 s.
  protected override _onConstruct(): void {
    super._onConstruct();
    this.#poll = timer(0, 30_000, this._dispatcher.foreground).subscribe(() => {
      const { status } = this.resource.state;
      if (status === AsyncResourceStatus.Idle) void this.resource.load();
      // Skip a tick while a load runs; a reload would supersede it.
      else if (status !== AsyncResourceStatus.Loading) void this.resource.reload();
    });
  }

  protected override _onDestruct(): void {
    this.#poll?.unsubscribe();
    this.#poll = null;
    this.resource.cancel();
    super._onDestruct();
  }
}
// docs-snippet:end polling-panel

/** A fake API whose fetches the test settles one by one. */
function controlledApi() {
  const pending: {
    signal: AbortSignal;
    resolve: (value: Metric[]) => void;
    reject: (error: unknown) => void;
  }[] = [];
  const api: MetricsApi = {
    fetch: (signal) =>
      new Promise<Metric[]>((resolve, reject) => {
        pending.push({ signal, resolve, reject });
      }),
  };
  return { api, pending };
}

const hub = () => new MessageHub();

describe("AsyncResourceVM recipes", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const dispatcher = () => new RxDispatcher(asyncScheduler, asyncScheduler);

  it("offers retry only in Error, and retry reloads to Ready", async () => {
    const { api, pending } = controlledApi();
    const panel = new MetricsPanelVM(api, hub(), dispatcher());
    let retryChanges = 0;
    panel.retryCommand.canExecuteChanged.subscribe(() => (retryChanges += 1));

    expect(panel.retryCommand.canExecute()).toBe(false); // Idle
    void panel.resource.load();
    expect(panel.retryCommand.canExecute()).toBe(false); // Loading
    pending[0]!.reject(new Error("offline"));
    await vi.advanceTimersByTimeAsync(0);

    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Error);
    expect(panel.retryCommand.canExecute()).toBe(true);
    expect(panel.resource.loadCommand.canExecute()).toBe(false);
    expect(retryChanges).toBeGreaterThanOrEqual(2);

    panel.retryCommand.execute();
    expect(panel.retryCommand.canExecute()).toBe(false); // Loading again
    pending[1]!.resolve([{ value: 1 }]);
    await vi.advanceTimersByTimeAsync(0);

    expect(panel.resource.state).toEqual({
      status: AsyncResourceStatus.Ready,
      value: [{ value: 1 }],
    });
    expect(panel.retryCommand.canExecute()).toBe(false);
    panel.dispose();
  });

  it("lets the latest start win without rejection handling", async () => {
    const { api, pending } = controlledApi();
    const panel = new MetricsPanelVM(api, hub(), dispatcher());
    const errors: unknown[] = [];
    panel.resource.reloadCommand.errors.subscribe((error) => errors.push(error));
    void panel.resource.load();
    pending[0]!.resolve([{ value: 1 }]);
    await vi.advanceTimersByTimeAsync(0);

    const first = panel.resource.reload();
    const second = panel.resource.reload();
    pending[2]!.reject(new Error("offline"));
    pending[1]!.resolve([{ value: 2 }]); // stale: ignored

    const settled = await Promise.allSettled([first, second]);
    expect(settled.map((result) => result.status)).toEqual(["fulfilled", "fulfilled"]);
    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Error);
    expect(panel.resource.state).toMatchObject({ value: [{ value: 1 }] });

    panel.resource.reloadCommand.execute();
    pending[3]!.reject(new Error("still offline"));
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Error);
    expect(errors).toEqual([]);
    panel.dispose();
  });

  it("lets a reload supersede a load that loadCommand started", async () => {
    const { api, pending } = controlledApi();
    const panel = new MetricsPanelVM(api, hub(), dispatcher());

    panel.resource.loadCommand.execute();
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.reloadCommand.canExecute()).toBe(true);
    panel.resource.reloadCommand.execute();
    await vi.advanceTimersByTimeAsync(0);
    expect(pending).toHaveLength(2);

    pending[0]!.resolve([{ value: 1 }]); // superseded: ignored
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Loading);
    pending[1]!.resolve([{ value: 2 }]);
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.state).toEqual({
      status: AsyncResourceStatus.Ready,
      value: [{ value: 2 }],
    });
    panel.dispose();
  });

  it("reloads from Error on the next tick", async () => {
    const { api, pending } = controlledApi();
    const panel = new MetricsPanelVM(api, hub(), dispatcher());

    panel.construct();
    await vi.advanceTimersByTimeAsync(0);
    pending[0]!.reject(new Error("offline"));
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Error);

    await vi.advanceTimersByTimeAsync(30_000);
    expect(pending).toHaveLength(2);
    panel.dispose();
  });

  it("polls while constructed and skips ticks during a load", async () => {
    const { api, pending } = controlledApi();
    const panel = new MetricsPanelVM(api, hub(), dispatcher());

    panel.construct();
    await vi.advanceTimersByTimeAsync(0);
    expect(pending).toHaveLength(1); // the first tick loads
    pending[0]!.resolve([{ value: 1 }]);
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Ready);

    await vi.advanceTimersByTimeAsync(30_000);
    expect(pending).toHaveLength(2); // the next tick reloads
    // RetainPrevious: the view keeps the last value while the reload runs.
    expect(panel.resource.state).toEqual({
      status: AsyncResourceStatus.Loading,
      value: [{ value: 1 }],
    });

    // A load longer than the interval: later ticks start nothing.
    await vi.advanceTimersByTimeAsync(90_000);
    expect(pending).toHaveLength(2);
    expect(pending[1]!.signal.aborted).toBe(false);
    pending[1]!.resolve([{ value: 2 }]);
    await vi.advanceTimersByTimeAsync(0);
    expect(panel.resource.state).toEqual({
      status: AsyncResourceStatus.Ready,
      value: [{ value: 2 }],
    });
    panel.dispose();
  });

  it("stops polling and cancels the running load at destruct", async () => {
    const { api, pending } = controlledApi();
    const panel = new MetricsPanelVM(api, hub(), dispatcher());

    panel.construct();
    await vi.advanceTimersByTimeAsync(0);
    panel.destruct();

    expect(pending[0]!.signal.aborted).toBe(true);
    expect(panel.resource.state.status).toBe(AsyncResourceStatus.Idle);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(pending).toHaveLength(1);

    panel.construct(); // constructing again resumes polling
    await vi.advanceTimersByTimeAsync(0);
    expect(pending).toHaveLength(2);
    panel.dispose();
    expect(pending[1]!.signal.aborted).toBe(true);
  });

  it("cancels only the operations started with an aborted signal", async () => {
    const { api, pending } = controlledApi();
    const resource = new AsyncResourceVM({
      name: "metrics",
      hub: hub(),
      dispatcher: dispatcher(),
      loader: (signal) => api.fetch(signal),
    });
    const construct = new AbortController();

    void resource.load(construct.signal);
    construct.abort();
    await vi.advanceTimersByTimeAsync(0);
    expect(pending[0]!.signal.aborted).toBe(true);
    expect(resource.state.status).toBe(AsyncResourceStatus.Idle);

    void resource.load(); // started without the signal
    construct.abort();
    expect(pending[1]!.signal.aborted).toBe(false);
    resource.cancel(); // cancels whichever operation is current
    expect(pending[1]!.signal.aborted).toBe(true);
    resource.dispose();
  });
});

interface Note {
  id: number;
}

describe("TokenPagedComposition failure recipe", () => {
  it("surfaces a failed fetch only on the command's errors stream", async () => {
    const pages: TokenPage<Note, string>[] = [{ items: [{ id: 1 }], nextToken: "2" }];
    const api = {
      page: (token: string | null): Promise<TokenPage<Note, string>> =>
        token === null || pages.length > 0
          ? Promise.resolve(pages.shift() ?? { items: [], nextToken: null })
          : Promise.reject(new Error(`page ${token} failed`)),
    };
    const shown: unknown[] = [];
    const notify = (error: unknown): void => {
      shown.push(error);
    };

    // docs-snippet:start token-paged-failures
    const pager = new TokenPagedComposition<Note, string>((token) => api.page(token));
    // execute() has no caller to reject, so a failed fetch arrives here.
    pager.loadMoreCommand.errors.subscribe(notify);
    pager.refreshCommand.errors.subscribe(notify);
    // docs-snippet:end token-paged-failures

    await pager.loadMoreCommand.executeAsync();
    expect(pager.items).toEqual([{ id: 1 }]);
    let published = 0;
    pager.collectionChanged.subscribe(() => (published += 1));
    pager.propertyChanged.subscribe(() => (published += 1));

    pager.loadMoreCommand.execute();
    await vi.waitFor(() => expect(shown).toHaveLength(1));

    expect((shown[0] as Error).message).toBe("page 2 failed");
    expect(pager.items).toEqual([{ id: 1 }]);
    expect(pager.currentToken).toBe("2");
    expect(pager.hasMore).toBe(true);
    expect(published).toBe(0);

    // Awaiting executeAsync() rejects instead of reaching the errors stream.
    await expect(pager.loadMoreCommand.executeAsync()).rejects.toThrow("page 2 failed");
    expect(shown).toHaveLength(1);
    pager.dispose();
  });

  it("surfaces a failed refresh the same way", async () => {
    const pager = new TokenPagedComposition<Note, string>(() =>
      Promise.reject(new Error("refresh failed")),
    );
    const shown: unknown[] = [];
    pager.refreshCommand.errors.subscribe((error) => shown.push(error));

    pager.refreshCommand.execute();
    await vi.waitFor(() => expect(shown).toHaveLength(1));

    expect(pager.items).toEqual([]);
    expect(pager.hasMore).toBe(true);
    pager.dispose();
  });

  it("lets a failed operation supersede an older one in progress", async () => {
    let resolveFirst!: (page: TokenPage<Note, string>) => void;
    const fetches = [
      new Promise<TokenPage<Note, string>>((resolve) => (resolveFirst = resolve)),
      Promise.reject(new Error("refresh failed")),
    ];
    const pager = new TokenPagedComposition<Note, string>(() => fetches.shift()!);

    const load = pager.loadMoreCommand.executeAsync();
    await expect(pager.refreshCommand.executeAsync()).rejects.toThrow("refresh failed");
    resolveFirst({ items: [{ id: 1 }], nextToken: null });
    await load;

    expect(pager.items).toEqual([]); // the older load's page is dropped
    pager.dispose();
  });
});
