# Open Cross-Flavor Decisions

Recorded: **2026-10-18**, against the `overnight-maintenance` branch (spec
3.29.0). Each item below is a known difference between flavors or a gap in the
specification. None of them is accidental drift. Do not change one flavor to
match the others until the owner decides the rule and records it in the spec
and an ADR.

When an ADR closes an item, remove the item from its section and add a row to
§6 that names the ADR and the pull request. A closed item keeps no stub, and
its number is not used again, so an ADR that cites the number still finds it in
§6. A section without numbered items, such as §3, closes as a whole. It keeps
its heading and says "None open", and its §6 row names the section.

Paths are relative to the repository root. Line numbers are those of the
recording date.

## 1. Spec text needs a decision

### 1.1. Async resource: cancelling a discard-mode retry from `Error`

`spec/23-async-resource-vm.md` §8 says `DiscardPrevious` uses `Idle` as the
cancellation baseline. §5 and §7 say cancellation restores the saved stable
state.

- Swift resets the baseline to `Idle` on every discard-mode start
  (`langs/swift/Sources/VMx/State/AsyncResourceVM.swift:271-273`). A cancelled
  retry from `Error` returns to `Idle`.
- C#, Python, TypeScript and Rust reset the baseline only when the stable state
  holds a value (for example `langs/python/src/vmx/state/async_resource_vm.py:249-252`).
  A cancelled retry from a value-less `Error` returns to that `Error`.
- No ARES test covers this case.

### 1.2. Failures inside derived streams

