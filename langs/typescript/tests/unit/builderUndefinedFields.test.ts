// Required builder fields must reject `undefined` the same way they reject
// `null`. A typed caller cannot pass `undefined`, but a JavaScript caller or a
// cast can, and build() must then report the missing field (spec/10-builders.md
// §3, BLD-002, BLD-006). Each row below sets one required setter to an absent
// value while every other required setter is valid.
import { describe, expect, it } from "vitest";
import {
  AggregateVM1,
  AggregateVM2,
  AggregateVM3,
  AggregateVM4,
  AggregateVM5,
  AggregateVM6,
  BuilderValidationError,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  CompositeVMOf,
  FormVM,
  GroupVM,
  HierarchicalVM,
  HierarchicalVMBuilder,
  MessageHub,
  ReadonlyComponentVMOf,
  RxDispatcher,
} from "../../src/index.js";
import type { HierarchicalVMConstructionContext } from "../../src/index.js";

class TestNode extends HierarchicalVM<string, TestNode> {
  constructor(ctx: TestContext) {
    super(ctx);
  }
}
type TestContext = HierarchicalVMConstructionContext<string, TestNode>;

const hub = new MessageHub();
const disp = RxDispatcher.immediate();
const child = ComponentVM.builder().name("child").services(hub, disp).build();
const childFactory = (): ComponentVM => child;

/** Returns `value` when `key` names the setter under test, else the valid `fallback`. */
function pick<T>(key: string, target: string, value: unknown, fallback: T): T {
  return key === target ? (value as T) : fallback;
}

interface Built {
  build(): unknown;
}

/** Builds a builder whose setter for `key` receives `value`. */
type Make = (key: string, value: unknown) => Built;

interface Row {
  builder: string;
  /** Pairs of (test key, the `missingField` build() must report). */
  keys: Array<[string, string]>;
  make: Make;
}

const commonKeys: Array<[string, string]> = [
  ["name", "name"],
  ["hub", "services"],
  ["dispatcher", "services"],
];

const aggregateKeys = (arity: number): Array<[string, string]> => [
  ...commonKeys,
  ...Array.from(
    { length: arity },
    (_, i): [string, string] => [`component${i + 1}`, `component${i + 1}`],
  ),
];

