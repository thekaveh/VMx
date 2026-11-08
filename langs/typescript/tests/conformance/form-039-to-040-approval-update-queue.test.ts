// FORM-039..FORM-040 conformance tests — FormVM queues updates made during
// approval publication. See spec/20-form-vm.md §5.1/§5.3/§5.4 and ADR-0174.
//
// PLACEHOLDER: the spec change for ADR-0174 adds these IDs before the
// TypeScript implementation lands. The implementation PR replaces each
// skipped test below with the behavioral test. The conformance execution
// check counts a skipped ID as not passing, so CI stays red until then.

import { describe, it } from "vitest";

describe("FORM-039", () => {
  it.skip("updates during approval publication replay after onApproved (ADR-0174 placeholder)", () => {
    // Replaced by the TypeScript FormVM implementation.
  });
});

describe("FORM-040", () => {
  it.skip("a queued update prepares at call time and replays in isolation (ADR-0174 placeholder)", () => {
    // Replaced by the TypeScript FormVM implementation.
  });
});
