/**
 * Attack round 2: throwing computeds, equalities and effects.
 *
 * Expectations used:
 * - a design goal: "Errors: define what a throwing computed or effect does ... consistent with VMx's rules (a throwing
 *   command predicate reads as false, spec 04 §2; hub observer isolation, HUB-007)".
 * - R16: "A throw on a direct read goes to the reader"; "Value-to-error and error-to-value transitions are
 *   changes; error-to-error is not" (R6.5 as written before fix round 2).
 * - Consistency (inference): a reactive reader and a direct reader of the same computed see the same outcome.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

function quietly<T>(fn: () => T): T {
  configureReactiveDiagnostics({ development: false });
  try {
    return fn();
  } finally {
    configureReactiveDiagnostics({ development: undefined });
  }
}

function hubNames(s: Services): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage) names.push(`${m.senderName}.${m.propertyName}`);
  });
  return names;
}

class Parser extends ComponentVM {
  declare text: string;
  declare shownError: string;
  constructor(s: Services, name = "parser") {
    super(base(s, name));
    this.observable({ text: "1", shownError: "" });
    this.computed("value");
    this.effect(() => {
      try {
        void this.value;
        this.shownError = "";
      } catch (error) {
        this.shownError = (error as Error).message;
      }
    });
  }
  get value(): number {
    const n = Number(this.text);
    if (Number.isNaN(n)) throw new Error(`not a number: ${this.text}`);
    return n;
  }
}

describe("attack-r2 errors", () => {
  it("EE1 when a computed's error changes, an effect that shows the error sees the new error, as a direct read does", async () => {
    await streamFed();
    const s = services();
    quietly(() => {
      const vm = new Parser(s);
      vm.construct();
      vm.text = "a";
      assert.equal(vm.shownError, "not a number: a");
      vm.text = "b";
      assert.throws(() => vm.value, /not a number: b/, "a direct read sees the new error");
      assert.equal(vm.shownError, "not a number: b", "the effect still shows the first error");
    });
    await streamFed();
  });

  it("EE2 when a computed's error changes, hub observers are told (as for any change a reader can see)", async () => {
    await streamFed();
    const s = services();
    quietly(() => {
      const vm = new Parser(s, "announced");
      vm.construct();
      vm.text = "a";
      const names = hubNames(s);
      vm.text = "b";
      assert.ok(names.includes("announced.value"), `announced: ${names.join(", ")}`);
    });
    await streamFed();
  });

  // Fix round 2 (R6.10): an equality runs in its own context; a throw counts as "not equal" and is
  // reported on the stream-fed route. The scenario and the announcements are unchanged; the expectation of the
  // stream-fed route moved from the documented gap (nothing) to the resolved rule (one report per throw).
  it("EE3 a throwing equality counts as 'not equal': every equal write is accepted and announced, and each throw is reported", async () => {
    await streamFed();
    const s = services();
    class Faulty extends ComponentVM {
      declare level: number;
      constructor() {
        super(base(s, "faulty"));
        this.observable(
          { level: 1 },
          {
            level: (): boolean => {
              throw new Error("equality failed");
            },
          },
        );
      }
    }
    const vm = new Faulty();
    activate(vm);
    const names = hubNames(s);
    vm.level = 1;
    vm.level = 1;
    assert.deepEqual(names, ["faulty.level", "faulty.level"]);
    assert.deepEqual(
      (await streamFed()).map(String),
      ["Error: equality failed", "Error: equality failed"],
      "each throw of the equality is reported once",
    );
  });

  // Spec gap: an effect's first run is part of the construct (R12.1, LIFE-014), so a computed that is in error at
  // construct fails the whole construct unless every reader catches.
  it("EE4 GAP: an effect that reads a computed in error at construct fails the construct", () => {
    const s = services();
    class Form extends ComponentVM {
      declare text: string;
      constructor() {
        super(base(s, "form"));
        this.observable({ text: "" });
        this.computed("parsed");
        this.effect(() => {
          void this.parsed;
        });
      }
      get parsed(): number {
        if (this.text === "") throw new Error("empty");
        return Number(this.text);
      }
    }
    const vm = new Form();
    assert.throws(() => vm.construct(), /empty/);
    assert.equal(vm.status, ConstructionStatus.Destructed);
  });

  it("EE5 a predicate over a computed in error reads as false and is raised when the computed recovers (expected to hold)", async () => {
    await streamFed();
    const s = services();
    class Saver extends ComponentVM {
      declare text: string;
      readonly save = this.relayCommand(
        () => undefined,
        () => this.parsed > 0,
      );
      constructor() {
        super(base(s, "saver"));
        this.observable({ text: "x" });
        this.computed("parsed");
      }
      get parsed(): number {
        const n = Number(this.text);
        if (Number.isNaN(n)) throw new Error("bad");
        return n;
      }
    }
    quietly(() => {
      const vm = new Saver();
      activate(vm);
      let raises = 0;
      vm.save.canExecuteChanged.subscribe(() => {
        raises += 1;
      });
      assert.equal(vm.save.canExecute(), false);
      vm.text = "5";
      assert.equal(raises, 1);
      assert.equal(vm.save.canExecute(), true);
    });
    await streamFed();
  });
});
