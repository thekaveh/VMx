/**
 * Selection rules for a disposed child, a destructing composite and the child
 * select()/deselect() paths (spec ch. 05 §6, ch. 06 §3, §3.1, §4.3 rules 2, 8
 * and 9, §5; ch. 02 §3 invariant 3; ADR-0188, ADR-0189).
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus as S,
  ConstructionStatusChangedMessage,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "../../src/index.js";

function child(hub: MessageHub, name: string, onDestruct?: () => void): ComponentVM {
  let builder = ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate());
  if (onDestruct !== undefined) builder = builder.onDestruct(onDestruct);
  return builder.build();
}

/** Records `<sender>.<property>` for each PropertyChangedMessage from `senders`. */
function recordProperties(hub: MessageHub, ...senders: object[]): string[] {
  const log: string[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof PropertyChangedMessage && senders.includes(message.sender as object)) {
      log.push(`${message.senderName}.${message.propertyName}`);
    }
  });
  return log;
}

describe("COMP-050", () => {
  it("disposing the current child clears Current once and leaves the child unselectable", () => {
    const hub = new MessageHub();
    const a = child(hub, "a");
    const b = child(hub, "b");
    const changes: (ComponentVM | null)[] = [];
    const p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, RxDispatcher.immediate())
      .children(() => [a, b])
      .onCurrentChanged((vm) => changes.push(vm))
      .build();
    p.construct();
    p.current = a;
    changes.length = 0;
    const log = recordProperties(hub, p, a);
    let disposedSeen = false;
    const afterDisposed: string[] = [];
    hub.messages.subscribe((message) => {
      if (message.sender !== a) return;
      if (message instanceof ConstructionStatusChangedMessage && message.status === S.Disposed) {
        disposedSeen = true;
      } else if (message instanceof PropertyChangedMessage && disposedSeen) {
        afterDisposed.push(message.propertyName);
      }
    });

    a.dispose();

    expect(p.current).toBeNull();
    expect(a.isCurrent).toBe(false);
    expect(log.filter((entry) => entry === "p.current")).toEqual(["p.current"]);
    expect(changes).toEqual([null]);
    expect(afterDisposed).not.toContain("isCurrent");
    expect(p.canSelectComponent(a)).toBe(false);
    expect(() => {
      p.current = a;
    }).toThrow(/not a member/);
    expect(p.current).toBeNull();
  });

  it("the composite's own dispose cascade does not clear Current", () => {
    const hub = new MessageHub();
    const a = child(hub, "a");
    const b = child(hub, "b");
    const p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, RxDispatcher.immediate())
      .children(() => [a, b])
      .build();
    p.construct();
    p.current = b;
    const log = recordProperties(hub, p);

    p.dispose();

    expect(b.status).toBe(S.Disposed);
    expect(log).not.toContain("p.current");
  });
});

describe("COMP-051", () => {
  function setup() {
    const hub = new MessageHub();
    const errors: unknown[] = [];
    const recorded: boolean[] = [];
    const changes: (ComponentVM | null)[] = [];
    const record = (action: () => void): void => {
      try {
        action();
      } catch (error) {
        errors.push(error);
      }
    };
    let p: CompositeVM<ComponentVM> | null = null;
    const a = child(hub, "a");
    const c = child(hub, "c");
    const b = child(hub, "b", () => {
      const parent = p as CompositeVM<ComponentVM>;
      record(() => {
        parent.current = c;
      });
      record(() => c.select());
      recorded.push(parent.canSelectComponent(c));
      record(() => {
        parent.current = a;
      });
      record(() => {
        parent.current = null;
      });
    });
    p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, RxDispatcher.immediate())
      .children(() => [a, b, c])
      .onCurrentChanged((vm) => {
        changes.push(vm);
        const parent = p as CompositeVM<ComponentVM>;
        if (vm === null && parent.status === S.Destructing) {
          record(() => {
            parent.current = b;
          });
          record(() => parent.selectComponent(b));
          record(() => b.select());
        }
      })
      .build();
    const composite = p;
    composite.construct();
    composite.current = a;
    const log = recordProperties(hub, composite);
    return { composite, a, b, c, errors, recorded, changes, log };
  }

  it("destruct() ignores selections made while the composite is Destructing", () => {
    const { composite, a, b, c, errors, recorded, changes, log } = setup();
    changes.length = 0;

    expect(() => composite.destruct()).not.toThrow();

    expect(errors).toEqual([]);
    expect(composite.status).toBe(S.Destructed);
    for (const vm of [a, b, c]) expect(vm.status).toBe(S.Destructed);
    expect(composite.current).toBeNull();
    expect(recorded).toEqual([false]);
    expect(log).toEqual(["p.current"]);
    expect(changes).toEqual([null]);
  });

  it("the destruct phase of reconstruct() follows the same rule", () => {
    const { composite, a, b, c, errors, recorded, changes, log } = setup();
    composite.destruct();
    composite.construct();
    composite.current = a;
    errors.length = 0;
    recorded.length = 0;
    changes.length = 0;
    log.length = 0;

    expect(() => composite.reconstruct()).not.toThrow();

    expect(errors).toEqual([]);
    expect(composite.status).toBe(S.Constructed);
    for (const vm of [a, b, c]) expect(vm.status).toBe(S.Constructed);
    expect(composite.current).toBeNull();
    expect(recorded).toEqual([false]);
    expect(log).toEqual(["p.current"]);
    expect(changes).toEqual([null]);
  });
});

describe("COMP-052", () => {
  it("a refused child select() or deselect() changes nothing and raises nothing", () => {
    const hub = new MessageHub();
    const a = child(hub, "a");
    const b = child(hub, "b");
    const c = child(hub, "c");
    let p: CompositeVM<ComponentVM> | null = null;
    const d = ComponentVM.builder()
      .name("d")
      .services(hub, RxDispatcher.immediate())
      .onConstruct(() => a.select())
      .build();
    p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, RxDispatcher.immediate())
      .children(() => [a, b, c])
      .autoConstructOnAdd(true)
      .onCurrentChanged((vm) => {
        if (vm === c) {
          (p as CompositeVM<ComponentVM>).dispose();
          a.select();
        }
      })
      .build();
    const composite = p;
    composite.construct();
    b.destruct();
    const currentMessages: unknown[] = [];
    hub.messages.subscribe((message) => {
      if (
        message instanceof PropertyChangedMessage &&
        message.sender === composite &&
        message.propertyName === "current"
      ) {
        currentMessages.push(composite.current);
      }
    });

    expect(() => b.select()).not.toThrow();
    expect(composite.current).toBeNull();
    expect(() => a.deselect()).not.toThrow();
    expect(composite.current).toBeNull();
    expect(() => composite.add(d)).not.toThrow();
    expect(d.status).toBe(S.Constructed);
    expect(composite.current).toBeNull();
    expect(currentMessages).toEqual([]);

    expect(() => {
      composite.current = c;
    }).not.toThrow();

    expect(currentMessages).toEqual([c]);
    expect(composite.current).toBe(c);
    expect(composite.status).toBe(S.Disposed);
  });
});
