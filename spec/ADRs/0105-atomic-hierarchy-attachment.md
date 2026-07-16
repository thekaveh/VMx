# ADR 0105 — Make hierarchy attachment atomic and non-owning

**Status:** Accepted (2026-07-14)
**Spec version:** introduced in 3.20.1

## 1. Context

`ReparentChild` preflighted ancestor cycles and detached the old parent, while
`AddChild` appended first and overwrote the child's parent reference. Calling
`AddChild` with an attached node therefore left the same identity in two parent
lists; calling it with self or an ancestor could create an unwalkable cycle.
Several conformance paths legitimately use `AddChild` to transfer an existing
node, so treating it as detached-only would preserve the corruption hazard.

Chapter 18 also described eager construction as mirroring disposal order even
though hierarchical nodes do not own or dispose their child nodes. That wording
could cause consumers to assume a lifetime cascade that no flavor provides.

## 2. Decision

`AddChild` preflights the HIER-018 identity-based cycle rule before any mutation.
Adding an existing child of the receiver is a no-op. A child attached elsewhere
is removed from its old parent's materialized list by identity, appended to the
new parent's list, and assigned the new parent as one logical transfer. The new
parent publishes one `Reparented` message; a newly attached child publishes one
`Added` message. Rejection and attachment failure leave both lists and the
backpointer unchanged.

C#, Python, and TypeScript throw their standard invalid-operation error. Rust
returns `VmxResult`. Swift adds an ignorable, source-compatible
`Result<Void, HierarchyError>` return so existing call sites may continue to
ignore success while callers can inspect rejection without converting the
method into a new throwing API.

Hierarchy construction coordination remains depth-first when eager children
are enabled, but it creates no ownership or disposal relationship. Child
lifetime management remains the consumer's responsibility.

## 3. Consequences

- A node identity cannot remain in two parents after `AddChild`.
- `AddChild` and `ReparentChild` now share the same cycle safety boundary.
- Existing successful call sites retain their surface behavior.
- Cross-parent `AddChild` emits `Reparented`, not a misleading second `Added`.
- Eager construction no longer implies an undocumented disposal cascade.

## 4. Rejected alternatives

- Reject every already-attached child: incompatible with existing path and
  batch-attachment usage that intentionally transfers nodes.
- Silently ignore cycle attempts: hides corrupted input and diverges from
  HIER-018.
- Make Swift `addChild` newly throwing: correct but unnecessarily
  source-breaking when a result return can preserve ignored-success call sites.
