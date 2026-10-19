# ADR 0149 — Spec prose corrections for chapters 02 to 23

- **Status:** Accepted
- **Date:** 2026-10-17
- **Spec version:** 3.29.0
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md)
  (cross-flavor divergence catalogue, fluent `Confirm` overload),
  [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic names),
  [ADR-0059](0059-swift-leaf-area-divergences.md) (§2.4, Swift protocol names),
  [ADR-0121](0121-current-five-flavor-contract-clarifications.md) (current
  prose names all five flavors),
  [ADR-0148](0148-spec-prose-corrections-maintenance.md) (the same correction
  for chapters 00 to 17)

## 1. Context

A maintenance review compared the prose of chapters 02 to 23 with the code in
all five flavors. It found three kinds of problems:

- Prose that disagreed with the code:
  - Chapter 04 §9.1 and ADR-0009 showed Python and TypeScript `confirm` as a
    command method. Both ship `confirm(command, delegate)` as a free function.
  - Chapter 04 §4.2 said the `ModeledCrudCommands` commands MUST have a
    current-changed trigger. Chapter 06 §7 makes the trigger RECOMMENDED, and
    the Python and TypeScript helpers accept none.
  - Chapter 16 §8.1 built a `CompositeVM<Notification, NotificationVM>`. No
    flavor can build it, because `NotificationVM` is not a component VM. The
    recipe also passed the notification hub to `Services(IMessageHub, …)`.
  - Chapter 16 §5 sent every confirmation through `IDialogService.Confirm`,
    which contradicted §1.1, §4 (`make_confirm`), and §7 (`ConfirmationVM`).
    It also called the hub fire-and-forget, although `Post` returns an
    awaitable reaction. Chapter 19 §5 had the same rule of thumb.
  - Chapter 13 §4 gave Python and TypeScript tree types as `IComponentVM` and
    the TypeScript module as `vmx/tree`. Chapter 16 gave the TypeScript
    notifications path as `vmx/notifications`. The package is `@thekaveh/vmx`.
  - Chapter 14 Rule 5 said only Rust drops the `I` prefix. Swift also drops it.
    §2.6 called `SearchableState` a predicate builder over `IFilterable`; no
    flavor implements `IFilterable` on it.
  - Chapter 21 §2.3.3 said no serviced collection has a `Count` channel. The C#
    collection derives from `ObservableCollection<T>` and raises `Count` and
    `Item[]` on its local `PropertyChanged` event. §6.2 named
    `AutoConstructOnAdd` as a C# property; it is a constructor parameter, and
    Rust uses `with_auto_construct_loader`.
  - Chapter 03 said a `Create` factory exists in every language. Swift uses
    initializers and Rust uses plain structs.
  - Chapter 23 §3 said construction requires a hub and dispatcher. Rust
    `AsyncResourceVm::new(name, loader)` supplies both.
  - Chapter 19 §2.1 said every flavor without a source-compatible `Present`
    ships a fallback helper; only C# does. It also said "all four methods"
    after it listed five.
  - Chapter 18 `HIER-015` described a required triple. C#, TypeScript, and
    Swift builders also require the VM factory; Python's is optional and Rust
    has none.
- Per-flavor lists that did not name all five flavors (ADR-0121).
- Prose that states behavior Rust does not have, with no Rust note.

## 2. Decision

Correct the prose as the code ships it:

- Chapter 02 §2.2: Rust replaces each hook with a closure through public
  `on_construct`, `on_destruct`, and `on_dispose` methods.
- Chapter 03: the hub stream is Rx in C#, Python, and TypeScript, Combine in
  Swift, and the VMx-owned stream in Rust (introduction, §3, §3.1, §4). Message
  construction is listed per flavor (§2.1, §2.2). Rust property names are
  snake_case. Rust `NullMessageHub::hub()` returns a new disposed hub on each
  call (§6).
- Chapter 04: §4.2 aligns with chapter 06 §7. §9.1 shows `confirm` as a free
  function in Python, TypeScript, and Swift and as a method in Rust. §9.4
  gives the Swift, TypeScript, and Rust `DecoratorCommand` argument forms.
  §10.3 names the Swift `CancellationError` and Rust `VmxError::Cancelled`.
  ADR-0009 corrects the same `confirm` text and the notifications path.
- Chapter 13: iteration is lazy in C#, Python, and TypeScript; Swift and Rust
  materialize (§2, §5). §4 corrects the Python and TypeScript types and the
  TypeScript module.
- Chapter 14: Rule 5 says Swift protocols and Rust traits drop the `I` prefix.
  §2.6 describes `SearchableState` as a separate helper.
- Chapter 15 §2: Swift `canSet:` / `setAction:` and Rust `with_write_back`.
- Chapter 16: the TypeScript subpath is `@thekaveh/vmx/notifications`. §2 lists
  the Rust `post`, `post_notification`, `post_with_waiter`, `pending`,
  `pending_stream`, and `pending_snapshots` methods. §5 sends in-app
  confirmations through the hub (`make_confirm`) and modal confirmations
  through `IDialogService.Confirm`. §8.1 is a language-neutral sketch that
  keeps `NotificationVM` instances in an application-owned list driven by
  `Pending`, and passes the notification hub to each `NotificationVM`, not to
  `Services`.
- Chapter 18: Swift binds `TVM: AnyObject`. The eager option and the cycle
  errors are listed for Swift and Rust (§4, §7, `HIER-008`, `HIER-018`).
  `HIER-015` lists the required fields and the validation error per flavor.
- Chapter 19: §2.1 describes the `present` placement per flavor and says "all
  five methods". §5 aligns its rule of thumb with chapter 16 §5.
