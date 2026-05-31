// @vitest-environment jsdom
/**
 * Browser-build smoke test (D1).
 *
 * Loads the vmx public surface inside a JSDOM environment to prove that:
 *
 *   1. The module imports cleanly with no runtime resolution of Node
 *      built-ins (node:fs / node:path / node:url) — those would crash a
 *      browser bundler at module-load time.
 *   2. The lifecycle-transitions fixture is bundled into the module (via
 *      the static JSON import in transitionValidator.ts) and reachable
 *      without filesystem access.
 *   3. Core VM construction works end-to-end (ComponentVMOf builder,
 *      construct/dispose lifecycle) using only browser-safe code paths.
 *
 * If this test ever needs to fall back to fs-based fixture loading, the
 * imports below will throw inside JSDOM (no fs/path/url in window globals
 * is fine, but our SOURCE module must not even try to import them).
 *
 * Future regressions in this area (e.g. someone re-introducing a top-level
 * `node:fs` import to read a fixture at runtime) will surface here.
 */
import { describe, expect, it } from "vitest";

import {
  ComponentVMOf,
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  isLegal,
  finalState,
} from "../../src/index.js";

interface DemoModel {
  title: string;
}

describe("browser-build smoke (JSDOM)", () => {
  it("runs inside a JSDOM environment (window is defined)", () => {
    expect(typeof window).toBe("object");
    expect(typeof document).toBe("object");
  });

  it("loads the lifecycle fixture without any filesystem access", () => {
    // If transitionValidator.ts still imported node:fs/path/url, this would
    // have crashed at module-load. Reaching this assertion proves the fixture
    // was bundled in.
    expect(isLegal(ConstructionStatus.Destructed, "construct")).toBe(true);
    expect(finalState(ConstructionStatus.Destructed, "construct")).toBe(
      ConstructionStatus.Constructed,
    );
    expect(isLegal(ConstructionStatus.Disposed, "construct")).toBe(false);
  });

  it("constructs and disposes a ComponentVMOf without runtime errors", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();

    const vm = ComponentVMOf.builder<DemoModel>()
      .name("demo")
      .model({ title: "hello" })
      .services(hub, dispatcher)
      .build();

    expect(vm.status).toBe(ConstructionStatus.Destructed);
    vm.construct();
    expect(vm.status).toBe(ConstructionStatus.Constructed);
    expect(vm.model.title).toBe("hello");

    vm.dispose();
    expect(vm.status).toBe(ConstructionStatus.Disposed);
    hub.dispose();
  });
});