**Consumer cases decided by
[ADR-0191](../../spec/ADRs/0191-subscriber-failures-do-not-stop-delivery-or-detach.md)**
(2026-11-09, under the owner's delegation). Chapter 03 §3.6 now states one rule
for a failing subscriber or callback on these channels: the hub and its §7.1
and §7.2 helpers, `DerivedProperty.ValueChanged`, `SearchableState` (its
predicate, item supplier and `Filtered` subscribers), and command
`CanExecuteChanged` handlers on the trigger path and on a direct raise.

- A delivery reaches every subscriber once, even when an earlier one fails.
- No failure detaches a subscriber or the library's own source subscription.
- A stream-fed failure never reaches the upstream publisher. C# discards it,
  Python logs it, TypeScript reports it through rxjs, and Rust catches the
  panic. Swift subscribers on these channels cannot fail.
- A failing `SearchableState` predicate keeps the last snapshot, and a later
  valid term recomputes as usual.

One case stays open: a throwing `DerivedProperty` transform or a failing source
(#374).

| Flavor     | Throwing transform or failing source       |
| ---------- | ------------------------------------------ |
| C#         | Unhandled `OnError` is rethrown; detaches  |
| Python     | Default `on_error` raises; detaches        |
| TypeScript | The stream errors; detaches                |
| Swift      | Not possible: sources are `Never`-failing  |
| Rust       | Panic is caught; the value does not update |

### 1.3. Rollback failure loses the original failure in Swift and Rust

**The error shape is decided by
[ADR-0218](../../spec/ADRs/0218-container-rollback-errors-walk-resumption-and-single-start.md)**
(2026-11-09, under the owner's delegation, #1305). The item stays here so
that the section numbers do not change. Chapter 06 §4.2 now requires that the
reported failure gives access to the original failure and to the first
compensation failure. Swift returns `.attachmentFailed(ContainerRollbackError)`,
and Rust returns `VmxError::ContainerRollback`. C#, Python and TypeScript keep
their shapes.

One question stays open. On the ordinary construct path no flavor rolls back
siblings that already constructed. The spec does not say whether it should.

## 2. Small spec gaps

### 2.5. Delivery order across subscribers

**Decided for `AggregateChangeStream` by
[ADR-0192](../../spec/ADRs/0192-aggregate-change-stream-delivers-in-subscription-order.md)**
(2026-11-09, under the owner's delegation). The item stays here so that the
section numbers do not change. Chapter 21 §9.5 now requires subscription order
for item, structural, final `Batch` and completion delivery (`AGCH-011`). Swift
moves to ordered storage, and C# stops relying on `HashSet<T>` order.

No rule fixes the order for the hub or for other streams. Swift's
`VMxConcurrentSubject` (the per-VM `propertyChanged` subject and the `FormVM`
channels, ADR-0174) delivers in subscription order, but no rule requires it.

### 2.7. Initial-current selector input after late adds

**Decided by
[ADR-0218](../../spec/ADRs/0218-container-rollback-errors-walk-resumption-and-single-start.md)**
(2026-11-09, under the owner's delegation, #1312). The item stays here so that
the section numbers do not change. Chapter 06 §3.2 now says that the
`Current(selector)` callback receives the live membership when it runs, so it
sees a late child (`COMP-053`). A pick of a child that an add has attached but
not yet admitted stays a no-op (ADR-0165, ADR-0173).

Before ADR-0218, Swift passed the membership taken before the walk. C#,
Python, TypeScript and Rust already passed the live membership.

### 2.8. Removing a child during the construct walk

**Decided by ADR-0186** (2026-11-09, under the owner's delegation). The item
stays here so that the section numbers do not change. Chapter 06 §5.1 now
states the rule for every flavor:

- The construct walk counts members only. It checks membership before it
  starts or joins a child, and again after the child settles.
- A child that a removal takes out during the walk does not roll the
  container back, whether it is a snapshot child or a late child. The walk
  does not construct a snapshot child removed before it reaches it.
- A failed add undoes its attach, so its child is removed too. The add fails,
  and the container does not roll back.

Before ADR-0186, every flavor constructed a removed snapshot child and waited
on a removed background child. A failure of that child rolled the container
back. Only a late child removed before the walk reached it was skipped.

### 2.10. Cross-thread membership admission

**Decided by ADR-0187** (2026-11-09, under the owner's delegation). The item
stays here so that the section numbers do not change. Chapter 06 §4.2 and
chapter 07 §1.1 now state the rule for every flavor:

- A membership change never waits for another thread's membership
  transaction. The changes are add, insert, index replacement, population,
  transfer detach, `remove`, `removeAt` and `clear`.
- While any thread holds the transaction, each change fails before mutation
  with the "membership transaction in progress" error of a re-entrant change
  (ADR-0118).
- Rust `clear()` returns `VmxResult<()>` and reports the refusal. Swift
  `removeAt(_:)` and `clear()` cannot throw and return with no change (§3).
- Disposal from another thread still waits for the transaction boundary
  (ADR-0122, ADR-0153).

Before ADR-0187, Swift containers and C# groups waited for the other
transaction, and refused only a wait that would close a cycle. C# composites,
Python and Rust failed at once. Rust `clear()` returned with no change and no
error.

## 3. Swift signatures that cannot throw

ADR-0184 closed the CMDD-010, CMDD-013 and FORM-035/036 snapshotter gaps
(§6).

Swift `CompositeVM.removeAt(_:)`, `CompositeVM.clear()`, `GroupVM.removeAt(_:)`
and `GroupVM.clear()` cannot throw. A call refused because a membership
transaction is open returns with no change, so the caller cannot see the
refusal (ADR-0187). The other flavors raise or return an error.

Swift `add(_:)`, `insert(_:at:)` and `replace(at:with:)` on `CompositeVM` and
`GroupVM` cannot throw either. A refused `add(_:)` traps in a debug build. In
a release build, each refused call returns with no change and no signal. Since
ADR-0187, another thread's open transaction refuses them at once. Callers use
`addResult`, `insertResult` and `replaceResult` to see the refusal.

Other Swift operations that trap instead of throwing are listed under
ADR-0009, ADR-0037 and ADR-0053.

## 4. Tests parked as known defects

None. ADR-0173 returned the two ignored COMP-026 Rust tests to the suite.

## 5. Related records

- Rust parity backlog: [Rust parity status](2026-07-16-rust-capability-parity.md),
  §12.7 and §12.13.
- ADR-0201 decides the Notes Showcase selection, unsaved-edit, Save and theme
  policies (#1331).

## 6. Closed items

| Item  | Title                                                                                         | Closed by | Pull request                                       |
| ----- | --------------------------------------------------------------------------------------------- | --------- | -------------------------------------------------- |
| §1.4  | Notifications of an update nested in a form callback                                          | ADR-0180  | [#1239](https://github.com/thekaveh/VMx/pull/1239) |
| §2.3  | Duplicate dictionary key error                                                                | ADR-0214  | [#1522](https://github.com/thekaveh/VMx/pull/1522) |
| §2.6  | `SetModel` while approval publishes                                                           | ADR-0174  | [#1211](https://github.com/thekaveh/VMx/pull/1211) |
| §2.9  | Selecting from a composite's own structural transaction                                       | ADR-0173  | [#1212](https://github.com/thekaveh/VMx/pull/1212) |
| §2.11 | Lifecycle call during a container's inline dispose cascade                                    | ADR-0175  | [#1216](https://github.com/thekaveh/VMx/pull/1216) |
| §3    | Swift: throwing inner command in CMDD-010 and CMDD-013, and the FORM-035/036 deny snapshotter | ADR-0184  | [#1490](https://github.com/thekaveh/VMx/pull/1490) |
