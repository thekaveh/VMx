# 1. Hierarchy Factory Hydration Design

## 1.1. Status

Approved for implementation on 2026-07-23.

## 1.2. Problem

Each flavor materializes a `HierarchicalVM` child factory into a list and then
assigns every produced node's parent directly. That path bypasses the identity,
ownership, and cycle checks used by the public structural mutators.

Invalid factory output can therefore corrupt the tree before any caller can
observe or reject it:

- returning the receiving node creates a self-parent cycle;
- returning the same node twice creates duplicate identity membership;
- returning an ancestor creates an ancestor cycle;
- returning an already-parented node leaves it present in two child lists while
  its parent reference names only one owner;
- a null-like value can fail after earlier candidates have already been
  mutated.

Depth, path, root discovery, and traversal assume an acyclic, singly owned
tree, so these states can recurse indefinitely or report contradictory
structure.

## 1.3. Decision

Factory hydration is an atomic initial-attachment operation, not an implicit
transfer operation.

Every flavor must:

1. fully materialize the factory output into a stable snapshot;
1. preflight the complete snapshot before mutating any node;
1. reject null-like entries where the language permits them;
1. reject duplicate node identity within the snapshot;
1. reject the receiving node and any ancestor of the receiver;
1. reject every node whose parent is already non-null, including a node already
   parented by the receiver;
1. on rejection, leave the receiver cache, every parent link, every existing
   child collection, and every path cache unchanged, and publish no structural
   or property-change message;
1. on success, install every parent link and the receiver's child snapshot as
   one logical commit without publishing parent-change messages.

The public `AddChild`/`add_child` operation remains the explicit
attach-or-transfer API. A factory is declarative initial structure; allowing it
to transfer nodes would make a read of `Children` mutate unrelated trees.

Each flavor reports rejection through an idiomatic invalid-operation surface:

- C#: `InvalidOperationException`;
- Python: `ValueError`;
- TypeScript: `Error`;
- Swift: a new `tryChildren() -> Result<[TVM], HierarchyError>` using a new
  `invalidFactoryOutput` case; the existing nonfallible `children` property
  remains a compatibility convenience and fails fast on programmer-invalid
  factory output;
- Rust: a new `try_children() -> VmxResult<Vec<Self>>`; the existing
  `children() -> Vec<Self>` remains a compatibility convenience and fails fast
  on programmer-invalid factory output. Invalid snapshots use
  `VmxError::InvalidArgument`.

The Swift and Rust compatibility conveniences must delegate to the same
fallible implementation. A failed attempt never mutates or caches state before
either the result is returned or the compatibility convenience fails fast.
The catchable entry points are the normative error-observation surfaces used by
conformance tests and applications that accept dynamic factory input.

No new public transfer API is introduced.

## 1.4. Conformance

Add `HIER-031` as one cross-flavor scenario. It must prove:

- a valid detached snapshot attaches in input order;
- duplicate identity is rejected atomically;
- self/ancestor output is rejected atomically;
- foreign-parented output is rejected without detaching it;
- no invalid snapshot is cached;
- no parent or structural notification is emitted on rejection.

Swift and Rust assert rejection through their new catchable entry points and
also prove that their legacy convenience surfaces delegate to the same atomic
preflight. The other flavors assert their existing exception surfaces.

Tests must exercise lazy hydration. Eager construction must use the same
preflight path and is covered by a focused regression in each flavor.

The implementation also adds the explicit lifecycle hook/disposal coordination
scenario identified in the same maintenance pass. That scenario records the
already-approved ADR-0126 behavior and does not alter this hierarchy decision.

## 1.5. Error and Retry Semantics

A rejected lazy hydration attempt does not cache a partial or empty result.
The next `Children` access invokes the factory again and may succeed if it
returns a valid snapshot.

If factory enumeration itself raises or panics, the existing factory error
propagates and no tree mutation occurs. Validation never replaces that earlier
failure.

The new Swift/Rust fallible entry points distinguish invalid factory output
from factory execution failure where their existing factory delegate type
allows that distinction. Existing factory panics remain panics; this change
does not convert arbitrary user-code panics into VMx errors.

Validation and commit contain no callback or suspension point. Rust keeps both
inside its existing topology gate. This change does not broaden the documented
thread-safety contract of the other flavors; TypeScript is synchronous, while
concurrent first access in C#, Python, or Swift remains outside the hierarchy
contract unless separately synchronized by the caller.

## 1.6. Alternatives Rejected

### 1.6.1. Transfer already-parented nodes

Rejected because a property read would mutate an unrelated parent, publish
cross-tree structural events, and require multi-parent rollback if a later
candidate fails.

### 1.6.2. Filter invalid candidates

Rejected because silent omission hides a broken factory and makes the
materialized tree depend on validation order.

### 1.6.3. Attach candidates incrementally

Rejected because a later invalid candidate would require rollback of parent
links, path caches, and messages. Full preflight is simpler and preserves
atomicity.

## 1.7. Specification, Versioning, and Documentation

Implementation will add ADR-0127, update chapter 18 and its conformance list,
add the catalog scenario and five real test markers, and synchronize all
current conformance counts.

Because the change fixes observable behavior and adds fallible Swift/Rust
entry points without removing existing APIs, the spec and flavor versions
advance by their patch policy from the current source lines. Compatibility
matrix rows, minimum-spec declarations, package manifests, changelogs,
generated documentation, diagrams, and package metadata must remain
consistent.

## 1.8. Verification

Verification includes:

- red-green focused tests in all five flavors;
- every flavor's complete test, lint, format, type-check, and package gate;
- exact 100% conformance coverage after the new IDs;
- version, fixture, generated-artifact, and package consistency checks;
- numbered canonical documentation plus generated site/wiki drift checks;
- diagram regeneration and validation if derived counts change;
- pre-commit and clean-diff checks.