const rows: Row[] = [
  {
    builder: "ComponentVM",
    keys: commonKeys,
    make: (k, v) =>
      ComponentVM.builder()
        .name(pick(k, "name", v, "vm"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp)),
  },
  {
    builder: "ComponentVMOf",
    keys: commonKeys,
    make: (k, v) =>
      ComponentVMOf.builder<string>()
        .name(pick(k, "name", v, "vm"))
        .model("m")
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp)),
  },
  {
    builder: "ReadonlyComponentVMOf",
    keys: commonKeys,
    make: (k, v) =>
      ReadonlyComponentVMOf.builder<string>()
        .name(pick(k, "name", v, "vm"))
        .model("m")
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp)),
  },
  {
    builder: "CompositeVM",
    keys: [...commonKeys, ["children", "children"]],
    make: (k, v) =>
      CompositeVM.builder<ComponentVM>()
        .name(pick(k, "name", v, "composite"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .children(pick(k, "children", v, () => [child])),
  },
  {
    builder: "CompositeVMOf",
    keys: [
      ...commonKeys,
      ["childrenModels", "childrenModels"],
      ["childModelToChildViewModel", "childModelToChildViewModel"],
    ],
    make: (k, v) =>
      CompositeVMOf.builder<string, ComponentVM>()
        .name(pick(k, "name", v, "composite"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .childrenModels(pick(k, "childrenModels", v, () => ["m"]))
        .childModelToChildViewModel(
          pick(k, "childModelToChildViewModel", v, () => child),
        ),
  },
  {
    builder: "GroupVM",
    keys: [...commonKeys, ["children", "children"]],
    make: (k, v) =>
      GroupVM.builder<ComponentVM>()
        .name(pick(k, "name", v, "group"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .children(pick(k, "children", v, () => [child])),
  },
  {
    builder: "AggregateVM1",
    keys: aggregateKeys(1),
    make: (k, v) =>
      AggregateVM1.builder<ComponentVM>()
        .name(pick(k, "name", v, "agg"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .component1(pick(k, "component1", v, childFactory)),
  },
  {
    builder: "AggregateVM2",
    keys: aggregateKeys(2),
    make: (k, v) =>
      AggregateVM2.builder<ComponentVM, ComponentVM>()
        .name(pick(k, "name", v, "agg"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .component1(pick(k, "component1", v, childFactory))
        .component2(pick(k, "component2", v, childFactory)),
  },
  {
    builder: "AggregateVM3",
    keys: aggregateKeys(3),
    make: (k, v) =>
      AggregateVM3.builder<ComponentVM, ComponentVM, ComponentVM>()
        .name(pick(k, "name", v, "agg"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .component1(pick(k, "component1", v, childFactory))
        .component2(pick(k, "component2", v, childFactory))
        .component3(pick(k, "component3", v, childFactory)),
  },
  {
    builder: "AggregateVM4",
    keys: aggregateKeys(4),
    make: (k, v) =>
      AggregateVM4.builder<ComponentVM, ComponentVM, ComponentVM, ComponentVM>()
        .name(pick(k, "name", v, "agg"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .component1(pick(k, "component1", v, childFactory))
        .component2(pick(k, "component2", v, childFactory))
        .component3(pick(k, "component3", v, childFactory))
        .component4(pick(k, "component4", v, childFactory)),
  },
  {
    builder: "AggregateVM5",
    keys: aggregateKeys(5),
    make: (k, v) =>
      AggregateVM5.builder<
        ComponentVM,
        ComponentVM,
        ComponentVM,
        ComponentVM,
        ComponentVM
      >()
        .name(pick(k, "name", v, "agg"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .component1(pick(k, "component1", v, childFactory))
        .component2(pick(k, "component2", v, childFactory))
        .component3(pick(k, "component3", v, childFactory))
        .component4(pick(k, "component4", v, childFactory))
        .component5(pick(k, "component5", v, childFactory)),
  },
  {
    builder: "AggregateVM6",
    keys: aggregateKeys(6),
    make: (k, v) =>
      AggregateVM6.builder<
        ComponentVM,
        ComponentVM,
        ComponentVM,
        ComponentVM,
        ComponentVM,
        ComponentVM
      >()
        .name(pick(k, "name", v, "agg"))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .component1(pick(k, "component1", v, childFactory))
        .component2(pick(k, "component2", v, childFactory))
        .component3(pick(k, "component3", v, childFactory))
        .component4(pick(k, "component4", v, childFactory))
        .component5(pick(k, "component5", v, childFactory))
        .component6(pick(k, "component6", v, childFactory)),
  },
  {
    builder: "HierarchicalVMBuilder",
    keys: [
      ["childrenFactory", "childrenFactory"],
      ["hub", "services"],
      ["dispatcher", "services"],
      ["vmFactory", "vmFactory"],
    ],
    make: (k, v) =>
      new HierarchicalVMBuilder<string, TestNode>()
        .model("root")
        .childrenFactory(pick(k, "childrenFactory", v, () => []))
        .services(pick(k, "hub", v, hub), pick(k, "dispatcher", v, disp))
        .vmFactory(
          pick(k, "vmFactory", v, (ctx: TestContext) => new TestNode(ctx)),
        ),
  },
  {
    builder: "FormVM",
    keys: [["persister", "persister"]],
    make: (k, v) =>
      FormVM.builder<{ name: string }>()
        .initial({ name: "a" })
        .persister(pick(k, "persister", v, async () => {})),
  },
];

const absentValues: Array<[string, unknown]> = [
  ["undefined", undefined],
  ["null", null],
];

describe("required builder fields reject an absent value", () => {
  for (const row of rows) {
    for (const [label, absent] of absentValues) {
      for (const [key, missingField] of row.keys) {
        it(`${row.builder}: ${key} = ${label} reports missing ${missingField}`, () => {
          let caught: unknown;
          try {
            row.make(key, absent).build();
          } catch (e) {
            caught = e;
          }
          expect(caught).toBeInstanceOf(BuilderValidationError);
          expect((caught as BuilderValidationError).missingField).toBe(missingField);
        });
      }
    }
  }
});

describe("an undefined model stays legal", () => {
  it("builds ComponentVMOf<number | undefined> with model(undefined)", () => {
    const vm = ComponentVMOf.builder<number | undefined>()
      .name("m")
      .model(undefined)
      .services(hub, disp)
      .build();
    expect(vm.model).toBeUndefined();
  });
});
