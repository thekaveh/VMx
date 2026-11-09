/**
 * A container whose disposal is requested during a change sends no hub
 * message for it (spec ch. 01 §1.4, ch. 06 §4/§4.2/§4.3, ch. 07 §1,
 * ADR-0190).
 */
import { describe, expect, it } from "vitest";
import {
  CollectionChangedMessage,
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  ConstructionStatus,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { CollectionChangedEvent } from "../../src/index.js";

const dispatcher = RxDispatcher.immediate();

function child(hub: MessageHub, name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).build();
}

function composite(hub: MessageHub, name: string) {
  return CompositeVM.builder<ComponentVMBase>()
    .name(name).services(hub, dispatcher).children(() => []).build();
}

function group(hub: MessageHub, name: string) {
  return GroupVM.builder<ComponentVMBase>()
    .name(name).services(hub, dispatcher).children(() => []).build();
}

/** Hub `CollectionChangedMessage`s as `sender:action` strings. */
function hubLog(hub: MessageHub): string[] {
  const log: string[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof CollectionChangedMessage) {
      log.push(`${(message.sender as ComponentVMBase).name}:${message.action}`);
    }
  });
  return log;
}

interface Container {
  readonly status: ConstructionStatus;
  readonly collectionChanged: { subscribe(next: (event: CollectionChangedEvent) => void): unknown };
  add(item: ComponentVMBase): void;
  move(fromIndex: number, toIndex: number): void;
  dispose(): void;
}

const containers: Array<[string, (hub: MessageHub, name: string) => Container]> = [
  ["CompositeVM", composite],
  ["GroupVM", group],
];

describe("COMP-049", () => {
  it("sends only the new composite's Add when the old one disposes itself in a transfer", () => {
    const hub = new MessageHub();
    const x = child(hub, "x");
    let oldParent: CompositeVM<ComponentVMBase> | null = null;
    const built = CompositeVM.builder<ComponentVMBase>()
      .name("old").services(hub, dispatcher).children(() => [])
      .onCurrentChanged((value) => {
        if (value === null) oldParent?.dispose();
      })
      .build();
    oldParent = built;
    const newParent = composite(hub, "new");
    built.add(x);
    built.current = x;
    const oldLocal: string[] = [];
    built.collectionChanged.subscribe((event) => oldLocal.push(event.action));
    const messages = hubLog(hub);

    newParent.add(x);

    expect(messages).toEqual(["new:add"]);
    expect(built.status).toBe(ConstructionStatus.Disposed);
    expect(oldLocal).toEqual(["remove"]);
  });

  for (const [kind, make] of containers) {
    it(`${kind}: an Add whose local subscriber disposes the container sends no hub message`, () => {
      const hub = new MessageHub();
      const p = make(hub, "p");
      const local: string[] = [];
      p.collectionChanged.subscribe((event) => {
        local.push(event.action);
        p.dispose();
      });
      const messages = hubLog(hub);

      p.add(child(hub, "c"));

      expect(local).toEqual(["add"]);
      expect(messages).toEqual([]);
      expect(p.status).toBe(ConstructionStatus.Disposed);
    });

    it(`${kind}: a Move whose local subscriber disposes the container sends no hub message`, () => {
      const hub = new MessageHub();
      const p = make(hub, "p");
      p.add(child(hub, "a"));
      p.add(child(hub, "b"));
      const local: string[] = [];
      p.collectionChanged.subscribe((event) => {
        local.push(event.action);
        p.dispose();
      });
      const messages = hubLog(hub);

      p.move(0, 1);

      expect(local).toEqual(["move"]);
      expect(messages).toEqual([]);
      expect(p.status).toBe(ConstructionStatus.Disposed);
    });
  }
});
