# ADR 0248 — Attach transfers keep the ancestor walk; the O(1) check covers a parentless child

- **Status:** Accepted
- **Date:** 2026-11-23
- **Spec version:** 3.30.0 (no spec chapter change; no conformance ID change; no library behavior change)
- **Amends:** [ADR-0247](0247-hierarchy-root-pointer.md) §2.2 and §3. Related: [ADR-0037](0037-v2.5-maintenance-clarifications.md) (HIER-018), [ADR-0127](0127-validate-hierarchy-factory-hydration-atomically.md) (factory hydration), #1912, #2225.

## 1. Context

ADR-0247 §2.2 says that a candidate that already has a parent "takes the existing already-parented error path", that "only there does the code walk the ancestors", and that "the success path costs O(1)". These statements do not match attach:

1. Attach is attach-or-transfer. Spec chapter 18 §7 says that adding a child owned by another parent removes it from the old parent, appends it to the new parent and publishes one `Reparented` message. That transfer succeeds. It is not an error.
1. The already-parented rejection is the factory-hydration rule of ADR-0127: a children factory cannot return a child that already has a parent, and factory hydration never implies transfer. It is not an attach rule.
1. ADR-0247 removes the ancestor walk only for a parentless candidate. A parented candidate can be an ancestor of this node, and the root link does not say which nodes are ancestors. So a transfer still needs the walk.

The Swift attach path (`attachChild` in `langs/swift/Sources/VMx/Hierarchical/HierarchicalVM.swift`) does exactly this, and it matches chapter 18 §7. The wording of ADR-0247 §2.2 is what is wrong. This ADR corrects it. It does not change the code.

## 2. Decision

### 2.1 Parentless candidate (O(1))

A candidate with no parent is a cycle when it is this node or this node's root. Otherwise it attaches. This is ADR-0247 §2.2 unchanged. The check costs O(1), because a parentless ancestor of this node can only be the root of its tree.

### 2.2 Candidate with a parent (transfer, O(depth))

A candidate that already has a parent is a transfer under chapter 18 §7. Its cycle check walks this node's ancestors and tests whether the candidate is one of them, which costs one O(depth) walk:

- If the candidate is this node or one of its ancestors, the attach fails with the cycle error (HIER-018), and the tree is unchanged.
- Otherwise the transfer succeeds, removes the candidate from its old parent and publishes one `Reparented` message.

The error text is the same for a parentless cycle and a parented cycle in the Swift attach path, so the walk chooses no message there. Error texts do not change.

### 2.3 Cross-tree shortcut (not required)

A parented candidate that lies in another tree cannot be an ancestor of this node, so its walk may be skipped. The shortcut changes the cost of a transfer, not its result. This ADR does not require it. The rule that all five flavors must share is the result: a candidate is rejected with the cycle error exactly when it is this node or one of its ancestors. A flavor may take the shortcut. The Rust attach path in pull request #2224 does, and the Swift attach path in pull request #2225 walks every parented candidate. A later ADR can make the cost the same in all five flavors.

### 2.4 Scope

This ADR changes no spec chapter, no conformance ID, no public API, no version and no library behavior. The Status line and the registry cell of ADR-0247 gain the back-link "§2.2 and §3 amended by ADR-0248".

## 3. Consequences

- A parentless attach costs O(1). The O(N²) build that issue #1912 names comes from these attaches, so a tree of N nodes built by parentless attaches costs O(N) in the attach step.
- A transfer costs one O(depth) walk, as it did before ADR-0247. This ADR does not make transfers O(1), and transfers are not part of the build cost.
- A rejected attach of a parentless candidate costs O(1). A rejected attach of a parented candidate costs the walk.
- The sentence "An attach that succeeds costs O(1)" in ADR-0247 §3 is replaced by the three bullets above.

## 4. Rejected alternatives

- **Reject a candidate that has a parent as already-parented (the reading that ADR-0247 §2.2 gives).** Rejected. Chapter 18 §7 requires the transfer to succeed and publish `Reparented`. The already-parented rejection applies to factory output only (ADR-0127).
- **Make transfers O(1) with the root link alone.** Rejected. The root link says which tree a parented candidate is in. It does not say whether the candidate is an ancestor of this node. An ancestor set on each node is the cost that ADR-0247 §4 rejects.
- **Amend ADR-0247 in place.** Rejected. A changed decision is recorded as a new ADR with a back-link to the earlier one (`spec/ADRs/README.md` §2.3).
