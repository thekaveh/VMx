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

  it("queues concurrent requests in FIFO order and settles both promises", async () => {
    const svc = new ReactDialogService();
    const events: (DialogRequest | null)[] = [];
    const sub = svc.current.subscribe((r) => events.push(r));

    const first = svc.confirm("first");
    const firstRequest = captureRequest(svc);
    const second = svc.confirm("second", "Second confirmation");

    expect(captureRequest(svc)).toBe(firstRequest);
    firstRequest.resolveBool(true);
    await expect(first).resolves.toBe(true);

    const secondRequest = captureRequest(svc);
    expect(secondRequest.kind).toBe("confirm");
    expect(secondRequest.title).toBe("Second confirmation");
    firstRequest.resolveBool(false); // a stale callback cannot close the next dialog
    expect(captureRequest(svc)).toBe(secondRequest);
    secondRequest.resolveBool(false);
    await expect(second).resolves.toBe(false);

    expect(events.length).toBeGreaterThanOrEqual(4);
    expect(events[0]).toBeNull(); // initial seed
    expect(events[events.length - 1]).toBeNull();
    sub.unsubscribe();
  });

  it("close() safely cancels the active request and advances the queue", async () => {
    const svc = new ReactDialogService();
    const first = svc.confirm("first");
    const second = svc.pickFileToOpen(null, "second");

    svc.close();
    await expect(first).resolves.toBe(false);
    expect(captureRequest(svc).title).toBe("second");

    svc.close();
    await expect(second).resolves.toBeNull();
    expect(svc.currentValue).toBeNull();
  });

  it("settles the active promise before a promoted request can complete", async () => {
    const svc = new ReactDialogService();
    const settled: string[] = [];
    const first = svc.confirm("first").then(() => settled.push("first"));
    const firstRequest = captureRequest(svc);
    const second = svc.confirm("second").then(() => settled.push("second"));
    const sub = svc.current.subscribe((request) => {
      if (request?.message === "second") request.resolveBool(true);
    });

    firstRequest.resolveBool(true);
    await Promise.all([first, second]);

    expect(settled).toEqual(["first", "second"]);
    sub.unsubscribe();
  });
});
