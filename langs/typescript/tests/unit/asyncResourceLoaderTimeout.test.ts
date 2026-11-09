import { describe, expect, it } from "vitest";
import {
  AsyncResourceStatus,
  AsyncResourceVM,
  MessageHub,
  NullDispatcher,
} from "../../src/index.js";

// ADR-0199: only an "AbortError" rejection is the loader's own cancellation.
// A timeout is a failure and installs Error.
describe("AsyncResourceVM loader timeout", () => {
  it("installs Error for a TimeoutError rejection", async () => {
    const timeout = new DOMException("timed out", "TimeoutError");
    const vm = new AsyncResourceVM<number>({
      name: "resource",
      hub: new MessageHub(),
      dispatcher: NullDispatcher.INSTANCE,
      loader: () => Promise.reject(timeout),
    });

    await vm.loadCommand.executeAsync();

    expect(vm.state).toEqual({ status: AsyncResourceStatus.Error, error: timeout });
    expect(vm.reloadCommand.canExecute()).toBe(true);
  });
});
