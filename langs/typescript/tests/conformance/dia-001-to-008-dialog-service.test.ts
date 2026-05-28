// Conformance stubs: DIA-001..DIA-008 — IDialogService (host modal interactions).
// See spec/19-dialogs.md and ADR-0029. Substage 3A (spec foundation).

import { describe, it } from "vitest";

describe("DIA-001", () => {
  it.todo("PickFileToOpen contract — optional filter/title; returns path or null on cancel");
});

describe("DIA-002", () => {
  it.todo("PickFileToSave contract — optional filter/title/suggestedName; returns path or null");
});

describe("DIA-003", () => {
  it.todo("Confirm contract — message + optional title; returns bool (false on cancel)");
});

describe("DIA-004", () => {
  it.todo("Notify contract — message/title/severity (Info/Warning/Error); completes without error");
});

describe("DIA-005", () => {
  it.todo("NullDialogService: PickFile* returns null; Confirm returns false; Notify is no-op");
});

describe("DIA-006", () => {
  it.todo("Reentrancy is implementation-defined; both queueing and rejecting impls conform");
});

describe("DIA-007", () => {
  it.todo("Cancellation completes awaitable with safe default (null/false), does not throw");
});

describe("DIA-008", () => {
  it.todo("ConfirmationDecoratorCommand with dialogService.Confirm constructs valid command graph");
});
