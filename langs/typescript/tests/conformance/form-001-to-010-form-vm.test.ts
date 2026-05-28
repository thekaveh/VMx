// Conformance stubs: FORM-001..FORM-010 — FormVM<TM> (snapshot/revert edit lifecycle).
// See spec/20-form-vm.md and ADR-0030. Substage 3A (spec foundation).

import { describe, it } from "vitest";

describe("FORM-001", () => {
  it.todo("Snapshot captured at construct; Model == Snapshot; IsDirty == false");
});

describe("FORM-002", () => {
  it.todo("Model mutation reflected in IsDirty; Snapshot unchanged");
});

describe("FORM-003", () => {
  it.todo("IsDirty derivation via structural inequality");
});

describe("FORM-004", () => {
  it.todo("DenyCommand reverts Model to Snapshot; IsDirty == false after revert");
});

describe("FORM-005", () => {
  it.todo("ApproveCommand invokes persister; Snapshot advances on success");
});

describe("FORM-006", () => {
  it.todo("OnApproved fires only after successful persist; not when persister throws");
});

describe("FORM-007", () => {
  it.todo("Persist failure leaves Snapshot and Model unchanged; exception propagates");
});

describe("FORM-008", () => {
  it.todo("DenyCommand publishes FormRevertedMessage and PropertyChangedMessage('Model') on hub");
});

describe("FORM-009", () => {
  it.todo("Strict mode: ApproveCommand.CanExecute is false when IsDirty == false");
});

describe("FORM-010", () => {
  it.todo("Integration with IDialogService.Confirm — confirm guard prevents revert on false return");
});
