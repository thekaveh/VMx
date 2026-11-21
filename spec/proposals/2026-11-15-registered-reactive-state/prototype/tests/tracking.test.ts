/**
 * RSTATE-020 and RSTATE-021: tracking through callbacks, other view-models, untracked and peek; invalidate.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM } from "@thekaveh/vmx";
import { activate, explain, untracked } from "../src/index.js";
import { base, Recorder, type Services, services } from "./support.js";

interface ChildOptions extends Services {
  readonly key: string;
  readonly page: () => string;
}

class Child extends ComponentVM {
  readonly #o: ChildOptions;
  constructor(o: ChildOptions) {
    super(base(o, o.key));
    this.#o = o;
    this.computed("label");
  }
  get label(): string {
    return this.#o.page().toUpperCase();
  }
}

class Owner extends ComponentVM {
  declare readonly mode: string;
  readonly #set;
  readonly #page = this.signal("home");
  readonly child: Child;
  constructor(s: Services) {
    super(base(s, "owner"));
    this.#set = this.observable({ mode: "light" });
    this.child = this.member(Child, { key: "child", page: () => this.#page.value });
    this.computed("summary", "peeked", "hidden");
  }
  get summary(): string {
    return `${this.child.label}/${this.mode}`;
  }
  get peeked(): string {
    return this.#page.peek();
  }
  get hidden(): string {
    return untracked(() => this.mode);
  }
  go(page: string): void {
    this.#page.value = page;
  }
  setMode(mode: string): void {
    this.#set({ mode });
  }
}

describe("RSTATE-020 tracking through callbacks, other view-models, untracked and peek", () => {
  it("a callback option and a member's computed are transparent", () => {
    const s = services();
    const owner = new Owner(s);
    activate(owner);
    const rec = new Recorder(s.hub);
    owner.go("settings");
    assert.deepEqual(rec.hubNames(), ["child.label", "owner.summary"]);
    assert.equal(owner.summary, "SETTINGS/light");
    // R5.4: the owner's computed depends on the member's computed node, not on the signal behind it.
    const sources = explain(owner, "summary").map((entry) => entry.name);
    assert.ok(sources.includes("label"));
    assert.ok(sources.includes("mode"));
    assert.ok(!sources.some((name) => name.startsWith("signal")));
  });

  it("a sibling view-model's state is tracked", () => {
    const s = services();
    const owner = new Owner(s);
    class Sibling extends ComponentVM {
      constructor() {
        super(base(s, "sibling"));
        this.computed("echo");
      }
      get echo(): string {
        return owner.mode.toUpperCase();
      }
    }
    const sibling = new Sibling();
    activate(sibling);
    const rec = new Recorder(s.hub);
    owner.setMode("dark");
    assert.deepEqual(rec.hubNames(), ["owner.mode", "sibling.echo"]);
  });

  it("untracked() and peek() record nothing", () => {
    const s = services();
    const owner = new Owner(s);
    activate(owner);
    const rec = new Recorder(s.hub);
    owner.setMode("dark");
    owner.go("about");
    assert.deepEqual(rec.hubNames(), ["owner.mode", "owner.summary", "child.label", "owner.summary"]);
    assert.equal(owner.peeked, "home");
    assert.equal(owner.hidden, "light");
  });
});

describe("RSTATE-021 invalidate and memo.invalidate", () => {
  class Store {
    marked = new Set<string>();
  }

  class Bookmark extends ComponentVM {
    readonly #store: Store;
    readonly #upper;
    constructor(s: Services, store: Store) {
      super(base(s, "bookmark"));
      this.#store = store;
      this.#upper = this.memo(() => [...this.#store.marked].join(",").toUpperCase());
      this.computed("marked", "memoText");
    }
    get marked(): boolean {
      return this.#store.marked.has("a");
    }
    get memoText(): string {
      return this.#upper.value;
    }
    refresh(): void {
      this.invalidate("marked");
    }
    refreshMemo(): void {
      this.#upper.invalidate();
    }
  }

  it("invalidate re-evaluates a computed over an outside input and announces only a change", () => {
    const s = services();
    const store = new Store();
    const vm = new Bookmark(s, store);
    activate(vm);
    const rec = new Recorder(s.hub);
    vm.refresh();
    assert.deepEqual(rec.hubNames(), []);
    store.marked.add("a");
    vm.refresh();
    assert.deepEqual(rec.hubNames(), ["bookmark.marked"]);
    assert.equal(vm.marked, true);
  });

  it("memo.invalidate re-evaluates the memo and its dependents", () => {
    const s = services();
    const store = new Store();
    const vm = new Bookmark(s, store);
    activate(vm);
    const rec = new Recorder(s.hub);
    store.marked.add("b");
    vm.refreshMemo();
    assert.deepEqual(rec.hubNames(), ["bookmark.memoText"]);
    assert.equal(vm.memoText, "B");
  });

  it("invalidate reaches the readers of a computed of a view-model that is not activated", () => {
    const s = services();
    const store = new Store();
    const bookmark = new Bookmark(s, store);
    class Reader extends ComponentVM {
      constructor() {
        super(base(s, "reader"));
        this.computed("text");
      }
      get text(): string {
        return bookmark.marked ? "marked" : "free";
      }
    }
    const reader = new Reader();
    activate(reader);
    const rec = new Recorder(s.hub);
    store.marked.add("a");
    bookmark.refresh();
    assert.deepEqual(rec.hubNames(), ["reader.text"]);
  });
});
