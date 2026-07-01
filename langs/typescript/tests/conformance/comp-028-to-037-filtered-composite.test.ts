// Conformance tests: COMP-028..037 — filtered and scored composite views.

import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  FilteredCompositeVM,
  FilteredCursorPolicy,
  NullDispatcher,
  NullMessageHub,
  ScoredFilteredCompositeVM,
} from "../../src/index.js";

function child(name: string): ComponentVM {
  return ComponentVM.builder().name(name).withNullServices().build();
}

function source(...names: string[]): CompositeVM<ComponentVM> {
  const vm = CompositeVM.builder<ComponentVM>()
    .name("source")
    .services(NullMessageHub.INSTANCE, NullDispatcher.INSTANCE)
    .children(() => [])
    .build();
  for (const name of names) vm.add(child(name));
  return vm;
}

describe("COMP-028", () => {
  it("filtered visible projection applies the predicate", () => {
    const sut = new FilteredCompositeVM(source("alpha", "beta"), { predicate: (vm) => vm.name.includes("a") });
    expect(sut.visible.map((vm) => vm.name)).toEqual(["alpha", "beta"]);
  });
});

describe("COMP-029", () => {
  it("visibleCount reports projection length", () => {
    const sut = new FilteredCompositeVM(source("alpha", "bee"), { predicate: (vm) => vm.name.includes("a") });
    expect(sut.visibleCount).toBe(1);
  });
});

describe("COMP-030", () => {
  it("current maps to the visible domain", () => {
    const src = source("alpha", "bee");
    const sut = new FilteredCompositeVM(src, { predicate: (vm) => vm.name.includes("a") });
    sut.current = sut.visible[0]!;
    expect(sut.current).toBe(src.at(0));
  });
});

describe("COMP-031", () => {
  it("predicate change recomputes projection", () => {
    const sut = new FilteredCompositeVM(source("alpha", "bee"), { predicate: (vm) => vm.name.includes("a") });
    sut.setPredicate((vm) => vm.name.includes("e"));
    expect(sut.visible.map((vm) => vm.name)).toEqual(["bee"]);
  });
});

describe("COMP-032", () => {
  it("source mutation reconciles projection", () => {
    const src = source("alpha");
    const sut = new FilteredCompositeVM(src, { predicate: (vm) => vm.name.includes("z") });
    src.add(child("zulu"));
    expect(sut.visible.map((vm) => vm.name)).toEqual(["zulu"]);
  });
});

describe("COMP-033", () => {
  it("cursor policies handle filtered-out current", () => {
    const src = source("alpha", "bee");
    const snap = new FilteredCompositeVM(src, { predicate: () => true });
    snap.current = src.at(1);
    snap.setPredicate((vm) => vm.name === "alpha");
    expect(snap.current).toBe(src.at(0));

    const clear = new FilteredCompositeVM(src, { predicate: () => true, cursorPolicy: FilteredCursorPolicy.Clear });
    clear.current = src.at(1);
    clear.setPredicate((vm) => vm.name === "alpha");
    expect(clear.current).toBeNull();
  });
});

describe("COMP-034", () => {
  it("visible navigation moves previous and next", () => {
    const sut = new FilteredCompositeVM(source("alpha", "bee", "gamma"), { predicate: (vm) => vm.name.includes("a") });
    sut.current = sut.visible[0]!;
    sut.moveToNextVisible();
    expect(sut.current).toBe(sut.visible[1]);
    sut.moveToPreviousVisible();
    expect(sut.current).toBe(sut.visible[0]);
  });
});

describe("COMP-035", () => {
  it("dispose stops source subscription", () => {
    const src = source("alpha");
    const sut = new FilteredCompositeVM(src, { predicate: () => true });
    sut.dispose();
    src.add(child("bee"));
    expect(sut.visible.map((vm) => vm.name)).toEqual(["alpha"]);
  });
});

describe("COMP-036", () => {
  it("scored filter sorts by score with stable ties", () => {
    const sut = new ScoredFilteredCompositeVM(source("alpha", "bee", "ax"), {
      scorer: (vm) => vm.name.startsWith("a") ? 1 : null,
    });
    expect(sut.visible.map((vm) => vm.name)).toEqual(["alpha", "ax"]);
  });
});

describe("COMP-037", () => {
  it("scored filter recomputes order when scores change", () => {
    const weights = new Map([["alpha", 1], ["bee", 2]]);
    const sut = new ScoredFilteredCompositeVM(source("alpha", "bee"), {
      scorer: (vm) => weights.get(vm.name) ?? null,
    });
    expect(sut.visible.map((vm) => vm.name)).toEqual(["bee", "alpha"]);
    weights.set("alpha", 3);
    sut.refreshScores();
    expect(sut.visible.map((vm) => vm.name)).toEqual(["alpha", "bee"]);
  });
});
