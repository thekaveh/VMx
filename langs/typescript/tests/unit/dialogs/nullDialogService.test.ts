// Unit tests for NullDialogService.
// Each test covers one independently verifiable behavioural requirement.

import { describe, expect, it } from "vitest";

import type { IDialogService, NotificationSeverity } from "../../../src/index.js";
import { NullDialogService } from "../../../src/index.js";
import type { FileFilter } from "../../../src/dialogs/dialogService.js";

// ---------------------------------------------------------------------------
// Construction / type identity
// ---------------------------------------------------------------------------

describe("NullDialogService — construction", () => {
  it("implements IDialogService", () => {
    const sut: IDialogService = new NullDialogService();
    expect(sut).toBeDefined();
  });

  it("INSTANCE singleton is not null", () => {
    expect(NullDialogService.INSTANCE).toBeDefined();
    expect(NullDialogService.INSTANCE).not.toBeNull();
  });

  it("INSTANCE is an IDialogService", () => {
    const sut: IDialogService = NullDialogService.INSTANCE;
    expect(sut).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// pickFileToOpen
// ---------------------------------------------------------------------------

describe("NullDialogService.pickFileToOpen", () => {
  it("returns null with no args", async () => {
    const sut = new NullDialogService();
    expect(await sut.pickFileToOpen()).toBeNull();
  });

  it("returns null with filter", async () => {
    const sut = new NullDialogService();
    const filter: FileFilter = { description: "Images", extensions: ["*.png"] };
    expect(await sut.pickFileToOpen(filter)).toBeNull();
  });

  it("returns null with title", async () => {
    const sut = new NullDialogService();
    expect(await sut.pickFileToOpen(null, "Choose file")).toBeNull();
  });

  it("returns null with null filter", async () => {
    const sut = new NullDialogService();
    expect(await sut.pickFileToOpen(null)).toBeNull();
  });

  it("returns null on multiple successive calls", async () => {
    const sut = new NullDialogService();
    for (let i = 0; i < 3; i++) {
      expect(await sut.pickFileToOpen()).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// pickFileToSave
// ---------------------------------------------------------------------------

describe("NullDialogService.pickFileToSave", () => {
  it("returns null with no args", async () => {
    const sut = new NullDialogService();
    expect(await sut.pickFileToSave()).toBeNull();
  });

  it("returns null with all args", async () => {
    const sut = new NullDialogService();
    const filter: FileFilter = { description: "Text", extensions: ["*.txt"] };
    expect(await sut.pickFileToSave(filter, "Save as", "output.txt")).toBeNull();
  });

  it("returns null with null filter", async () => {
    const sut = new NullDialogService();
    expect(await sut.pickFileToSave(null)).toBeNull();
  });

  it("returns null on multiple successive calls", async () => {
    const sut = new NullDialogService();
    for (let i = 0; i < 3; i++) {
      expect(await sut.pickFileToSave()).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// confirm
// ---------------------------------------------------------------------------

describe("NullDialogService.confirm", () => {
  it("returns false (safest default)", async () => {
    const sut = new NullDialogService();
    expect(await sut.confirm("Delete?")).toBe(false);
  });

  it("returns false with title", async () => {
    const sut = new NullDialogService();
    expect(await sut.confirm("Overwrite?", "Confirm")).toBe(false);
  });

  it("returns false with null title", async () => {
    const sut = new NullDialogService();
    expect(await sut.confirm("msg", null)).toBe(false);
  });

  it("returns false on multiple successive calls", async () => {
    const sut = new NullDialogService();
    for (let i = 0; i < 3; i++) {
      expect(await sut.confirm(`message ${i}`)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// notify
// ---------------------------------------------------------------------------

describe("NullDialogService.notify", () => {
  it("resolves without error (default severity)", async () => {
    const sut = new NullDialogService();
    await expect(sut.notify("Hello")).resolves.toBeUndefined();
  });

  it("resolves for info severity", async () => {
    const sut = new NullDialogService();
    await expect(sut.notify("Info", null, "info")).resolves.toBeUndefined();
  });

  it("resolves for warning severity", async () => {
    const sut = new NullDialogService();
    await expect(sut.notify("Warn", null, "warning")).resolves.toBeUndefined();
  });

  it("resolves for error severity", async () => {
    const sut = new NullDialogService();
    await expect(sut.notify("Error", null, "error")).resolves.toBeUndefined();
  });

  it("resolves with null title", async () => {
    const sut = new NullDialogService();
    await expect(sut.notify("msg", null)).resolves.toBeUndefined();
  });

  it("resolves with title", async () => {
    const sut = new NullDialogService();
    await expect(sut.notify("msg", "My title")).resolves.toBeUndefined();
  });

  it("resolves on multiple successive calls", async () => {
    const sut = new NullDialogService();
    for (let i = 0; i < 3; i++) {
      await expect(sut.notify(`message ${i}`)).resolves.toBeUndefined();
    }
  });
});

// ---------------------------------------------------------------------------
// FileFilter type (structural)
// ---------------------------------------------------------------------------

describe("FileFilter interface", () => {
  it("accepts description and extensions", () => {
    const filter: FileFilter = { description: "Images", extensions: ["*.png", "*.jpg"] };
    expect(filter.description).toBe("Images");
    expect(filter.extensions).toEqual(["*.png", "*.jpg"]);
  });

  it("accepts empty extensions array", () => {
    const filter: FileFilter = { description: "All files", extensions: [] };
    expect(filter.extensions).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// NotificationSeverity type (structural)
// ---------------------------------------------------------------------------

describe("NotificationSeverity type", () => {
  it("accepts all three values", () => {
    const severities: NotificationSeverity[] = ["info", "warning", "error"];
    expect(severities).toHaveLength(3);
  });
});
