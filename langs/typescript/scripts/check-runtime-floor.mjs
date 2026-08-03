import assert from "node:assert/strict";
import { createRequire } from "node:module";

import { BatchUpdateHandle as EsmBatchUpdateHandle } from "../dist/index.js";

const require = createRequire(import.meta.url);
const { BatchUpdateHandle: CjsBatchUpdateHandle } = require("../dist/index.cjs");

assert.equal(typeof Symbol.dispose, "symbol");

function assertDisposalProtocol(BatchUpdateHandle) {
  let exits = 0;
  const handle = new BatchUpdateHandle({
    _exitBatch() {
      exits += 1;
    },
  });

  assert.equal(typeof handle[Symbol.dispose], "function");
  handle[Symbol.dispose]();
  handle.dispose();
  assert.equal(exits, 1);
}

assertDisposalProtocol(EsmBatchUpdateHandle);
assertDisposalProtocol(CjsBatchUpdateHandle);

console.log("VMx Node runtime-floor ESM/CommonJS smoke passed");
