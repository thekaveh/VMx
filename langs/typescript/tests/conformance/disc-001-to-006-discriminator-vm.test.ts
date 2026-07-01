import { describe, expect, it } from "vitest";
import { DiscriminatorVM } from "../../src/index.js";

describe("DISC-001", () => {
  it("initial active key and isActive", () => {
    const sut = new DiscriminatorVM("nav");
    expect(sut.activeKey).toBe("nav");
    expect(sut.isActive("nav")).toBe(true);
    expect(sut.isActive("modal")).toBe(false);
  });
});

describe("DISC-002", () => {
  it("setActiveKey emits change", () => {
    const sut = new DiscriminatorVM("nav");
    const seen: string[] = [];
    sut.activeChanged.subscribe((key) => seen.push(key));
    sut.setActiveKey("detail");
    expect(sut.activeKey).toBe("detail");
    expect(seen).toEqual(["detail"]);
  });
});

describe("DISC-003", () => {
  it("setting same key is a no-op", () => {
    const sut = new DiscriminatorVM("nav");
    const seen: string[] = [];
    sut.activeChanged.subscribe((key) => seen.push(key));
    sut.setActiveKey("nav");
    expect(seen).toEqual([]);
  });
});

describe("DISC-004", () => {
  it("modalOpen activates modal key", () => {
    const sut = new DiscriminatorVM("nav");
    sut.modalOpen("modal");
    expect(sut.activeKey).toBe("modal");
    expect(sut.isActive("modal")).toBe(true);
  });
});

describe("DISC-005", () => {
  it("modalClose restores prior key", () => {
    const sut = new DiscriminatorVM("nav");
    sut.setActiveKey("detail");
    sut.modalOpen("modal");
    sut.modalClose();
    expect(sut.activeKey).toBe("detail");
  });
});

describe("DISC-006", () => {
  it("nested modal precedence restores in LIFO order", () => {
    const sut = new DiscriminatorVM("nav");
    sut.modalOpen("modal-a");
    sut.modalOpen("modal-b");
    sut.modalClose();
    expect(sut.activeKey).toBe("modal-a");
    sut.modalClose();
    expect(sut.activeKey).toBe("nav");
  });
});
