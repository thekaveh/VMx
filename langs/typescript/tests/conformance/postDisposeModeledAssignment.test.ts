import { describe, expect, it, vi } from "vitest";
import {
  ComponentVMOf,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "../../src/index.js";

interface ComponentModel {
  value: number;
}

interface FormModel {
  name: string;
}

describe("DISP-014", () => {
  it("makes modeled component and form assignment inert after disposal", () => {
    const componentHub = new MessageHub();
    const hinter = vi.fn((model: ComponentModel) => `hint:${model.value}`);
    const onModelChanged = vi.fn((_model: ComponentModel) => {});
    const initial: ComponentModel = { value: 1 };
    const replacement: ComponentModel = { value: 2 };
    const component = ComponentVMOf.builder<ComponentModel>()
      .name("component")
      .model(initial)
      .modeledHinter(hinter)
      .onModelChanged(onModelChanged)
      .services(componentHub, RxDispatcher.immediate())
      .build();
    const localChanges: string[] = [];
    const componentHubChanges: PropertyChangedMessage<unknown>[] = [];
    component.propertyChanged.subscribe((name) => localChanges.push(name));
    componentHub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) componentHubChanges.push(message);
    });

    component.dispose();
    hinter.mockClear();
    onModelChanged.mockClear();
    localChanges.length = 0;
    componentHubChanges.length = 0;
    const lateComponentCompletion = (): void => { component.model = replacement; };

    lateComponentCompletion();

    expect(component.model).toBe(initial);
    expect(component.modeledHint).toBe("hint:1");
    expect(hinter).not.toHaveBeenCalled();
    expect(onModelChanged).not.toHaveBeenCalled();
    expect(localChanges).toEqual([]);
    expect(componentHubChanges).toEqual([]);

    const formHub = new MessageHub();
    const equals = vi.fn((left: FormModel, right: FormModel) => left.name === right.name);
    const validator = vi.fn((model: FormModel) => model.name === "" ? "required" : null);
    const form = new FormVM<FormModel>({
      initial: { name: "valid" },
      persister: async () => {},
      hub: formHub,
      strict: true,
      equals,
      validators: { name: validator },
    });
    const initialFormModel = form.model;
    const initialSnapshot = form.snapshot;
    const initialErrors = form.errors;
    const initialDirty = form.isDirty;
    const initialValid = form.isValid;
    const errorsSignals: Array<Record<string, string>> = [];
    const commandSignals: void[] = [];
    const formHubChanges: unknown[] = [];
    form.errorsChanged.subscribe((errors) => errorsSignals.push(errors));
    form.approveCommand.canExecuteChanged.subscribe(() => commandSignals.push());
    formHub.messages.subscribe((message) => formHubChanges.push(message));

    form.dispose();
    equals.mockClear();
    validator.mockClear();
    errorsSignals.length = 0;
    commandSignals.length = 0;
    formHubChanges.length = 0;
    const lateFormCompletion = (): void => form.setModel({ name: "" });

    lateFormCompletion();

    expect(form.model).toBe(initialFormModel);
    expect(form.snapshot).toBe(initialSnapshot);
    expect(form.errors).toEqual(initialErrors);
    expect(equals).not.toHaveBeenCalled();
    expect(validator).not.toHaveBeenCalled();
    expect(errorsSignals).toEqual([]);
    expect(commandSignals).toEqual([]);
    expect(formHubChanges).toEqual([]);
    expect(form.isDirty).toBe(initialDirty);
    expect(form.isValid).toBe(initialValid);
  });
});
