# ADR 0168 — Swift and Rust `PagedComposition` page a stored copy of the source

- **Status:** Accepted
- **Date:** 2026-11-01
- **Spec version:** 3.30.0 (clarification of chapter 21 §5.2, §5.5 and §7.2)

## 1. Context

Chapter 21 §5.2 said that `PagedComposition` computes each slice on demand. It
said that repeatable sources and factories stay live, because each read
enumerates them again. The repeatable-source claim holds for C#, Python and
TypeScript only. Only Python and TypeScript take a factory.

Swift `init(source:)` stores a copy of the `[TVM]` array value. Rust
`PagedComposition::new` takes the `Vec<T>` by value and keeps it in its own
`Mutex`. A later change to the caller's collection does not reach either copy.
A Swift probe built a pager over `[1, 2, 3]` with `pageSize: 2`. The caller
then appended two items to its own array. The pager still reported
`pageCount == 2` and the items `[1, 2]` (#1068).

Swift `setSource(_:)` is the only update call for a Swift array source.
ADR-0060 §2.5 chose this call because Swift arrays are value types. Chapter 21
did not reflect that decision. Rust changes its copy only through `set_source`,
`push` and `remove_at`. Swift `init(sourceComposite:)` follows the composite
through `collectionChanged`. Each emission replaces the stored copy.

Chapter 21 had four more statements that did not hold in every flavor:

- §5.2 said that "the source is never mutated". Rust `push` and `remove_at`
  change the stored copy, which is the only Rust source. Enumerating a one-shot
  source also consumes it.
- §5.2 tied the `PageCount` recompute to a source change. In C#, Python and
  TypeScript, `PageCount` reads the live source on every access. Only the
  `CurrentPageIndex` clamp waits, as this ADR §2 states.
- §5.5 implied that Swift observes an `ObservableList` source, and §7.2
  implied it for Swift and Rust. Swift observes only a `CompositeVM` source.
- §7.2 said that the pager recomputes its page slice on a batch `Reset`. The
  pager reads the live source on every access, so it only clamps the index and
  publishes its notifications.

Guide section 6.7.10 made the same liveness claim. Its sentence "Swift and Rust
take a repeatable collection, so the case does not arise there" also implied
that Swift and Rust stay live. ADR-0155 corrected the C# wording in the same
paragraphs.

## 2. Decision

- §5.2 states that the pager never changes the caller's repeatable source, and
  that enumerating a one-shot source consumes it.
- §5.2 states that C#, Python and TypeScript compute slices on demand from the
  live source.
- §5.2 states that Swift and Rust page a stored copy that they take at
  construction. It names the update calls: Swift `setSource(_:)`, and Rust
  `set_source`, `push` and `remove_at`.
- §5.2 states that Swift `init(sourceComposite:)` follows the composite through
  `collectionChanged`.
- §5.2 states that `PageCount` and `Items` always read the current source. A
  delivered change clamps `CurrentPageIndex`. An observed source stream delivers
  a change. In Swift and Rust, the update calls also deliver one.
- §5.2 states that, in C#, Python and TypeScript, a change to an unobserved live
  source shows on the next read. The index clamp then waits for a delivered
  change, the next `CurrentPageIndex` assignment, or a `PageSize` assignment
  that changes the page size.
- The one-shot paragraph says that a one-shot source cannot occur in Swift or
  Rust. Swift takes an array or a `CompositeVM`, and Rust takes a `Vec`. Only
  Python and TypeScript take a factory.
- §5.5 states that Swift observes only a `CompositeVM` source. §7.2 limits the
  observed `Reset` to C#, Python and TypeScript. There, the `Reset` clamps the
  index and publishes the notifications once.
- Guide section 6.7.10, renamed "Paged Composition Sources", states the same
  rules.

This is an accuracy correction. It adds no conformance ID and changes no
package or specification version.

## 3. Consequences

- The text matches the behavior of all five flavors. No behavior changes.
- A Swift or Rust reader calls an update method after the source changes.
  Before, a reader who followed the text got stale pages without an error.
- A live Swift or Rust array source would change behavior. ADR-0060 §2.5 chose
  an explicit `setSource(_:)` for Swift arrays. ADR-0060 §4 rejected an
  observed `CurrentValueSubject` array source. A new design needs a separate
  decision.
