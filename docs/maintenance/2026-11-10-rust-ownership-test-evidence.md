# Rust ownership-test evidence

Recorded 2026-11-10. This note holds the test-internal evidence for the Rust
serviced-collection ownership tests. The user-facing ownership rules are in the
contributing guide's Rust ownership-test section. These tests strengthen the
catalog IDs `COL-055` and `COL-062` and add no catalog IDs.

## 1. Test method

`COL-055` and `COL-062` wrap real `ComponentVm` instances in test-private
shared wrappers. After each operation, including failed keyed preflight and
empty operations, they count every known wrapper handle. They also check
lifecycle hooks and parent state. After returned and snapshot handles are
released, the caller disposes each VM exactly once and releases its last
wrapper. The test then checks weak-reference expiration and a separate native
release counter.

The exact counts are deterministic because the
tests control every holder and run mutations synchronously. They do not count
the VM's internal references.

## 2. Limits

A retained caller `Arc` always has at least one strong reference. A check of
`strong_count >= 1` therefore cannot prove that a collection released its item
handles. A temporary mutation that leaks items inside both `clear`
implementations fails both tests; the unmodified implementations pass. These
tests strengthen `COL-055` and `COL-062` and add no catalog IDs.

The C#, Python, TypeScript, and Swift counterparts use direct lifecycle
observables, with different probe coverage. C# observes disposal. Swift omits
some lifecycle categories. Python's keyed test does not retain failed-operation
candidates, and TypeScript's keyed test instruments one item. None asserts
exactly-once caller cleanup. These are limits of the test evidence, not proof of
a collection defect.
