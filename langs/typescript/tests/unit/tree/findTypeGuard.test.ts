/**
 * Type-level and run-time checks for the type-guard overload of `find`
 * (spec/13-tree-utilities.md, UTIL-003). A type-guard predicate narrows the
 * result without a cast; the run-time result is the same node that a boolean
 * predicate returns.
 */
import { describe, expect, it } from "vitest";
import {
  CompositeVM,
  ComponentVM,
  ComponentVMBase,
  MessageHub,
  RxDispatcher,
  ViewModelType,
  find,
  type IDispatcher,
  type IMessageHub,
} from "../../../src/index.js";

class RouteVM extends ComponentVMBase {
  readonly route: string;

  constructor(hub: IMessageHub, dispatcher: IDispatcher, route: string) {
    super({ name: route, hub, dispatcher });
    this.route = route;
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

function isRoute(vm: ComponentVMBase): vm is RouteVM {
  return vm instanceof RouteVM;
}

function buildTree() {
  const hub = new MessageHub();
  const disp = RxDispatcher.immediate();
  const other = ComponentVM.builder().name("other").services(hub, disp).build();
  const leaf = new RouteVM(hub, disp, "leaf");
  const root = CompositeVM.builder<ComponentVMBase>()
    .name("root")
    .services(hub, disp)
    .children(() => [other, leaf])
    .build();
  root.construct();
  return { root, leaf };
}

describe("find with a type-guard predicate", () => {
  it("narrows the result to the guarded type without a cast", () => {
    const { root } = buildTree();

    const found = find(root, isRoute);

    expect(found?.route).toBe("leaf");
  });

  it("keeps the base return type for a boolean predicate", () => {
    const { root, leaf } = buildTree();

    const plain = find(root, (vm) => vm.name === "leaf");

    expect(plain).toBe(leaf);
    // @ts-expect-error A boolean predicate keeps the base return type, so `route` is not visible.
    expect(plain?.route).toBe("leaf");
  });

  it("returns the same node at run time as a boolean predicate", () => {
    const { root, leaf } = buildTree();

    expect(find(root, isRoute)).toBe(leaf);
    expect(find(root, isRoute)).toBe(find(root, (vm) => vm.name === "leaf"));
  });
});
