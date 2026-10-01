/**
 * Executable form of the imperative-engine bridge in
 * docs/content/integration/index.md. The docs-snippet regions are shown there
 * verbatim, dedented, and `make docs-check` keeps them equal. No conformance ID
 * (integration recipe).
 */
import { describe, expect, it } from "vitest";
import { ComponentVMOf, MessageHub, RxDispatcher, subscribeValue } from "../../src/index.js";

interface Camera {
  exposure: number;
}

describe("imperative engine bridge recipe", () => {
  it("sets the uniform at once, follows changes, and stops after unsubscribe", () => {
    const hub = new MessageHub();
    const cameraVm = ComponentVMOf.builder<Camera>()
      .name("camera")
      .model({ exposure: 1 })
      .services(hub, RxDispatcher.immediate())
      .build();
    const material = { uniforms: { exposure: { value: 0 } } };

    // docs-snippet:start imperative-bridge
    const exposureSubscription = subscribeValue(
      cameraVm,
      vm => vm.model.exposure,
      exposure => { material.uniforms.exposure.value = exposure; },
      { fireImmediately: true },
    );
    // docs-snippet:end imperative-bridge
    expect(material.uniforms.exposure.value).toBe(1);

    cameraVm.model = { exposure: 2 };
    expect(material.uniforms.exposure.value).toBe(2);

    // docs-snippet:start imperative-bridge-dispose
    exposureSubscription.unsubscribe();
    // docs-snippet:end imperative-bridge-dispose
    cameraVm.model = { exposure: 3 };
    expect(material.uniforms.exposure.value).toBe(2);
  });
});
