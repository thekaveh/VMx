# 01 — Core concepts

This document introduces the VMx mental model. Subsequent sections (`02-lifecycle.md`
onwards) give precise normative definitions; this document is the orientation.

## 1. The viewmodel hierarchy

VMx defines the viewmodel types in the table below. They form independent
families rather than a single inheritance chain, as ADR-0018 records. The
forwarding decorators wrap an inner viewmodel and are not tree nodes of their
own.

| Family                                            | Role                                  | Children                        | Typical use                            |
| ------------------------------------------------- | ------------------------------------- | ------------------------------- | -------------------------------------- |
| `ComponentVM`                                     | leaf                                  | none                            | a single addressable VM with state     |
| `ReadonlyComponentVM`                             | leaf, immutable model                 | none                            | read-only view of a model              |
| `CompositeVM`                                     | container with selection              | `IList<VM>` + `Current`         | a tab strip, a navigation tree         |
| `GroupVM`                                         | container without selection           | `IList<VM>`                     | peers shown side-by-side               |
| `AggregateVM<VM1..VM6>`                           | fixed tuple of heterogeneous children | 1–6 typed slots                 | a screen composed of distinct sub-VMs  |
| `ForwardingComponentVM` / `ForwardingCompositeVM` | decorator                             | wraps another VM                | proxies, caching, instrumentation      |
| `HierarchicalVM<TModel, TVM>`                     | recursive tree VM                     | lazy/eager `IList<TVM>` subtree | file-system tree, org-chart, menu      |
| `FormVM<TM>`                                      | snapshot/revert edit VM               | none (embeds model snapshot)    | edit forms with approve/deny lifecycle |
| `AsyncResourceVM<T>`                              | leaf, one asynchronous value          | none                            | a panel that loads, retries or cancels |

Chapters 05 to 09 specify the first six families. Chapter 18 specifies
`HierarchicalVM`, chapter 20 `FormVM`, and chapter 23 `AsyncResourceVM`.

Opt-in primitives complement these families:

- **Rendering VMs** (chapter 16): `NotificationVM` and `ConfirmationVM` are
  render-side VMs with an auto-dismiss lifecycle, suitable for toast or banner
  UI.
- **State coordinator** (chapter 22): `DiscriminatorVM<TKey>` holds one active
  key, such as the active pane or route, with modal precedence.
- **Collection primitives** (chapter 21): `ServicedObservableCollection<T>`,
  `ObservableList<T>`, `ObservableDictionary<K1,K2,V>`, `PagedComposition<TVM>`
  and related helpers sit above the standard language collection types and
  integrate with the message hub and the paging capability.

Every VM is also a `ComponentVM` (inheritance / protocol composition per language). A
composite's children are themselves VMs and may be composites, components, etc.

### 1.1 Modeled and readonly variants

VMx uses "modeled" to describe two distinct patterns:

- **Modeled component** (`ComponentVM<M>`) — the VM holds a `Model` of type `M` as a
  settable property. Replacing the model (`vm.Model = m'`) fires `PropertyChangedMessage`.
- **Readonly component** (`ReadonlyComponentVM<M>`) — the VM is constructed with a model
  and the model is final. No setter is exposed.
- **Modeled composite** (`CompositeVM<M, VM>`) — `M` parameterizes the *children factory*
  rather than a top-level property; the composite does not expose `M` directly. See
  `06-composite-vm.md` for the full contract.

The shared idea is that `M` is the *domain shape* the VM (or its children) wrap; the
exact surface differs by VM family.

### 1.2 `Current` selection contract

Each `CompositeVM<VM>` has an optional `Current` child. The contract:

- At most one child is `Current` at any time.
- Setting `Current = c` requires `c ∈ children` (otherwise the operation MUST raise).
- Setting `Current = None` is legal at any time.
- The `Current` setter MAY dispatch asynchronously if the builder enabled
  `AsyncSelection(true)`.
- Child VMs observe their selection state via their `IsCurrent` property (raised
  through `PropertyChangedMessage`).

`GroupVM<VM>` has no `Current`. Children are peers.

### 1.3 `IComponentVM` baseline

Every viewmodel exposes:

- `Name : string` — immutable post-construction; an identifier for the VM.
- `Hint : string` — immutable post-construction; a human-readable hint. It
  defaults to the empty string.
- `Type : ViewModelType` — enum (`Component`, `ReadOnlyComponent`, `Aggregate`,
  `Group`, `Composite`); immutable.
- `IsCurrent : bool` — derived from parent's `Current` reference. Raised through
  property-change notification.
- `IsConstructed : bool` — equals `Status == Constructed`. Raised when `Status`
  changes.
