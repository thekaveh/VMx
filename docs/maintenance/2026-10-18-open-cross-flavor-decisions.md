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

ADR-0123 §2 says the first operation failure stays the reported failure and a
compensation failure is surfaced with it. On factory-population rollback and on
add or insert attach rollback:

- C# reports an `AggregateException` of both. TypeScript reports
  `ContainerRollbackError(original, compensation)`. Python raises the
  compensation error `from` the original.
- Swift reports `.attachmentFailed(compensationError)` and Rust returns the
  compensation error. Both drop the original failure (for example
  `langs/swift/Sources/VMx/Composites/CompositeVM.swift:423-424` and
  `langs/rust/src/groups.rs:328`).

On the ordinary construct path no flavor rolls back siblings that already
constructed. The spec does not say whether it should.

## 2. Small spec gaps

### 2.1. Notification opacity after resolution

`spec/16-notifications.md` says opacity decays toward 0. It does not say what a
read returns after resolution. C#, Python, TypeScript and Swift compute it from
the clock, so it keeps decreasing. Rust freezes it at resolution.

### 2.2. Initial debounced search refresh

C#, Python, TypeScript and Swift seed the search term with `""` and debounce it,
so one filtered emission arrives after construction without a request. With a
zero debounce, C#, Python and TypeScript emit it inside the constructor, where
no subscriber can see it. Every SRCH-007 test uses a zero debounce, so no test
exposes it. Rust is pull-based and does not emit it.

### 2.3. Duplicate dictionary key error

`spec/21-collections.md` §4 names no error for a duplicate key.

| Flavor     | Error                                    |
| ---------- | ---------------------------------------- |
| C#         | `ArgumentException`                      |
| Python     | `KeyError`                               |
| TypeScript | `Error`                                  |
| Swift      | `ObservableDictionaryError.duplicateKey` |
| Rust       | `VmxError::InvalidArgument`              |

The keyed serviced collection does name exact types (`spec/21-collections.md`
§2.10), and there Python uses `ValueError`.

### 2.4. VM-collection `CollectionChanged` sender name

`spec/03-messages.md` says the sender name "typically" equals the VM name. C#,
Python and TypeScript use the sender's type name. Swift and Rust use the VM
name.

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

With auto-construct on, a child added while a container is `Constructing` is
joined by the construct walk (chapter 06 §5.1). C#, Python and TypeScript pass
the live membership to the `Current(selector)` callback. Swift passes the
membership taken before the walk, so the selector does not see a late child.
The live membership can contain a child that an add has attached but not yet
admitted. Every flavor treats that child as not contained, so selecting it is
a no-op (ADR-0165, ADR-0173).

### 2.8. Removing a child during the construct walk

Every flavor walks a fixed snapshot of the members present when construct
starts, then (with auto-construct on) members added later. A snapshot child
removed during the walk is still constructed, and a removed background child
is still awaited: if it then fails, the container rolls back although it no
longer owns that child. A late child removed before the walk reaches it is
skipped. The spec does not say which behavior is intended.

### 2.10. Cross-thread membership admission

When another thread holds a container's membership transaction, a new
admission either waits for it to end or fails. Admission here means an add,
insert, replace or population, and the detach from the old parent when a child
moves. Chapter 06 defines a cross-thread wait for disposal, not for admission.

| Flavor | Composite                                                                                                                                                                                | Group                                                                                                                                                         |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C#     | Fails with `InvalidOperationException` ([`CompositeVMBase.cs`](../../langs/csharp/src/VMx/Composites/CompositeVMBase.cs), `BeginMembershipTransactionLocked` and `EnsureChildAdmission`) | Waits, and refuses a wait that would close a cycle ([`GroupVMBase.cs`](../../langs/csharp/src/VMx/Groups/GroupVMBase.cs), `BeginMembershipTransactionLocked`) |
| Python | Raises `RuntimeError` ([`composite_vm.py`](../../langs/python/src/vmx/composites/composite_vm.py), `_require_child_admission`)                                                           | Raises `RuntimeError` ([`group_vm.py`](../../langs/python/src/vmx/groups/group_vm.py), `_require_child_admission`)                                            |
| Rust   | Returns `OwnershipTransactionInProgress` ([`runtime.rs`](../../langs/rust/src/runtime.rs), `begin_membership_transaction`)                                                               | Returns `OwnershipTransactionInProgress` (same function)                                                                                                      |
| Swift  | Waits, and refuses a wait that would close a cycle ([`CompositeVM.swift`](../../langs/swift/Sources/VMx/Composites/CompositeVM.swift), `enterMembershipTransaction`)                     | Waits, with the same refusal ([`GroupVM.swift`](../../langs/swift/Sources/VMx/Groups/GroupVM.swift), `enterMembershipTransaction`)                            |

TypeScript runs on one thread, so the case does not arise. In every flavor, a
second transaction on the same thread is rejected (ADR-0118). A population that
waits and succeeds in Swift or a C# group fails in a C# composite, in Python and
in Rust.

Removal differs again. Swift `remove`, `removeAt` and `clear` also wait for
another thread's transaction. In C# composites and groups and in Python, these
calls fail instead.

## 3. Swift signatures that cannot throw

None open. ADR-0184 closed the CMDD-010, CMDD-013 and FORM-035/036 snapshotter
gaps (§6). Other Swift operations that trap instead of throwing are listed under
ADR-0009, ADR-0037 and ADR-0053.

## 4. Tests parked as known defects

None. ADR-0173 returned the two ignored COMP-026 Rust tests to the suite.

## 5. Related records

- Rust parity backlog: [Rust parity status](2026-07-16-rust-capability-parity.md),
  §12.4.7 and §12.7–§12.12.
- The remaining Notes Showcase UX policies stay with the owner and are not
  listed here.

## 6. Closed items

| Item  | Title                                                                                         | Closed by | Pull request                                       |
| ----- | --------------------------------------------------------------------------------------------- | --------- | -------------------------------------------------- |
| §1.4  | Notifications of an update nested in a form callback                                          | ADR-0180  | [#1239](https://github.com/thekaveh/VMx/pull/1239) |
| §2.6  | `SetModel` while approval publishes                                                           | ADR-0174  | [#1211](https://github.com/thekaveh/VMx/pull/1211) |
| §2.9  | Selecting from a composite's own structural transaction                                       | ADR-0173  | [#1212](https://github.com/thekaveh/VMx/pull/1212) |
| §2.11 | Lifecycle call during a container's inline dispose cascade                                    | ADR-0175  | [#1216](https://github.com/thekaveh/VMx/pull/1216) |
| §3    | Swift: throwing inner command in CMDD-010 and CMDD-013, and the FORM-035/036 deny snapshotter | ADR-0184  | [#1490](https://github.com/thekaveh/VMx/pull/1490) |
