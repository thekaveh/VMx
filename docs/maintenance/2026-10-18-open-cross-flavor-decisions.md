# Open Cross-Flavor Decisions

Recorded: **2026-10-18**, against the `overnight-maintenance` branch (spec
3.29.0). Each item below is a known difference between flavors or a gap in the
specification. None of them is accidental drift. Do not change one flavor to
match the others until the owner decides the rule and records it in the spec
and an ADR. Remove an item when that ADR lands.

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

The only consumer-isolation rule is for the hub (`spec/03-messages.md` §3.4,
HUB-007). `spec/15-derived-properties.md` has no rule for a throwing consumer,
transform or source. For `SearchableState`, SRCH-005 covers only a failing
source signal.

| Flavor     | Throwing consumer                                                          | Throwing transform or failing source       |
| ---------- | -------------------------------------------------------------------------- | ------------------------------------------ |
| C#         | Rx detaches the subscription; the property stops updating for every reader | Unhandled `OnError` is rethrown; detaches  |
| Python     | Exception reaches the publisher; the subscription stays                    | Default `on_error` raises; detaches        |
| TypeScript | Reported through the rxjs unhandled-error hook; the subscription stays     | The stream errors; detaches                |
| Swift      | Not possible: sinks and transforms cannot throw                            | Not possible: sources are `Never`-failing  |
| Rust       | Panic is caught per subscriber; the subscription stays                     | Panic is caught; the value does not update |

The C# consumer behavior also applies to a throwing `SearchableState` consumer
or predicate (built on `Merge`) and to command triggers built from Rx operators.
The C# hub's isolating observer (`langs/csharp/src/VMx/Services/MessageHub.cs:376`)
protects only raw `hub.Messages` subscribers.

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

### 2.5. Delivery order across subscribers

No rule fixes the order in which several subscribers receive one event. Swift's
`AggregateChangeStream` stores observers in a dictionary, so its order is
unspecified. The other flavors, and Swift's `VMxConcurrentSubject` (the per-VM
`propertyChanged` subject and the `FormVM` channels, ADR-0174), deliver one
event in subscription order.

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

### 2.9. Selecting from a composite's own structural transaction

**Decided by ADR-0173** (2026-11-07, under the owner's delegation). The item
stays here so that the section numbers do not change. Chapter 06 §4.3 now
states the rule for every flavor:

- No selection opens, joins or waits for a membership transaction.
- On the thread that owns an uncommitted transaction of the composite, every
  selection call fails with the "membership transaction in progress" error,
  also a null clear. A transaction is uncommitted while an attached child
  waits for admission, a population is staged, or a transfer's detach has not
  committed. A failed add therefore needs no `Current` restore, and a hook
  that selects an admitted sibling or clears `Current` cannot survive the
  rollback.
- From the commit on, including the `CollectionChanged` publication, the
  owner thread's selection commits. A `CollectionChanged` subscriber can
  select in the composite that is publishing an add.

Before ADR-0173, C# and Python reused the transaction in both phases, and
TypeScript, Swift and Rust rejected the selection in both phases. An add to
the same composite from that subscriber's call chain stays rejected in every
flavor (ADR-0118).

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

Swift `Command.execute()` cannot throw
(`langs/swift/Sources/VMx/Commands/Command.swift:15`).

- CMDD-010: Swift tests only a throwing confirm, not a throwing inner command.
- CMDD-013: no Swift test runs a throwing inner command through the post-action.
  The spec has no Swift exemption.
- FORM-035 and FORM-036: `spec/20-form-vm.md` exempts Swift validators and
  `equals`. The exemption does not mention the deny snapshotter, which also
  cannot throw in Swift.

Other Swift operations that trap instead of throwing are listed under ADR-0009,
ADR-0037 and ADR-0053.

## 4. Tests parked as known defects

None. ADR-0173 returned the two ignored COMP-026 Rust tests to the suite.

## 5. Related records

- Rust parity backlog: [Rust parity status](2026-07-16-rust-capability-parity.md),
  §12.4.7 and §12.7–§12.12.
- The remaining Notes Showcase UX policies stay with the owner and are not
  listed here.
