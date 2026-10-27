// The global setup invalidates rebuilt files by the ids Vite stores (#781).

import { describe, expect, it } from "vitest";

import { toViteFileId } from "../globalSetup.js";

describe("toViteFileId", () => {
  it("turns a Windows path into a forward-slash id on every host", () => {
    expect(toViteFileId("C:\\repo\\langs\\typescript\\dist\\index.js")).toBe(
      "C:/repo/langs/typescript/dist/index.js",
    );
  });

  it("keeps a forward-slash path unchanged", () => {
    expect(toViteFileId("/repo/langs/typescript/dist/index.js")).toBe(
      "/repo/langs/typescript/dist/index.js",
    );
  });
});