- Chapter 20: Rust uses `Clone` for the default snapshot and `PartialEq` for
  dirty tracking; Swift's designated initializer takes `equals:`, and the
  `Equatable` convenience initializer and the builder default it to `==`.
- Chapter 21: the C# `Count` exception (§2.3.3); the Rust message
  `sender_name` field (§2.4); Swift and Rust in §3.4, §3.6, §4.1, and §5.1;
  the per-flavor auto-construction option (§6.2).
- Chapter 23 §3: Rust default services.
- Open Rust gaps are recorded where the chapter states behavior Rust does not
  have:
  - Notifications are not behind a Cargo feature (chapter 16).
  - `NullNotificationHub` has no hub trait and no `resolve` (chapter 16 §3).
  - `DialogService` has no `present` and Rust has no modal-capable service
    trait; only `NullDialogService` has an inherent `present` (chapter 19).
  - `active_changed()` messages carry no key; consumers use
    `active_key_changes()` (chapter 22).
  - `ObservableMultiDictionary` requires a hub, returns snapshot keys, and has
    no local event, indexer, or `TryGetValue` (chapter 21 §4.2, §4.6).
  - `ObservableList` has no granular item streams and no value remove
    (chapter 21 §3.2).
  - `HierarchicalVm<M>` has no `TVM` parameter (chapter 18 §2).
  - The `HierarchicalVm` `TreeNode` implementation never reports collapse, so
    `walk_expanded` does not stop at a collapsed node (chapter 13 §6).

The change adds no conformance ID. It is editorial except for these follow-up
alignments, where code was brought to behavior the spec or the other flavors
already required, and the prose now states it: Python empty slice mutations
emit nothing (chapter 21 §2.10), Rust `search()` notifies (SRCH-005), and the
Python tree helpers use the public `ComponentVMProto` (chapter 13). With
auto-construct on, every flavor now constructs and joins a child added while
its container is still `Constructing` (chapter 06 §5.1, chapter 07 §4), as
chapter 02 §6 requires: before, the container reached `Constructed` with that
child still `Destructed`.

## 3. Consequences

- The corrected sections agree with the code and satisfy ADR-0121.
- Chapter 04 §4.2 no longer says MUST for the `ModeledCrudCommands` trigger. This
  is not a new relaxation: chapter 06 §7 and ADR-0049 already made the trigger
  RECOMMENDED, and the chapter 04 sentence contradicted them.
- Follow-up corrections in the same change, by chapter:
  - Chapter 02 lists which Rust VM types have the hook methods. Open gaps:
    `HierarchicalVm` and `ModeledCompositeVm` have no hook methods, and
    `ForwardingCompositeVm` reaches them only through `inner()`. Chapter 02 §6
    (and chapter 06 by reference) says which flavors drive container children
    sequentially.
  - Chapter 04 §4 says a trigger fires `CanExecuteChanged` and consumers re-read
    `CanExecute`. The chapter 04 §4.1 C# trigger recipe matches
    `IPropertyChangedMessage<IComponentVM>`. VMs publish
    `PropertyChangedMessage<IComponentVM>`, and the record type is invariant.
  - Chapter 06 records the Rust `FilteredCompositeVm` `Changed` and
    `ModeledCrudCommands` confirmation gaps. It separates the two Rust
    constructors: only `with_current_changed` takes the trigger. It says Rust
    `search()` notifies, as the explicit `Search()` of the other flavors does
    (SRCH-005). Chapter 06 §8 drops `SearchTermChanged` from the
    `SearchableState` shape. No flavor exposes the debounced term as a public
    stream; the debounce is internal, and consumers observe `Filtered`.
    Chapter 06 also records the Rust membership transaction held across
    publication (`COMP-026`) and the missing Rust local collection-change
    stream (`COMP-041`/`COMP-042`).
  - Chapter 08 says Swift slot factories cannot throw.
  - Chapter 09 §2 records that the TypeScript and Rust forwarding composites
    cannot be children of a container.
  - Chapter 10 records that a non-modeled Rust `ComponentVm<()>` needs
    `.model(())`. It says the Rust builders default `Hint` to `Some("")` and
    records the `ModeledCompositeVm` hint and identity gap.
  - Chapter 11 says the containers of every flavor wait for background children
    at the status level and that the Rust containers expose
    `background_errors()`.
  - The catalog (chapter 12) scopes `COL-031` and the `HUB-013` cross-hub
    clauses to the flavors that can satisfy them. It words `FORM-013` and
    `CMDD-009` per flavor.
  - Chapter 13 gives the Python helper types as the public `ComponentVMProto`,
    which the helpers now accept and return, instead of the private
    `_ComponentVMBase`. It records that Rust `walk` does not descend into a
    `CompositeVm`.
  - Chapter 16 §8.1 states the construction of the Rust `NotificationVm`.
  - Chapter 18 says Swift's `addChild` returns the cycle error as `.failure`,
    while `reparentChild` throws it. Chapter 18 §3 and §5 state that destruct
    does not cascade and that invalidation detaches children without a `Parent`
    message, as every flavor implements. Chapter 18 §4 says the eager option
    applies per node, as every flavor implements it, so the whole tree is eager
    when every node is.
  - Chapter 19 §1 and its §5 diagram no longer call the notification hub
    fire-and-forget.
  - Chapter 21 §5.5 records that Rust `PagedComposition` does not observe its
    source (`COL-031`). Chapter 21 §2.10 says an empty Python slice mutation
    emits nothing, matching TypeScript `splice`; the code now does so.
- The Rust gaps stay open. Each is recorded, not closed; closing one changes the
  public Rust surface and needs its own decision and change.
- The chapter 16 §8.1 recipe stays a composition pattern, not a new primitive.