- `Status : ConstructionStatus` — the lifecycle state. See `02-lifecycle.md`.
- `Parent` — an internal back-reference to the container (`CompositeVM` or `GroupVM`)
  that currently holds this VM as a child, or `null` when the VM is not a member of
  any container. It is **not** part of the public, consumer-settable surface and is
  **not** observable (a change to `Parent` does NOT publish a `PropertyChangedMessage`);
  it exists solely to back the selection predicates (`can_select` / `can_deselect` /
  `select` / `deselect`) and `IsCurrent`. The container sets it when the VM is added
  (`Add` / `Insert`, or wired as a child at build time) and clears it to `null` when
  the VM is removed (`Remove` / `RemoveAt` / `Clear`) or re-parented — see `05` §6.1
  for the precise contract and `06`/`07` for the container side. Reference
  implementations type it as a minimal internal parent interface
  (`IParentCompositeVM` in C#, `_ParentCompositeVM` in Python, `IParentVM` in
  TypeScript, `ParentVM` in Swift) exposing only the members the child needs for
  selection delegation, not the full container VM. Rust uses a type-erased weak
  `ParentHandle` whose selection operations are crate-internal.
- The lifecycle commands: `SelectCommand`, `DeselectCommand`, `SelectNextCommand`,
  `SelectPreviousCommand`, `ReconstructCommand`. Each is an `ICommand`-equivalent
  with appropriate predicates.

### 1.4 Shared VM collection capability

