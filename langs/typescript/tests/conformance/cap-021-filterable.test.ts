// Conformance stub: CAP-021 — IFilterable<TItem> capability contract surface and opt-in behavior.
// See spec/12-conformance.md §CAP-021 and spec/14-capabilities.md.
//
// IFilterable<TItem> does not exist yet; this stub satisfies the conformance
// coverage requirement. Replace with a real test once IFilterable<TItem> lands
// in the capabilities module (Task 1A.5–1A.7).

import { describe, it } from "vitest";

describe("CAP-021", () => {
  // IFilterable<TItem> is not implemented yet (Task 1A.5–1A.7).
  // These todos satisfy the conformance coverage requirement; replace with
  // real tests once IFilterable<TItem> lands in the capabilities module.
  it.todo(
    "IFilterable<TItem> contract: exposes settable Filter predicate and can_filter() decision",
  );
  it.todo("IFilterable<TItem>: setting Filter to null/undefined clears the filter");
  it.todo("IFilterable<TItem>: a VM that does NOT opt in reports false for IFilterable");
});
