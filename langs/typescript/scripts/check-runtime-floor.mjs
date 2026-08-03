import assert from "node:assert/strict";

import { BatchUpdateHandle } from "../dist/index.js";

assert.equal(typeof Symbol.dispose, "symbol");

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

console.log("VMx Node runtime-floor smoke passed");
