import { describe, expect, it } from "vitest";
import { ModalVM, NullDialogService, type IModalDialogService } from "../../src/index.js";

describe("DIA-009", () => {
  it("present returns modal result", async () => {
    const modal = new ModalVM("cancel");
    const service: IModalDialogService = {
      pickFileToOpen: (...args) => NullDialogService.INSTANCE.pickFileToOpen(...args),
      pickFileToSave: (...args) => NullDialogService.INSTANCE.pickFileToSave(...args),
      confirm: (...args) => NullDialogService.INSTANCE.confirm(...args),
      notify: (...args) => NullDialogService.INSTANCE.notify(...args),
      present: async <T>(modalVm: ModalVM<T>) => {
        modalVm.dismiss("accepted" as T);
        return modalVm.completion;
      },
    };

    await expect(service.present(modal)).resolves.toBe("accepted");
    expect(modal.result).toBe("accepted");
  });
});

describe("DIA-010", () => {
  it("null present uses cancellation result", async () => {
    const modal = new ModalVM("cancel");

    await expect(NullDialogService.INSTANCE.present(modal)).resolves.toBe("cancel");
    expect(modal.isDismissed).toBe(true);
    expect(modal.result).toBe("cancel");
  });
});

describe("DIA-011", () => {
  it("modal dispose completes with cancellation result", async () => {
    const modal = new ModalVM("cancel");
    modal.dispose();

    await expect(modal.completion).resolves.toBe("cancel");
    expect(modal.isDismissed).toBe(true);
  });
});

describe("DIA-012", () => {
  it("modal dismiss is idempotent", async () => {
    const modal = new ModalVM("cancel");
    modal.dismiss("first");
    modal.dismiss("second");

    await expect(modal.completion).resolves.toBe("first");
    expect(modal.result).toBe("first");
  });
});

describe("DIA-013", () => {
  it("existing dialog methods remain source-compatible", async () => {
    const sut = NullDialogService.INSTANCE;

    await expect(sut.pickFileToOpen()).resolves.toBeNull();
    await expect(sut.pickFileToSave()).resolves.toBeNull();
    await expect(sut.confirm("Proceed?")).resolves.toBe(false);
    await expect(sut.notify("Done")).resolves.toBeUndefined();
  });
});
