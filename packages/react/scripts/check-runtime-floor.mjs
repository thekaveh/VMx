// Load the built adapter's ESM and CJS entry points and render through each
// one, on the Node runtime that runs this script (#1334). CI runs it on the
// declared floor, Node 20.5.0, with each React major of the CI matrix.
//
//   node scripts/check-runtime-floor.mjs <react-major>
import assert from "node:assert/strict";
import { createRequire } from "node:module";

import { MessageHub as EsmMessageHub } from "@thekaveh/vmx";

import * as esm from "../dist/index.js";

const require = createRequire(import.meta.url);
const cjs = require("../dist/index.cjs");
const React = require("react");
const { renderToString } = require("react-dom/server");
const { MessageHub: CjsMessageHub } = require("@thekaveh/vmx");

const expectedMajor = process.argv[2];
assert.ok(expectedMajor, "pass the expected React major");
assert.equal(React.version.split(".")[0], expectedMajor, `React ${React.version} is installed`);

for (const [format, adapter, MessageHub] of [
  ["ESM", esm, EsmMessageHub],
  ["CJS", cjs, CjsMessageHub],
]) {
  assert.equal(typeof adapter.useVm, "function", `${format} exports useVm`);
  const store = adapter.createVmxStore(new MessageHub());
  const App = () => React.createElement("span", null, adapter.useVmx(store, () => format));
  assert.equal(renderToString(React.createElement(App)), `<span>${format}</span>`);
  store.dispose();
}

console.log(
  `VMx React adapter ESM/CJS runtime-floor smoke passed on Node ${process.versions.node} ` +
    `with React ${React.version}`,
);
