/**
 * ReactDialogService — Phase 5.c implementation tests.
 *
 * Verifies the public IDialogService contract (parity with Phase 5.a Avalonia
 * and Phase 5.b Textual implementations) and the internal `current`
 * BehaviorSubject the `DialogOverlay` consumes.
 */
import { describe, expect, it } from "vitest";

import {
  type DialogRequest,
  ReactDialogService,
} from "../../../src/views/adapter/ReactDialogService.js";

function captureRequest(svc: ReactDialogService): DialogRequest {
  const r = svc.currentValue;
  if (r === null) throw new Error("expected a current request");
  return r;
}

describe("ReactDialogService", () => {
  it("starts with no current request", () => {
    const svc = new ReactDialogService();
    expect(svc.currentValue).toBeNull();
  });

  it("confirm() publishes a confirm request and resolves with the user choice", async () => {
    const svc = new ReactDialogService();
    const promise = svc.confirm("Delete x?", "Confirm");
    const req = captureRequest(svc);
    expect(req.kind).toBe("confirm");
    expect(req.message).toBe("Delete x?");
    expect(req.title).toBe("Confirm");

    req.resolveBool(true);
    await expect(promise).resolves.toBe(true);
    expect(svc.currentValue).toBeNull();
  });

  it("confirm() with false resolves false and clears overlay", async () => {
    const svc = new ReactDialogService();
    const promise = svc.confirm("Delete?");
    captureRequest(svc).resolveBool(false);
    await expect(promise).resolves.toBe(false);
    expect(svc.currentValue).toBeNull();
  });

  it("pickFileToSave() publishes a saveFile request with the suggested name", async () => {
    const svc = new ReactDialogService();
    const promise = svc.pickFileToSave(null, "Export", "out.json");
    const req = captureRequest(svc);
    expect(req.kind).toBe("saveFile");
    expect(req.suggestedName).toBe("out.json");

    req.resolveString("/tmp/out.json");
    await expect(promise).resolves.toBe("/tmp/out.json");
    expect(svc.currentValue).toBeNull();
  });

  it("pickFileToSave() with null resolves null", async () => {
    const svc = new ReactDialogService();
    const promise = svc.pickFileToSave();
    captureRequest(svc).resolveString(null);
    await expect(promise).resolves.toBeNull();
  });

  it("pickFileToOpen() publishes an openFile request", async () => {
    const svc = new ReactDialogService();
    const promise = svc.pickFileToOpen(null, "Open");
    const req = captureRequest(svc);
    expect(req.kind).toBe("openFile");
    req.resolveString("/tmp/in.json");
    await expect(promise).resolves.toBe("/tmp/in.json");
  });

  it("notify() publishes a notify request and resolves on user dismiss", async () => {
    const svc = new ReactDialogService();
    const promise = svc.notify("Hello", "Info", "info");
    const req = captureRequest(svc);
    expect(req.kind).toBe("notify");
    expect(req.severity).toBe("info");
    req.resolveVoid();
    await expect(promise).resolves.toBeUndefined();
    expect(svc.currentValue).toBeNull();
  });

  it("current observable emits on every request and after close()", () => {
    const svc = new ReactDialogService();
    const events: (DialogRequest | null)[] = [];
    const sub = svc.current.subscribe((r) => events.push(r));

    void svc.confirm("first");
    void svc.confirm("second"); // overwrites the prior unfinished request
    svc.close();

    expect(events.length).toBeGreaterThanOrEqual(4);
    expect(events[0]).toBeNull(); // initial seed
    expect(events[events.length - 1]).toBeNull();
    sub.unsubscribe();
  });
});
