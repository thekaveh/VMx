# ADR 0116 — Correct threading lifecycle-guard cross-references

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0047](0047-v3-lifecycle-threading-semantics.md)

## 1. Context

Chapter 11's background-work guarantees correctly described the per-VM
transition guard and `LIFE-008` in-flight admission rule, but two inline links
pointed to chapter 02 §2.3. That section defines owned-resource cleanup. The
transition atomicity and concurrency guard are defined in §2.4.

The prose, implementations, and conformance coverage already agreed on the
guard behavior. Only the cross-reference targets were stale after lifecycle
chapter organization evolved.

## 2. Decision

- Point both chapter 11 concurrency-guard references to chapter 02 §2.4.
- Preserve every existing threading, lifecycle, error, and publication rule.
- Add no conformance ID, API change, fixture change, or version bump because
  this correction changes navigation only.

## 3. Consequences

- Readers land on the normative transition-atomicity section instead of the
  unrelated owned-resource contract.
- The correction remains compliant with the repository's rule that every edit
  to a numbered specification chapter is accompanied by an ADR.

## 4. Rejected alternatives

- Leave the incorrect links in place: that makes the background-work rationale
  appear to cite the wrong synchronization contract.
- Waive the ADR requirement: a maintainer label can exempt typo-only changes,
  but an in-repository decision record keeps this maintenance branch
  independently verifiable without relying on PR metadata.