`CompositeVM<VM>` and `GroupVM<VM>` implement one public ordered child-
collection capability (ADR-0085). It contains lifecycle-aware add, insert,
remove, indexed remove, replace, clear, atomic move, count, indexed and iterable
reads, collection-change observation, and batch updates. Its idiomatic names
are `IVmCollection<VM>` (C# / TypeScript), `VmCollectionProto[VM]` (Python),
`VMCollection` (Swift), and `VmCollection<T>` (Rust).

Selection is intentionally layered as a second capability:
`ISelectableVmCollection<VM>` / `SelectableVmCollectionProto` /
`SelectableVMCollection` / `SelectableVmCollection<T>`. `CompositeVM`
implements it; `GroupVM` does not acquire a `Current` placeholder.

`move(fromIndex, toIndex)` changes ordering only. Both indices use the
pre-move `[0, Count)` domain and the child occupies `toIndex` afterward. Equal
indices are silent no-ops. Invalid indices raise before mutation. A successful
move emits one `Move` event containing the same child and both indices, or is
coalesced into the outer batch `Reset`. Identity, parent, lifecycle,
subscriptions, auto-construction count, and a composite's `Current` reference
remain unchanged. Chapters 06 and 07 define the container-specific details;
`COL-032..039` are normative.

Both containers also publish their collection changes to their own message hub
(spec v3.26, ADR-0142). Each effective local collection-change event is
followed by exactly one `CollectionChangedMessage` (chapter 21 §2.4) sent by the
container, with the same action, positions, and (in typed flavors) items as the
local event; replacement keeps each flavor's local decomposition. The local
event is delivered first. A batch publishes nothing inside its scope and one
`Reset` after the local `Reset` on outermost completion; a mutation that raises
no local event publishes nothing. An ownership transfer publishes the old
container's `Remove` before the new container's `Add`. Publication uses the
hub's ordinary `Send`, so hub transactions defer it (chapter 03 §3.3); a
disposed container publishes nothing, and a forwarding wrapper publishes
nothing of its own. Rust additionally publishes `PropertyChanged("Count")` when
the size changes (ADR-0085). `COMP-042..045` and `GRP-012..013` are normative.

A container sends no hub message once its disposal is requested, also when it
defers the disposal (chapter 06 §4.2, §4.3 rule 5). It checks after its local
subscribers return. So a local subscriber or an `OnCurrentChanged` callback
that disposes the container suppresses the hub message of the change it
observes, and the local event is still delivered. The result is the same
whether the disposal runs at once or is deferred. In a transfer whose old
container requests its own disposal before its `Remove` publication, the hub
receives only the new container's `Add`. Rust's `Count` message follows the
same rule (ADR-0190, `COMP-049`).

A failing local subscriber does not undo the committed change and does not
suppress its hub message. The container still sends exactly one
`CollectionChangedMessage` for the change. C# and Python then rethrow the first
failure, and a local failure takes precedence over a later hub failure.
TypeScript reports the failure through rxjs, and the call returns normally.
Rust containers deliver the local event through
`ObservableMembershipSource::subscribe_membership`; Rust catches a panicking
local subscriber, and the call returns normally. Swift local subscribers cannot
fail (ADR-0171). Chapter 21 §2.5 applies the same rule to the hub-publishing
collections.

The failing subscriber does not stop the delivery to the other local
subscribers. Each local subscriber receives the change once, and each
completion observer completes at disposal. No subscriber is detached, and C#
and Python rethrow the first failure only after the hub send (chapter 03 §3.6,
ADR-0191).

### 1.5 Cross-language naming

The five active flavors share the same conceptual contracts and the complete
conformance catalog. Accepted language adaptations remain, so catalog
completeness does not claim member-for-member API identity. Identifier casing
follows the per-language idiom of ADR-0006. The same logical type appears under
the following names:

| Concept            | C#                        | Python             | TypeScript                | Swift                     | Rust                    |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- | ----------------------- |
| Unmodeled VM       | `ComponentVM`             | `ComponentVM`      | `ComponentVM`             | `ComponentVM`             | `ComponentVm`           |
| Modeled VM         | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        | `ComponentVm<M>`        |
| Status property    | `Status`                  | `status`           | `status`                  | `status`                  | `status()`              |
| Builder entrypoint | `Builder()`               | `builder()`        | `builder()`               | `builder()`               | `builder()`             |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` | `NullMessageHub::hub()` |

C# uses PascalCase, Python and Rust methods use snake_case, TypeScript and
Swift use camelCase. C# and Rust keep the same public type name for modeled and
unmodeled components (`ComponentVM<M>` / `ComponentVm<M>`). Python, TypeScript,
and Swift expose a separate `ComponentVMOf` type because their generics syntax
cannot overload an unparameterised name.

Throughout this spec, statements about `ComponentVM<M>` apply equally to
`ComponentVMOf[M]`, `ComponentVMOf<M>`, and `ComponentVm<M>` unless explicitly
called out. ADR-0009 catalogs the documented cross-flavor divergences, and
[`langs/swift/README.md` §5](../langs/swift/README.md) summarizes the Swift
conformance suite and its divergences.

## 2. Dependency philosophy

Every VM receives two cross-cutting services:

- `IMessageHub` — the pub/sub hub for `IMessage` events.
- `IDispatcher` — exposes `Foreground` and `Background` schedulers. C#, Python,
  and TypeScript expose them as Rx schedulers. Swift (`scheduleForeground` /
  `scheduleBackground`) and Rust (`dispatch` / `dispatch_background`) expose
  closure-based scheduling methods with no Rx scheduler type.

These are injected via constructor (and via the builder's `Services(hub, dispatcher)`
call for fluent users). VMx does NOT register a global locator. See ADR-0001 and
ADR-0003 for the rationale.

The `IMessageHub` MAY be shared across many VMs or scoped to a sub-tree; that is
the host application's choice. The conformance tests verify that VMs publish to the
hub they were given (`HUB-001`).

## 3. Concurrency philosophy

VMx is **thread-aware but not thread-bound**:

- It does not own a UI thread.
- It uses the dispatcher's foreground and background targets
  (`IDispatcher.Foreground`, `IDispatcher.Background`) to dispatch work. These
  are Rx schedulers in C#, Python, and TypeScript, and closure-based methods in
  Swift and Rust.
- Subscribers that need to observe events on a specific thread (e.g., a UI thread)
  MUST inject an `IDispatcher` whose `Foreground` scheduler dispatches there.

The default `IDispatcher` in each language uses a foreground target and a
separate background target:

- C#: `SynchronizationContextScheduler` for foreground, `TaskPoolScheduler` for
  background.
- Python: `AsyncIOThreadSafeScheduler(loop)` for foreground, `ThreadPoolScheduler`
  for background.
- TypeScript: `queueScheduler` (synchronous trampoline) for foreground,
  `asyncScheduler` (macrotask) for background.
- Swift: `DefaultDispatcher` runs foreground work on the main queue (inline when
  the caller is already on the main thread, else `DispatchQueue.main.async`) and
  background work on a global `.userInitiated` queue.
- Rust: `DefaultDispatcher` runs foreground work on a dedicated `vmx-foreground`
  worker thread and background work on a dedicated `vmx-background` worker
  thread.

See `11-threading.md` for the full contract.

## 4. Disposal invariant

Every public VMx-owned type that exposes `Dispose()` / `dispose()` MUST make
that operation safe and idempotent from every state in which the type permits
disposal. The first call claims terminal teardown; later and re-entrant calls
return normally without repeating stream completion, terminal notification,
cancellation, owned-resource cleanup, or other observable side effects.

For types documented as thread-safe, racing dispose callers MUST atomically
claim teardown so terminal work still occurs at most once. This does not make
otherwise single-threaded types thread-safe.

Parent disposal retains each family's specified ordering. A child reachable
through more than one cascade or host teardown path has one observable terminal
transition because its own disposal is idempotent.

The invariant applies only to disposal itself. Each type keeps its documented
post-dispose behavior: calls may be inert, last values may remain readable,
in-flight waiters may resolve with a safe result, or explicitly documented
operations may raise. Disposal also does not change ownership; non-owning
wrappers and serviced collections remain non-owning. The complete public
inventory and per-type behaviors are published in the
[Disposal Contract](../docs/content/primitives/disposal-contract.md). See
ADR-0084 and `DISP-001..006`.

## 5. Conformance

Chapter 12 §30 states the cross-cutting `DISP-001` to `DISP-006` IDs. They
check the §4 invariant for VM cascades, commands, hubs, interaction owners,
reactive helpers, and collection and projection helpers. The Conformance
section of each owning chapter maps them to its rules.

## 6. What this spec is not

This spec does not specify:

- The wire format of messages (no serialization).
- The lifetime of `IMessageHub` (the host decides).
- Whether multiple `IMessageHub` instances coexist. Multiple instances MAY be created.
- UI-framework specifics like XAML binding behaviors, accessibility, or rendering.
- The exact reactive library version each flavor uses (each flavor's `README.md`
  documents that). C#, Python, and TypeScript use Rx libraries, Swift uses
  Combine, and Rust uses VMx-owned stream types with no Rx library.
