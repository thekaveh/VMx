// HIER-015..HIER-017 conformance tests — HierarchicalVMBuilder<TModel, TVM>.
// See spec/10-builders.md §3 and ADR-0035 §2 H1 / H2.

import { describe, expect, it } from "vitest";

import {
  BuilderValidationError,
  HierarchicalVM,
  HierarchicalVMBuilder,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";
import type {
  HierarchicalVMConstructionContext,
  IDispatcher,
  IMessageHub,
} from "../../src/index.js";

// ---------------------------------------------------------------------------
// Shared helpers — minimal concrete TVM that satisfies the recursive generic
// constraint so the builder can produce nodes.
// ---------------------------------------------------------------------------

class TestNode extends HierarchicalVM<string, TestNode> {
  constructor(ctx: HierarchicalVMConstructionContext<string, TestNode>) {
    super(ctx);
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

function makeHub(): IMessageHub {
  return new MessageHub();
}

function makeDispatcher(): IDispatcher {
  return RxDispatcher.immediate();
}

function emptyChildren(): (parent: TestNode) => Iterable<TestNode> {
  return () => [];
}

function builder(): HierarchicalVMBuilder<string, TestNode> {
  return new HierarchicalVMBuilder<string, TestNode>();
}

// ---------------------------------------------------------------------------
// HIER-015 — build() validates each required field
// ---------------------------------------------------------------------------

describe("HIER-015", () => {
  describe("missing model", () => {
    it("throws BuilderValidationError('model') when model not set", () => {
      const b = builder()
        .childrenFactory(emptyChildren())
        .services(makeHub(), makeDispatcher())
        .vmFactory((ctx) => new TestNode(ctx));
      expect(() => b.build()).toThrow(BuilderValidationError);
      try {
        b.build();
      } catch (e) {
        expect(e).toBeInstanceOf(BuilderValidationError);
        expect((e as BuilderValidationError).missingField).toBe("model");
      }
    });
  });

  describe("missing childrenFactory", () => {
    it("throws BuilderValidationError('childrenFactory') when childrenFactory not set", () => {
      const b = builder()
        .model("root")
        .services(makeHub(), makeDispatcher())
        .vmFactory((ctx) => new TestNode(ctx));
      expect(() => b.build()).toThrow(BuilderValidationError);
      try {
        b.build();
      } catch (e) {
        expect(e).toBeInstanceOf(BuilderValidationError);
        expect((e as BuilderValidationError).missingField).toBe(
          "childrenFactory",
        );
      }
    });
  });

  describe("missing services", () => {
    it("throws BuilderValidationError('services') when services not set", () => {
      const b = builder()
        .model("root")
        .childrenFactory(emptyChildren())
        .vmFactory((ctx) => new TestNode(ctx));
      expect(() => b.build()).toThrow(BuilderValidationError);
      try {
        b.build();
      } catch (e) {
        expect(e).toBeInstanceOf(BuilderValidationError);
        expect((e as BuilderValidationError).missingField).toBe("services");
      }
    });
  });

  describe("missing vmFactory", () => {
    it("throws BuilderValidationError('vmFactory') when vmFactory not set", () => {
      const b = builder()
        .model("root")
        .childrenFactory(emptyChildren())
        .services(makeHub(), makeDispatcher());
      expect(() => b.build()).toThrow(BuilderValidationError);
      try {
        b.build();
      } catch (e) {
        expect(e).toBeInstanceOf(BuilderValidationError);
        expect((e as BuilderValidationError).missingField).toBe("vmFactory");
      }
    });
  });
});

// ---------------------------------------------------------------------------
// HIER-016 — Repeated build() calls produce distinct-but-equivalent nodes
// ---------------------------------------------------------------------------

describe("HIER-016", () => {
  it("repeated build() calls produce distinct-but-equivalent nodes", () => {
    const b = builder()
      .model("root")
      .childrenFactory(emptyChildren())
      .services(makeHub(), makeDispatcher())
      .hint("h")
      .eagerChildren(true)
      .vmFactory((ctx) => new TestNode(ctx));

    const n1 = b.build();
    const n2 = b.build();

    // Distinct instances.
    expect(n1).not.toBe(n2);
    // Equivalent observable state.
    expect(n1.model).toBe("root");
    expect(n2.model).toBe("root");
    expect(n1.model).toBe(n2.model);
    expect(n1.hint).toBe("h");
    expect(n2.hint).toBe("h");
    expect(n1.hint).toBe(n2.hint);
  });
});

// ---------------------------------------------------------------------------
// HIER-017 — Field defaults applied when not set
// ---------------------------------------------------------------------------

describe("HIER-017", () => {
  it("hint defaults to empty string and eagerChildren defaults to false", () => {
    let materialized = false;
    const node = builder()
      .model("root")
      .childrenFactory(() => {
        materialized = true;
        return [];
      })
      .services(makeHub(), makeDispatcher())
      .vmFactory((ctx) => new TestNode(ctx))
      .build();

    expect(node.hint).toBe("");
    // eagerChildren defaults to false: children NOT materialized at construct().
    expect(materialized).toBe(false);
    // Sanity check: accessing `children` lazily materializes them.
    node.construct();
    expect(materialized).toBe(false);
    void node.children;
    expect(materialized).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// H2 / BLD-001 — withDefaultServices Wither
// ---------------------------------------------------------------------------

describe("withDefaultServices", () => {
  it("wires real (non-null) hub + dispatcher", () => {
    const node = builder()
      .model("root")
      .childrenFactory(emptyChildren())
      .withDefaultServices()
      .vmFactory((ctx) => new TestNode(ctx))
      .build();

    expect(node).toBeInstanceOf(TestNode);
    expect(node.model).toBe("root");
  });

  it("returns a new builder instance (BLD-001)", () => {
    const b1 = builder()
      .model("root")
      .childrenFactory(emptyChildren())
      .vmFactory((ctx) => new TestNode(ctx));
    const b2 = b1.withDefaultServices();
    expect(b1).not.toBe(b2);

    // b1 still has no services wired — building it raises.
    expect(() => b1.build()).toThrow(BuilderValidationError);
    try {
      b1.build();
    } catch (e) {
      expect((e as BuilderValidationError).missingField).toBe("services");
    }

    // b2 builds successfully.
    const n = b2.build();
    expect(n.model).toBe("root");
  });
});
