// Conformance stubs: HIER-001..HIER-014 — HierarchicalVM recursive tree VM.
// See spec/18-hierarchical-vm.md and ADR-0028. Substage 2A (spec foundation).

import { describe, it } from "vitest";

describe("HIER-001", () => {
  it.todo("Recursive generic constraint compiles per flavor");
});

describe("HIER-002", () => {
  it.todo("Parent is null for root, non-null for non-root");
});

describe("HIER-003", () => {
  it.todo("Depth derivation — root is 0, child is parent + 1");
});

describe("HIER-004", () => {
  it.todo("Path materialization — returns root-first snapshot; cached until reparent");
});

describe("HIER-005", () => {
  it.todo("IsLeaf and IsRoot derivation match Parent/Children state");
});

describe("HIER-006", () => {
  it.todo("IsFirst and IsLast position predicates");
});

describe("HIER-007", () => {
  it.todo("Default lazy child loading — children factory not called until first access");
});

describe("HIER-008", () => {
  it.todo("Eager child loading via withEagerChildren() builder option");
});

describe("HIER-009", () => {
  it.todo("Depth-first construction order — deepest node reaches Constructed first");
});

describe("HIER-010", () => {
  it.todo("PropertyChangedMessage on parent change");
});

describe("HIER-011", () => {
  it.todo("TreeStructureChangedMessage on add / remove / reparent");
});

describe("HIER-012", () => {
  it.todo("walkExpanded honors lazy boundaries when ExpandableState gate is composed");
});

describe("HIER-013", () => {
  it.todo("Composition with SearchableState filters materialized portion");
});

describe("HIER-014", () => {
  it.todo("Composition with ModeledCrudCommands mutates the tree");
});
