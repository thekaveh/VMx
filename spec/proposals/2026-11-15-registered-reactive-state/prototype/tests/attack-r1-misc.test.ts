/**
 * Attack round 1: other places where the design's text was silent or ambiguous.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, PropertyChangedMessage, whenPropertyChanged } from "@thekaveh/vmx";
import { activate } from "../src/index.js";
import { base, captureReports, type Services, services, tick } from "./support.js";

function hubNames(s: Services): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage) names.push(`${m.senderName}.${m.propertyName}`);
  });
  return names;
}

describe("attack-r1 misc", () => {
  it("X2 a failed activation (a shadowed name) fails every construct, not only the first", () => {
    const s = services();
    class Base extends ComponentVM {
      declare x: number;
      constructor() {
        super(base(s, "shadow"));
        this.observable({ x: 0 });
      }
    }
    class Sub extends Base {
      override x = 5;
    }
    const vm = new Sub();
    assert.throws(() => vm.construct(), /shadowed by a class field/);
    assert.equal(vm.status, ConstructionStatus.Destructed);
    assert.throws(() => vm.construct(), /shadowed by a class field/, "the second construct succeeded silently");
  });

  // Fix round 1 (R4.5, R19.7): the design keeps deferred activation (R4.5, the base-constructor hazard), so a VM
  // observed only through the hub is activated by its host, as R4.5 prescribes.
  // The test adds that one call; X6b pins the development report that makes the omission loud.
  class Settings extends ComponentVM {
    declare unit: string;
    constructor(s: Services) {
      super(base(s, "settings"));
      this.observable({ unit: "s" });
      this.computed("unitLabel");
    }
    get unitLabel(): string {
      return this.unit === "s" ? "seconds" : "milliseconds";
    }
  }

  it("X6 a VM that is never constructed and is observed only through the hub publishes its computed once activated", () => {
    const s = services();
    const settings = new Settings(s); // a store-like VM: never constructed, never locally subscribed
    activate(settings); // R4.5: the host of a hub-only VM activates it
    const seen: string[] = [];
    whenPropertyChanged(s.hub, settings, "unitLabel").subscribe(() => seen.push(settings.unitLabel));
    settings.unit = "ms";
    assert.equal(settings.status, ConstructionStatus.Destructed);
    assert.deepEqual(seen, ["milliseconds"], "the hub listener never heard unitLabel change");
  });

  it("X6b without activation, development reports the unannounced computeds once per class (R19.7)", async () => {
    const reports = captureReports();
    const s = services();
    const settings = new Settings(s);
    const seen: string[] = [];
    whenPropertyChanged(s.hub, settings, "unitLabel").subscribe(() => seen.push(settings.unitLabel));
    settings.unit = "ms";
    settings.unit = "s";
    assert.deepEqual(seen, [], "R4.5: a VM that is not activated does not announce its computeds");
    assert.deepEqual(reports, [], "the report waits one task: a construct in the same task activates first");
    await tick();
    assert.deepEqual(reports, [
      "Settings: registered state changed while the view-model was not activated, so its computeds (unitLabel) " +
        "were not announced; construct, bind, own or contain it, or call activate()",
    ]);
    class OtherSettings extends Settings {}
    const constructed = new OtherSettings(s);
    constructed.unit = "ms";
    constructed.construct();
    await tick();
    assert.equal(reports.length, 1, "a VM activated in the same task is not reported");
  });

  it("X3 hub.batch around a throwing change scope: both channels deliver, then the body error surfaces (expected to hold)", () => {
    const s = services();
    class One extends ComponentVM {
      declare a: number;
      constructor() {
        super(base(s, "one"));
        this.observable({ a: 0 });
      }
    }
    const vm = new One();
    const local: string[] = [];
    vm.propertyChanged.subscribe((name) => local.push(name));
    const names = hubNames(s);
    assert.throws(
      () =>
        s.hub.batch(() =>
          vm.change(() => {
            vm.a = 1;
            throw new Error("body");
          }),
        ),
      /body/,
    );
    assert.deepEqual(local, ["a"]);
    assert.deepEqual(names, ["one.a"]);
  });

  it("X4 reconstruct() tears whileConstructed down once and sets it up once (expected to hold)", () => {
    const s = services();
    const log: string[] = [];
    class Host extends ComponentVM {
      constructor() {
        super(base(s, "host"));
        this.whileConstructed(() => {
          log.push("setup");
          return () => log.push("teardown");
        });
      }
    }
    const vm = new Host();
    vm.construct();
    vm.reconstruct();
    assert.deepEqual(log, ["setup", "teardown", "setup"]);
  });

  it("X5 GAP: an effect registered while Constructed whose first run throws: the registration call throws, the effect stays live", () => {
    const s = services();
    const runs: number[] = [];
    class Host extends ComponentVM {
      declare n: number;
      constructor() {
        super(base(s, "host"));
        this.observable({ n: 0 });
      }
    }
    const vm = new Host();
    vm.construct();
    assert.throws(
      () =>
        vm.effect(() => {
          runs.push(vm.n);
          if (vm.n === 0) throw new Error("first run");
        }),
      /first run/,
    );
    vm.n = 1;
    // Normative since fix round 1 (R16, X5): propagate, stay registered with the reads it made.
    assert.deepEqual(runs, [0, 1]);
  });
});
