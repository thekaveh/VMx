// LIFE-021: a lifecycle call during the inline dispose cascade fails
// (spec/02-lifecycle.md §7.2, ADR-0175).
//
// PLACEHOLDER. A `construct()`, `destruct()`, or `reconstruct()` call that
// starts during the cascade throws `StatusTransitionError` for `Disposed` and
// publishes nothing, and no status other than `Disposed` commits once the
// cascade has started. The implementation PR replaces this skipped placeholder
// with the full LIFE-021 scenarios, including `AggregateVM1` to `AggregateVM6`.

import { describe, it } from "vitest";

describe("LIFE-021", () => {
  it.skip("placeholder: replaced by the ADR-0175 implementation", () => {});
});
