import { describe, expect, it } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
} from "../../src/index.js";

interface Model {
  readonly value: string;
}

const model = (value: string): Model => ({ value });

describe("FORM-030", () => {
  it("publishes one settled model message for each accepted unequal assignment", async () => {
    const trace: string[] = [];
    const hub = new MessageHub();
    const form = new FormVM<Model>({
      initial: model(""),
      persister: async () => {},
      hub,
      strict: true,
      snapshotter: (value) => value,
      validators: {
        value: (value) => {
          trace.push("validate");
          return value.value.length === 0 ? "required" : undefined;
        },
      },
    });
    trace.length = 0;

    const errorsSub = form.errorsChanged.subscribe(() => trace.push("errors"));
    const commandSub = form.approveCommand.canExecuteChanged.subscribe(() =>
      trace.push("can_execute"),
    );
    const observed: Array<[string, boolean, boolean]> = [];
    let reentered = false;
    const hubSub = hub.messages.subscribe((message) => {
      if (
        !(message instanceof PropertyChangedMessage) ||
        message.sender !== form ||
        message.propertyName !== "model"
      ) {
        return;
      }
      observed.push([
        form.model.value,
        form.isValid,
        form.approveCommand.canExecute(),
      ]);
      trace.push("model");
      if (!reentered) {
        reentered = true;
        form.setModel(model("nested"));
      }
    });

    form.setModel(model("outer"));

    expect(observed).toEqual([
      ["outer", true, true],
      ["nested", true, true],
    ]);
    expect(trace).toEqual([
      "validate",
      "errors",
      "can_execute",
      "model",
      "validate",
      "model",
    ]);

    const retained = form.model;
    const traceBeforeEqual = trace.length;
    form.setModel(model("nested"));
    expect(form.model).toBe(retained);
    expect(trace).toHaveLength(traceBeforeEqual);

    form.dispose();
    const traceAfterDispose = trace.length;
    form.setModel(model("late"));
    expect(form.model).toBe(retained);
    expect(trace).toHaveLength(traceAfterDispose);

    const nullHubForm = new FormVM<Model>({
      initial: model("initial"),
      persister: async () => {},
      snapshotter: (value) => value,
    });
    nullHubForm.setModel(model("changed"));
    expect(nullHubForm.model.value).toBe("changed");

    const denyHub = new MessageHub();
    const denyMessages: unknown[] = [];
    const denySub = denyHub.messages.subscribe((message) =>
      denyMessages.push(message),
    );
    const denyForm = new FormVM<Model>({
      initial: model("initial"),
      persister: async () => {},
      hub: denyHub,
      snapshotter: (value) => value,
    });
    denyForm.setModel(model("changed"));
    denyMessages.length = 0;
    denyForm.denyCommand.execute();
    expect(denyMessages).toHaveLength(2);
    expect(denyMessages[0]).toBeInstanceOf(FormRevertedMessage);
    expect(denyMessages[1]).toBeInstanceOf(PropertyChangedMessage);
    expect((denyMessages[1] as PropertyChangedMessage<object>).propertyName).toBe(
      "model",
    );

    const resetHub = new MessageHub();
    const resetMessages: unknown[] = [];
    const resetSub = resetHub.messages.subscribe((message) =>
      resetMessages.push(message),
    );
    const resetForm = new FormVM<Model>({
      initial: model("initial"),
      persister: async () => {},
      hub: resetHub,
      snapshotter: (value) => value,
      resetOnApproved: () => model("reset"),
    });
    resetForm.setModel(model("saved"));
    resetMessages.length = 0;

    await resetForm.approveAsync();

    expect(resetForm.model.value).toBe("reset");
    expect(
      resetMessages.filter(
        (message) =>
          message instanceof PropertyChangedMessage &&
          message.propertyName === "model",
      ),
    ).toHaveLength(0);

    errorsSub.unsubscribe();
    commandSub.unsubscribe();
    hubSub.unsubscribe();
    denySub.unsubscribe();
    resetSub.unsubscribe();
  });
});
