# 1. Heimdall Upstream Candidates: Verification and Incorporation Plan

## 1.1. Status

| Field        | Value                                                                                                                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Status       | Proposed. It awaits the owner decisions in §1.12. No item is approved for implementation.                                                                                                                          |
| Date         | 2026-10-20                                                                                                                                                                                                         |
| Input        | "VMx upstream candidates", the catalogue of VMx gaps written by the Heimdall frontend team: 4 kit classes, 19 Vue binding files, owner-aware builders, 11 further proposals, 4 tables of lessons and 6 open items. |
| Baseline     | `develop` at `50ac3565` (spec 3.29.0). Published `@thekaveh/vmx` 3.30.0 (tag `typescript-v3.30.0`) and `@thekaveh/vmx-react` 0.1.1.                                                                                |
| Predecessors | `2026-05-27-vmx-absorption-audit.md`, `2026-06-13-vmx-absorption-audit-followup.md`, and the nnx-studio catalogue #593, triaged and closed on 2026-10-12.                                                          |
| Effect       | None. This document changes no behavior. Each adopted item still needs its own ADR, conformance IDs and PR (AGENTS.md §4).                                                                                         |

## 1.2. Summary

Heimdall is an operations dashboard with a Vue 3 and TypeScript frontend. Its view-model layer has about 60 files and 15,000 lines on `@thekaveh/vmx` 3.30.0. Its catalogue proposes moving app-agnostic code into VMx and changing VMx where its idioms cause repeated code. Every factual claim in the catalogue was checked against the TypeScript source, the published package, the spec, the ADRs, the other four flavors and the GitHub issues (§1.3).

**Verification.** Of 79 checked claims, 47 hold, 19 hold in part, 8 are wrong and 5 cannot be checked without Heimdall's code (§1.5.7). Of the 47 that hold, 19 describe a decision that the spec or an ADR records, not an omission.

**The main corrections to the catalogue:**

1. `reloadCommand` does not ignore a call while another load runs. It supersedes a load that `loadCommand` or `reload()` started; only its own execution in flight blocks it (spec 23 §4). A superseded or failed `reload()` resolves normally, so latest-wins needs no rejection handling.
1. The three callbacks in P11 never run before the constructor returns, and capturing `this` compiles and works. `currentSelector` already receives the composite. The callback that does run inside the constructor, `modeledHinter`, is not in the catalogue.
1. `declare<T>`, `derive<T>` and a compare-and-assign helper repeat designs that the spec rules out (spec 05 §2.3, ADR-0040, ADR-0083 §4.1 and §4.4) and that the resolution of #78 and the triage of #100 and #593 already declined.
1. Silent cleanup errors, the missing hierarchical dispose cascade, the on-demand-only resource, the conservative retention default and a predicate exception that reads as `false` are normative decisions: spec 02 §2.3 and DISP-009; spec 18 §3 and ADR-0105; ADR-0100 §2.7 and §4.6; spec 23 §8; spec 04 §2.
1. The proposed `ownedBy` does not remove the silent omission it targets. The proposed `owner` constructor option would dispose children parent-first, against LIFE-013, and would create a second owner that ADR-0107 transfers cannot see.
1. "VMx has `ExpandableState` only" overlooks the visible-domain cursor of `FilteredCompositeVM`, `CompositeVM.current`, `ModalVM`, `DiscriminatorVM` and the deferred #619 and #620.
1. The Vue proxy failure (L1) happens only when a parent holds the view-model in `ref()`, `reactive()`, `data()` or a store; a plain prop stays raw. The double trigger (L2) is real, and the #342 fix introduced it.
1. The accordion fold cannot materialize siblings through `parent.children`. Only reads of each sibling's own `children` or `isLeaf` do.

**Verification also found VMx defects that the catalogue does not report** (§1.9). The worst: `own()` on a TypeScript forwarding decorator registers into state that is never released, and Python raises instead. A docs page says a hierarchical node owns its children, against spec 18 §3.

**Recommended dispositions** (§1.7):

| Disposition                             | Items                                                                                                                                                                                                                                                                   |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Adopt as a normative five-flavor change | a tree-level selection helper; `ExpandableState` commands; a supported child-transition helper; an opt-in reverse child order for containers; a rule for `own()` on forwarding decorators; a construct-scope `whileConstructed` helper, after a pilot                   |
| Adopt as a non-normative package        | `@thekaveh/vmx-vue`, mirroring `@thekaveh/vmx-react`, behind the gates of #394                                                                                                                                                                                          |
| Adopt as a flavor-level change          | an optional `hint` in the raw constructors of TypeScript, Python and C#                                                                                                                                                                                                 |
| Fold into an existing issue             | keyed pages into #618; reload policy into #376; a value accessor into #378; predicate diagnostics into #372; a services bundle into #144; polling into #388; command-builder ownership into #371; focus and key handling into #413 and #620                             |
| Open one new design issue               | a cross-flavor clock and test-scheduler contract with a `DelayedTask` helper. Heimdall is the second consumer after #593 item 13.                                                                                                                                       |
| Fix or document now                     | the Vue recipe (L1, L2 and an SSR leak); the docs contradictions; a recipe for every declined item                                                                                                                                                                      |
| Decline                                 | navigation messages in core; Popup, Menu and Tooltip classes; `TransientStateVM`; declared and derived properties; property bubbling; instance arguments for callbacks; a `parent` option; DOM-behavior bindings; resource options that couple loading to the lifecycle |

**Sequencing** (§1.10). Phase 0 fixes and documents, with no behavior change. Phase 1 (spec 3.30.0) adds the small items with the strongest evidence. Phases 2 to 4 follow design issues and pilots. The Vue package has its own track.

## 1.3. Method

- Six parallel read-only research passes covered:
  - the architecture and abstraction map;
  - ownership and lifecycle: O1 to O15, P2, P3;
  - options, properties and callbacks: P4 to P6, P11, P12, L8;
  - async resources, commands and time: K4, P7 to P9, L6, L7, L17;
  - composites, trees, keyed pages and popups: K1 to K3, P10, L3 to L5;
  - the Vue bindings: V1 to V18, L1, L2.
- Each claim was checked at `develop` and at the `typescript-v3.30.0` tag. The changes between them do not alter any verdict.
- Runtime probes ran against the published npm package `@thekaveh/vmx@3.30.0`. They covered disposal order, the hierarchical cascade, composite `current`, resource reload, predicate exceptions and `own()` on forwarding decorators.
- The Vue probes used vue 3.5.43, solid-js 1.9.16 and svelte 5.57.1. The type probes used TypeScript 6.0.3 under the repo's strict configuration. The async claims were also run in Python.
- C#, Swift and Rust were checked by reading the source.
- Every decisive spec and ADR sentence quoted below was re-read at the cited place.
- Heimdall's code is not available. Its counts, such as 206 `own()` calls or 37 holders, are reported evidence only. Where a claim depends on Heimdall code, only the VMx mechanism was checked.

Each candidate was judged on seven questions:

1. Is the gap at framework level, or at application level?
1. Does it fit the scope of spec 00 §1 and §2?
1. Does it contradict an ADR? If so, is there new evidence that would justify a superseding ADR?
1. Can all five flavors express it idiomatically (ADR-0006)?
1. What does it cost in code, conformance IDs and documentation?
1. Is it backward compatible (README §6.1)?
1. Does an existing primitive or recipe already cover it?

## 1.4. VMx Structure and Abstraction Hierarchy

### 1.4.1. Layers and Governance

| Layer           | Content                                                                                                                                                                                                                                                                                                                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Spec (`spec/`)  | 24 chapters (`00` to `23`), 149 ADRs, 4 shared fixtures, 1 non-normative consumer schema, and proposals. Version 3.29.0. 430 conformance IDs: 425 library IDs and 5 THEME scenario IDs.                                                                                                                                                                              |
| Core libraries  | C# `langs/csharp/src/VMx`, Python `langs/python/src/vmx`, TypeScript `langs/typescript/src`, Swift `langs/swift/Sources/VMx`, Rust `langs/rust/src`. Directories mirror the chapters. Rust has no inheritance: VM types embed a crate-private `ComponentCore` and implement the `VmNode` trait.                                                                      |
| Opt-in surfaces | Notifications (chapter 16) as a C# assembly, Python and TypeScript sub-paths, a Swift folder and Rust exports. The C# DI extension. The TypeScript-only, non-normative `testing`, `devtools` and `conformance` sub-paths.                                                                                                                                            |
| Host adapters   | `packages/react` (`@thekaveh/vmx-react` 0.1.1). It is non-normative and independently versioned, with no ADR and no conformance IDs; its evidence is the pilot ledger `docs/maintenance/2026-08-10-vmx-react-consumer-pilots.md`. Vue, Svelte and Solid exist only as executed recipes in `examples/typescript/integration-recipes` and `docs/content/integration/`. |
| Examples        | Four flagship Notes showcases (Avalonia, Textual, React, SwiftUI), a Rust Ratatui showcase, and small demos.                                                                                                                                                                                                                                                         |
| Docs            | One source (`docs/content` and `docs/manifest.yaml`) published to the repo, the site and the wiki.                                                                                                                                                                                                                                                                   |
| Gates           | Any spec change needs a new ADR. A new conformance ID needs a marker in all five flavors in the same PR. The coverage gate requires 425 of 425 in every flavor, and the execution gate requires a passing test for every ID. Per-flavor CI and the docs check also run.                                                                                              |
| Versioning      | Independent SemVer per flavor. An additive spec minor bumps every flavor's minor; a spec major forces a major in every flavor (README §6.1).                                                                                                                                                                                                                         |

### 1.4.2. View-Model Families

```text
ComponentVMBase                abstract lifecycle base; Rust: ComponentCore + VmNode          ch02, ch05
├── ComponentVM                leaf without a model                                           ch05
├── ComponentVMOf<M>           leaf with a model                                              ch05 §3
├── ReadonlyComponentVMOf<M>   leaf with a fixed model                                        ch05 §4
├── CompositeVMBase<VM>        owning container with one current child                       ch06
│   ├── CompositeVM<VM>
│   └── CompositeVMOf<M, VM>   children projected from child models
├── GroupVM<VM>                owning container without selection                             ch07
├── AggregateVM1..6            typed slots filled by factories at construct                   ch08
├── HierarchicalVM<TModel,TVM> recursive tree; coordinates eager construct, owns no lifetimes  ch18
├── AsyncResourceVM<T>         one cancellable load with an immutable state                   ch23
└── ForwardingComponentVM<M>   decorator that shares the wrapped VM's ownership identity      ch09

Coordinators and projections (not ComponentVMBase subclasses in TypeScript):
  ForwardingCompositeVM<VM> (ch09), FilteredCompositeVM<VM> and ScoredFilteredCompositeVM<VM> (ch06 §9),
  FormVM<TM> (ch20), DiscriminatorVM<TKey> (ch22), ModalVM<T> (ch19), NotificationVM and ConfirmationVM (ch16)
```

| Family                   | Owns child lifetimes                                                | Iterable               | Child construct, destruct, dispose                                                                                         |
| ------------------------ | ------------------------------------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Leaf components          | No. They own resources through `own()`.                             | No                     | None. Children held in fields are the author's job.                                                                        |
| `CompositeVM`, `GroupVM` | Yes, as the single owner, with atomic transfer (ADR-0107, ADR-0118) | Yes                    | Construct and destruct walk the children, wait for background children and roll back on failure. Dispose goes depth-first. |
| `AggregateVM1..6`        | Yes, through fixed slots; an already-owned child is rejected        | Through `components()` | Factories run on every construct; reconstruct replaces the slots (AGG-007). Dispose goes depth-first.                      |
| `HierarchicalVM`         | No (spec 18 §3, ADR-0105)                                           | Yes                    | Only eager construct cascades. Destruct and dispose never do.                                                              |
| `AsyncResourceVM`        | None                                                                | No                     | It never loads at construct. Dispose cancels the load.                                                                     |
| Coordinators             | None (`DiscriminatorVM`, `ModalVM`, `FormVM`, the filtered views)   | No                     | Each owns only its own subscriptions.                                                                                      |

### 1.4.3. Other Abstractions

- **Lifecycle (ch02).** `ConstructionStatus` has five states and a shared transition fixture. Background construction, transactional rollback (LIFE-014) and deferred terminal cleanup inside hooks (LIFE-015). Ordered disposal: parent hook, owned resources in LIFO order, stream completion, built-in commands (ADR-0129).
- **Messages and the hub (ch03).** `PropertyChanged`, `ConstructionStatusChanged`, `CollectionChanged`, `TreeStructureChanged` and `FormReverted`. Rust uses a closed `Message` enum with a payload-less `Custom` variant. Hub transactions are lossless deferral, not coalescing (ADR-0082). Helpers: `whenPropertyChanged` (informative), `subscribeValue` (normative, SUBV) and the TypeScript-only raw-message predicates (ADR-0094).
- **Services.** `IMessageHub`, `IDispatcher` (foreground and background schedulers in C#, Python and TypeScript; closures in Swift and Rust) and a null object for each (ADR-0017). There is no global locator (ADR-0003).
- **Commands (ch04).** `ICommand`, `ICommandOf<T>` and `IAsyncCommand`. `RelayCommand`, `RelayCommandOf<T>` and `AsyncRelayCommand` with immutable builders. The wrappers `CompositeCommand`, `DecoratorCommand` and `ConfirmationDecoratorCommand` never own their inner commands (ADR-0134). Fluent helpers: `confirm`, `precedeWith`, `succeedWith`, `wrapWith`. CRUD helpers.
- **Capabilities (ch14).** 22 opt-in micro-interfaces (ADR-0057) and the helpers `ExpandableState` and `SearchableState`.
- **Collections (ch21).** `ObservableList`, `ObservableDictionary`, the serviced and keyed serviced collections, `PagedComposition`, `TokenPagedComposition`, `AggregateChangeStream` and the `IVmCollection` capability. None of them owns its items.
- **`DerivedProperty` (ch15)** is standalone, with no hub dependency (ADR-0011).
- **Also:** dialogs (`IDialogService`, `ModalVM`, ch19), localization (ch17) and tree utilities (`walk`, `find`, `walkExpanded`, ch13).

### 1.4.4. Invariants a New Abstraction Must Respect

1. **Flat hierarchy.** One abstract base; concerns layer in through opt-in interfaces (ADR-0018). Core VMs advertise only the lifecycle capabilities (ch14 rule 2).
1. **Constructor injection.** Hub and dispatcher are injected explicitly, with no ambient lookup (ADR-0003, ch01 §2, ch11).
1. **Idiomatic surfaces.** Any divergence beyond casing or idiom needs an ADR (ADR-0006).
1. **One disposal-lifetime registry.** `own()` is LIFO, isolates failures, and cleans at once after disposal. Per-construct resources stay explicit in the hooks (ADR-0041, refined by ADR-0090). ADR-0041 §4 leaves one door open: a `RegisterPerConstruct` helper.
1. **Disposal is safe and idempotent.** It reports the first hook or child failure while owned-resource failures stay swallowed (ADR-0084, ADR-0108, ADR-0129). Every disposable type joins the disposal inventory (`docs/content/primitives/disposal-contract.md`).
1. **Single-owner, transactional membership.** Transfers are atomic; re-entrant structural mutation is rejected; a wrapper shares the wrapped VM's ownership identity (ADR-0107, ADR-0118, ADR-0124).
1. **Callback safety.** Consumer callbacks never run under a state guard (ADR-0117).
1. **Properties.** Plain fields and one notification helper; no property wrappers, decorators or compare-and-assign helpers (spec 05 §2.3, ADR-0040, ADR-0083).
1. **One reactive primitive per flavor.** Adapters translate VMx notifications into the host's primitive under the invariants of ADR-0101 §2.4.
1. **Builders are immutable.** `Build()` validates, and the options form routes through the builder (ch10, BLD-006, ADR-0112).
1. **Capability granularity is fixed.** A VM advertises exactly the verbs it supports (ADR-0057). `AggregateVM` arity holds at 6 (ADR-0058).
1. **Scope.** UI bindings, navigation routing, persistence and serialization are application concerns (spec 00 §2).

### 1.4.5. Base-Class Access by Flavor

This table decides how any new protected member can be expressed.

| Member              | C#                                          | Python                       | TypeScript                                                 | Swift                           | Rust                                       |
| ------------------- | ------------------------------------------- | ---------------------------- | ---------------------------------------------------------- | ------------------------------- | ------------------------------------------ |
| Resource ownership  | `protected Own`                             | `_own` (convention)          | `protected own`                                            | `open func own` (public)        | `pub fn own` on each VM type               |
| Notification helper | `protected NotifyPropertyChanged`           | `_notify_property_changed`   | `protected _notifyPropertyChanged`                         | public `_notifyPropertyChanged` | `notify_property_changed`                  |
| Dispatcher          | `private protected _dispatcher`             | `_dispatcher`                | `protected get _dispatcher`                                | `public let dispatcher`         | none                                       |
| Child transitions   | `protected TransitionChildrenAsync`         | `_transition_children`       | `protected _transitionChildren` (develop only, unreleased) | internal                        | `pub(crate)`                               |
| Walk hook           | `IEnumerable` or internal `IAggregateSlots` | `__iter__` or `components()` | `Symbol.iterator` or `components()`                        | internal `_TreeContainer`       | `TreeNode::children_nodes`, same type only |

### 1.4.6. Where Each Kind of Addition Goes

| Addition                 | Spec and governance                                                                                                                                                                                             | Source per flavor                                                                                                     |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| New VM type              | A section in its family's chapter or a new chapter 24; ADR-0150 onward; IDs under an existing or new prefix. Reuse `ViewModelType.Component`, because a new enum member breaks Rust matches and Swift switches. | `src/<area>/` in TypeScript, C#, Python and Swift; a Rust module that implements `VmNode` if the type can be a child. |
| Helper or state object   | Chapter 14, 15, 21, 22 or 23; one disposal-inventory family                                                                                                                                                     | `state/`, `capabilities/`, `collections/` or `properties/`; a Rust module                                             |
| New message type         | Its owning chapter, listed in ch03 §2                                                                                                                                                                           | A Rust `Message` variant is source-breaking; `Custom{name}` carries no payload.                                       |
| Option on an existing VM | Chapter section plus ch10 §3 and §4                                                                                                                                                                             | A builder setter and `create(options)` routing in all five flavors                                                    |
| Protected base member    | ch02 §2.2 to §2.3, or ch05 §2                                                                                                                                                                                   | Per §1.4.5. Forwarding decorators must delegate it (ADR-0090).                                                        |
| Framework adapter        | Outside `spec/`; no IDs. A pilot ledger in `docs/maintenance` and the ADR-0101 §2.4 checklist.                                                                                                                  | `packages/<host>/`, mirroring `packages/react` and its CI, release and smoke tooling                                  |

The next free numbers are chapter 24, ADR-0150, `spec/HISTORY.md` §39 and chapter 12 §33. An additive normative minor moves spec 3.29.0 to 3.30.0, C# and Python to 3.30.0, TypeScript and Swift to 3.31.0, and Rust to 0.36.0.

## 1.5. Claim Verification Ledger

Verdicts: **Confirmed**, **Partial**, **Refuted**, **Not verifiable**. "By design" marks a confirmed gap that the spec or an ADR decided. Section numbers in the headings refer to the catalogue. Paths without a root are under `langs/typescript/src/`.

### 1.5.1. View-Model Kit (Catalogue §2.1)

| ID  | Claim                                                                                                                                  | Verdict                  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Related                                                                                                                                                                              |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| K1  | VMx has no navigation-intent message.                                                                                                  | **Confirmed**, by scope  | No flavor has one. Framework messages are listed in ch03 §2, ch18, ch20 and ch21. App-defined messages work in C#, Python, TypeScript and Swift. Rust has only the payload-less `Message::Custom` (`langs/rust/src/runtime.rs:509-532`).                                                                                                                                                                                                                 | Spec 00 §2: "Navigation routing, persistence, serialization. These are application concerns". #403 is deferred.                                                                      |
| K2  | A `HierarchicalVM` node has no selection, no expansion state with notifications, no expand or activate command and no dispose cascade. | **Partial**              | Selection: the inherited `select()` delegates to the container back-reference, which tree nodes never set (`components/componentVMBase.ts:191-194`, `hierarchical/hierarchicalVm.ts:93`); a probe shows `canSelect()` false. Expansion: the opt-in `ExpandableState` emits `isExpandedChanged` in every flavor but publishes nothing on the hub (ADR-0015, ADR-0028 §3.6). Commands: none, as claimed. Cascade: absent by design (spec 18 §3, ADR-0105). | All four Notes showcases avoid `HierarchicalVM` because it lacks a current selection, for example `examples/typescript/react/notes-showcase/src/viewmodels/notebooksRootVM.ts:4-12`. |
| K3  | `CompositeVM` has no keyed lookup and no open-or-activate step.                                                                        | **Confirmed**            | Lookup is by index or identity only (`composites/compositeVMBase.ts:217-235`). Keyed lookup exists only on the caller-owned keyed serviced collection (ADR-0097). `DiscriminatorVM` keeps keys only (spec 22 §3, ADR-0075 §4).                                                                                                                                                                                                                           | Deferred #618 is the same primitive, first raised by nnx-studio (#593 item 5).                                                                                                       |
| K4  | `AsyncResourceVM` loads on demand only and cannot poll.                                                                                | **Confirmed**, by design | No construct or destruct hook (`state/asyncResourceVM.ts:89-112`). Spec 23 §1: "It does not start automatically during component construction or stop during destruction". ADR-0100 §4.6 rejected coupling loads to the lifecycle.                                                                                                                                                                                                                       | #593 item 13 declined a delayed-task primitive. ADR-0073 deferred TTL for lack of a test clock.                                                                                      |

### 1.5.2. Vue Bindings (Catalogue §2.2)

| ID       | Claim                                                                                                                | Verdict                                         | Evidence                                                                                                                                                                                                                                                                                                                                                 | Related                                                 |
| -------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| V1       | A Vue recipe exists but no Vue package.                                                                              | **Confirmed**                                   | `packages/` holds only `react`. The recipe accepts only `ComponentVMOf` and takes an explicit hub (`examples/typescript/integration-recipes/src/vue/composables/useVm.ts:10-14`), although `hub` is public (ADR-0090).                                                                                                                                   | #394 (deferred)                                         |
| V2       | `useCommand` exists for React only.                                                                                  | **Confirmed**                                   | `packages/react/src/useCommand.ts:10` takes a parameterless `ICommand`. React has no `ICommandOf<T>` support, so Heimdall goes further than React.                                                                                                                                                                                                       | #394 acceptance criterion 4                             |
| V3       | `useVmCollection` exists for React only; tree children need a reparent-aware snapshot.                               | **Confirmed**                                   | React's hook takes `IVmCollection` only, and `HierarchicalVM.children` is a plain array. A reparent is published only by the new parent (spec 18 §7), so a React binding on the old parent stays stale.                                                                                                                                                  | React gap; #394                                         |
| V4 to V7 | Scroll target, in-view, pan and resize: a view-model cannot reach the viewport or measure the page.                  | **Confirmed**, by design                        | Core is DOM-free (`langs/typescript/tsconfig.json` lib is ES2020). Spec 00 §2 leaves the rendering layer to the host.                                                                                                                                                                                                                                    | #391 and #413 keep geometry and visibility on the host. |
| V8       | `hoverAt`                                                                                                            | **Confirmed**, app-coupled                      | It is tied to Heimdall's chart marks and its own `TooltipVM`.                                                                                                                                                                                                                                                                                            | —                                                       |
| V9       | `datePicker`                                                                                                         | **Confirmed**, app-specific                     | It names Heimdall's `RangeSelector` markup and has no test of its own.                                                                                                                                                                                                                                                                                   | —                                                       |
| V10      | `v-tip`                                                                                                              | **Confirmed**, depends on an absent `TooltipVM` | ARIA and Escape behavior belong to the host.                                                                                                                                                                                                                                                                                                             | #413                                                    |
| V11      | `eventValue`                                                                                                         | **Confirmed**, trivial                          | `v-model` and `$event.target.value` cover it; it exists for Heimdall's template lint.                                                                                                                                                                                                                                                                    | —                                                       |
| V12      | No Vue binding hands a VM down the component tree.                                                                   | **Confirmed**                                   | React has no context either (`packages/react/README.md:56-57`). The DayDreams pilot asked for a hub-first helper as a follow-up.                                                                                                                                                                                                                         | #394 scope                                              |
| V13      | `#private` fields make a proxied VM throw.                                                                           | **Confirmed**                                   | The 3.30.0 dist downlevels `#private` to WeakMap reads, so a Proxy receiver throws `TypeError` (probe).                                                                                                                                                                                                                                                  | #394                                                    |
| V14, V15 | Dismiss and document sync: a view-model cannot reach document events or the document.                                | **Confirmed**, by design                        | The React showcase keeps both kinds of code in app code (`ModalShell`, `themeAdapter.ts`).                                                                                                                                                                                                                                                               | ADR-0029 keeps host adapters downstream.                |
| V16      | A command cannot move focus.                                                                                         | **Confirmed**, conflicts with #413's design     | Heimdall drives focus from persistent state and refocuses on remount. #413 requires that "a one-shot focus intent must not pose as replayable model state".                                                                                                                                                                                              | #413                                                    |
| V17      | VMx has no key binding.                                                                                              | **Confirmed**, declined in core                 | #593 item 2: "Key gestures, ⌘/Ctrl labels, text-field routing and modal suppression are host concerns".                                                                                                                                                                                                                                                  | #593                                                    |
| V18      | Focus steps and the roving tabindex are DOM work.                                                                    | **Confirmed**, declined in core                 | #593 item 8 declined `handleKey` and key mapping; #620 tracks only the cursor moves.                                                                                                                                                                                                                                                                     | #620                                                    |
| L1       | A proxied VM throws, "for example from component props"; `sender === proxy` never matches; the recipe needs `toRaw`. | **Partial**                                     | The throw, the identity mismatch and the missing `toRaw` are confirmed. Props are shallow-reactive, so a raw VM passed as a prop stays raw. The proxy appears only when the parent holds the VM in `ref()`, `reactive()`, Options `data()`, a ref'd list or store state (probe). Solid and Svelte leave class instances raw, so the problem is Vue-only. | #342                                                    |
| L2       | The recipe assigns and then calls `triggerRef`, so a `flush: "sync"` watch runs twice per message.                   | **Confirmed**                                   | Probe: 2 runs for a synchronous `watch` or `watchEffect` on a replacement message, 1 for renders and default watchers. The #342 fix (PR #470) introduced the pattern.                                                                                                                                                                                    | ADR-0101 §2.4 forbids duplicate work.                   |

### 1.5.3. Owner-Aware Builders (Catalogue §2.3)

| ID   | Claim                                                                                                            | Verdict                      | Evidence                                                                                                                                                                                                                                                                                                | Related                                                                                |
| ---- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| O1   | `own()` is protected, so builders cannot call it.                                                                | **Confirmed**                | `components/componentVMBase.ts:1048`. C# `protected Own`, Python `_own`, Swift `open func own`, Rust `pub fn own`.                                                                                                                                                                                      | ADR-0090 §3: "C#, Python, and TypeScript expose registration only to subclasses."      |
| O2   | `own()` appends and returns; after disposal it cleans at once.                                                   | **Confirmed**                | `componentVMBase.ts:1048-1055`; DISP-010. Same in all five flavors.                                                                                                                                                                                                                                     | —                                                                                      |
| O3   | Only `dispose()` releases the list.                                                                              | **Confirmed**                | `#finishTerminalCleanup` alone drains it (`componentVMBase.ts:945`); DISP-011.                                                                                                                                                                                                                          | ADR-0090 §2: "Reconstruct and destruct never drain disposal-lifetime resources."       |
| O4   | `_onDispose` runs first, then owned resources in reverse, and `propertyChanged` completes last.                  | **Partial**                  | `Disposed` is published before `_onDispose`. The built-in commands are disposed after stream completion, so `propertyChanged` is not last (`componentVMBase.ts:923-962`).                                                                                                                               | ADR-0129 fixes the order in all five flavors.                                          |
| O5   | `dispose()` inside a hook defers all cleanup.                                                                    | **Confirmed**, with a nuance | `Disposed` is published at once; only terminal cleanup waits for the hook (`componentVMBase.ts:931-933`).                                                                                                                                                                                               | LIFE-015                                                                               |
| O6   | Each owned cleanup sits in an empty `catch`, so failures are invisible.                                          | **Confirmed**, normative     | `componentVMBase.ts:1057-1065`. Spec 02 §2.3: "Each cleanup failure is swallowed independently so later resources still run." All five flavors swallow.                                                                                                                                                 | DISP-009; ADR-0108: "Existing owned-resource cleanup remains independently swallowed." |
| O7   | The library never calls `own()`; wrappers leave inner commands to their creator.                                 | **Confirmed**                | No `own(` call in `langs/typescript/src`. Spec 04 §8.4 and ADR-0134 §2.2: "Wrappers stay non-owning".                                                                                                                                                                                                   | —                                                                                      |
| O8   | The builders' methods are listed; no builder takes an owner.                                                     | **Partial**                  | The lists miss `throwOnCancel` and `withNullServices`. No builder takes an owner in any flavor. `ComponentVMBuilder` builds only plain `ComponentVM`, never a subclass.                                                                                                                                 | —                                                                                      |
| O9   | `RelayCommand.dispose()` is idempotent and makes the command inert.                                              | **Confirmed**                | `commands/relayCommand.ts:52-86`; CMD-013; ADR-0068.                                                                                                                                                                                                                                                    | —                                                                                      |
| O10  | `walk()` accepts any node with `components()`, which only aggregates declare; leaf classes get no child support. | **Partial**                  | `tree/walk.ts:58-70` reads `components()` only on non-iterable nodes, and only aggregates declare it. This is not a spec contract: spec 13 §2 says "A leaf `ComponentVM` yields exactly itself". `own(child)` does dispose a child, but parent-first. `develop` adds a protected `_transitionChildren`. | —                                                                                      |
| O11  | Symbol-keyed `ComponentVMBuilder` members are a precedent for hidden builder options.                            | **Partial**                  | The symbols exist but are module-private and unexported; they serve only `create(options)`. An exported `registerOwned` would grow the public surface.                                                                                                                                                  | BLD-006                                                                                |
| O12  | `RelayCommand` sits in another chunk; a type-only import avoids a cycle.                                         | **Confirmed**                | tsup `splitting: true`. `componentVMBase.ts:21` imports `RelayCommand` as a value, so a registration channel must live in a leaf module.                                                                                                                                                                | —                                                                                      |
| O13  | Heimdall's usage counts.                                                                                         | **Not verifiable**           | Heimdall's code is not available.                                                                                                                                                                                                                                                                       | —                                                                                      |
| O14a | "Symbol-keyed, so the public surface does not grow."                                                             | **Refuted**                  | The symbol must be exported for builders in another module to use it.                                                                                                                                                                                                                                   | O11                                                                                    |
| O14b | `AsyncRelayCommand` needs its own owner option because it has no builder.                                        | **Refuted**                  | It has a builder (`commands/asyncRelayCommand.ts:193`).                                                                                                                                                                                                                                                 | —                                                                                      |
| O15  | The seven proposed tests.                                                                                        | **Partial**                  | Tests 1 to 6 restate existing contracts. Test 7 would pin parent-first disposal of child VMs, against LIFE-013. Missing: failure isolation, one registration per build, copies keep the owner, `create(options)` parity, forwarding owners, owner plus a later container transfer.                      | DISP-009, BLD-001, BLD-003, BLD-006, FWD-004, ADR-0107                                 |

### 1.5.4. Further Proposals (Catalogue §2.4)

These rows check the factual premises. §1.7 and §1.8 assess the proposals themselves.

| ID   | Claim                                                                                                    | Verdict                    | Evidence                                                                                                                                                                                                                                                                                                                                                                  | Related                                         |
| ---- | -------------------------------------------------------------------------------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| P2   | `own()` releases only at `dispose()`.                                                                    | **Confirmed**              | DISP-011                                                                                                                                                                                                                                                                                                                                                                  | ADR-0041 §4 anticipates a per-construct helper. |
| P3   | `GroupVM` constructs and destructs in insertion order.                                                   | **Confirmed**, unspecified | True in all five flavors, but spec 02 §6: subscribers "MUST NOT rely on a particular child visitation order" (ADR-0047 §2.5).                                                                                                                                                                                                                                             | —                                               |
| P4a  | Raw constructors require `hint`; `AsyncResourceVMOptions` makes it optional.                             | **Partial**                | True of the raw constructors in TypeScript and Python and of the C# positional constructor. Every options type and builder already defaults `hint` to `""` (spec 10 §4, BLD-004), and Swift defaults it on the base.                                                                                                                                                      | —                                               |
| P4b  | `ComponentVMBuilder` already carries services.                                                           | **Partial**                | `services(hub, dispatcher)` is a pair setter, not a bundle. The dispatcher is not public in TypeScript, C# or Rust.                                                                                                                                                                                                                                                       | #144                                            |
| P5a  | `DerivedProperty` publishes nothing on the hub.                                                          | **Confirmed**, by design   | ADR-0011 §4: "a self-contained primitive with no required dependency on VM types".                                                                                                                                                                                                                                                                                        | #100                                            |
| P5b  | `.value` throws before the first emission.                                                               | **Partial**                | Only for an unseeded source. A seeded source has a value at construction (DPROP-001); Rust requires an initial value.                                                                                                                                                                                                                                                     | #364, #142                                      |
| P5c  | `_notifyPropertyChanged` takes one name.                                                                 | **Confirmed**              | Spec 05 §2.3 and CVM-007 pin one hub message and one local notification per call.                                                                                                                                                                                                                                                                                         | —                                               |
| P6   | `whenPropertyChanged` takes one name, and its result still needs `own()`.                                | **Confirmed**              | `messages/whenPropertyChanged.ts:35-48`. Informative helper, no ID (ADR-0050 §2.1).                                                                                                                                                                                                                                                                                       | —                                               |
| P7a  | `reload()` aborts a running load and starts a new one.                                                   | **Confirmed**              | `state/asyncResourceVM.ts:173-179`; latest-start-wins, ARES-008.                                                                                                                                                                                                                                                                                                          | —                                               |
| P7b  | `reloadCommand` ignores a call while a load runs.                                                        | **Partial**, mostly wrong  | Only `reloadCommand`'s own execution blocks it. It supersedes a load that `loadCommand` or `reload()` started (probe in TypeScript and Python). Spec 23 §4: the reload command "MAY supersede a current load".                                                                                                                                                            | ADR-0056 §2.2                                   |
| P7c  | Latest-wins needs `reload()` plus rejection handling.                                                    | **Refuted**                | A superseded or failing `reload()` resolves normally (spec 23 §7, ADR-0100 §2.4, probe).                                                                                                                                                                                                                                                                                  | —                                               |
| P7d  | Nothing in the library reads the `errors` stream.                                                        | **Confirmed**, by design   | It is a consumer output channel (ADR-0049, ADR-0056 §2.4). `RelayCommand` has none. `TokenPagedComposition` fetch faults surface only there.                                                                                                                                                                                                                              | —                                               |
| P7e  | `canExecute()` swallows a predicate exception.                                                           | **Confirmed**, specified   | Spec 04 §2: "The predicate MUST NOT raise. If it does, the language flavor MAY treat the result as `false`".                                                                                                                                                                                                                                                              | #372                                            |
| P7f  | Every app hand-writes a retry command.                                                                   | **Partial**                | `reloadCommand` is the specified retry (spec 23 §7). A command enabled only in `Error` is one `wrapWith` call (CMD-011).                                                                                                                                                                                                                                                  | —                                               |
| P8a  | Only `dispose()` aborts a running load.                                                                  | **Partial**                | True of the automatic abort, by design (ADR-0100 §2.7). `cancel()`, `cancelCommand`, supersession and a caller's signal also abort.                                                                                                                                                                                                                                       | —                                               |
| P8b  | Consumers read the value through a switch over the state.                                                | **Partial**                | True in TypeScript and Python. C# (`State.Value`), Swift (`state.value`) and Rust (`value()`) ship accessors.                                                                                                                                                                                                                                                             | #378                                            |
| P9   | Six hand-written timers in four classes.                                                                 | **Not verifiable**         | Heimdall code                                                                                                                                                                                                                                                                                                                                                             | —                                               |
| P10  | VMx has `ExpandableState` only.                                                                          | **Partial**, overstated    | It is the only open-state helper. Movement and choice exist elsewhere: the `FilteredCompositeVM` cursor (COMP-033, COMP-034), `CompositeVM.current`, `ModalVM`, `DiscriminatorVM`.                                                                                                                                                                                        | #619, #620                                      |
| P11a | `loader`, `childModelToChildViewModel` and `currentSelector` need the instance before `super()` returns. | **Refuted** for TypeScript | All three run after construction: the loader on `load()` (ARES-001), the projection and the selector during `construct()`. Callbacks that capture `this`, including `#private` fields, compile and run (probe). `currentSelector` already receives the composite (`composites/compositeVMBase.ts:606`). The eager callback is `modeledHinter`, which the catalogue omits. | —                                               |
| P11b | A trailing instance argument keeps existing signatures.                                                  | **Refuted** across flavors | True only for JavaScript arity. Python, C#, Swift and Rust callables change arity. The catalogue's own example puts the instance first.                                                                                                                                                                                                                                   | —                                               |
| P12  | A view binds one VM by property name; tests need a recorder per child.                                   | **Partial**                | Name binding comes from the Vue recipe. The React adapter binds with selectors across VMs (`useVmx`). One `recordPropertyChanges(hub)` records every sender.                                                                                                                                                                                                              | ADR-0098                                        |

### 1.5.5. Lessons (Catalogue §3)

| ID   | Claim                                                                                                        | Verdict                                        | Evidence                                                                                                                                                                                                       | Related                                                                       |
| ---- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| L3   | `HierarchicalVM` falls back to a private hub.                                                                | **Confirmed**, TypeScript raw constructor only | `hierarchical/hierarchicalVm.ts:103-104`. The builder requires services (HIER-015). C#, Python and Swift require them. Rust's `new()` conveniences fabricate hubs.                                             | ADR-0009 defers a required hub to the next TypeScript major; ADR-0052 §2.3.   |
| L4   | Construct cascades only with `eagerChildren`; destruct and dispose never cascade.                            | **Confirmed**, by design                       | Spec 18 §3: "disposing a hierarchical node does not dispose, destruct, detach, reparent, or otherwise manage its children". Same in all five flavors.                                                          | ADR-0105. The docs page `hierarchical-family.md` contradicts the spec (§1.9). |
| L5   | `CompositeVM` clears `current` at destruct, and `current` stays null after a new construct.                  | **Partial**                                    | The clear is normative (spec 06 §5, COMP-005). A `Current(selector)` hook re-runs on every construct in all five flavors and restores the page. Re-running on reconstruct is untested.                         | ADR-0042, COMP-025                                                            |
| L6   | The default retention is `DiscardPrevious`.                                                                  | **Confirmed**, by design                       | Spec 23 §8: it "is conservative and is the default"; ADR-0100 §4.4; ARES-007.                                                                                                                                  | —                                                                             |
| L7   | `reload()` is a no-op in `Idle`; a cancelled first load returns to `Idle`; `reload()` in `Loading` restarts. | **Confirmed**                                  | ARES-001, ARES-005, ARES-008. Caveat: open cross-flavor decision §1.1 (Swift returns a cancelled discard-mode retry from `Error` to `Idle`).                                                                   | `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md`                  |
| L8   | A subclass `status` collides with the inherited `ConstructionStatus`.                                        | **Partial**                                    | The names are deliberate in all five flavors. In TypeScript a subclass field `status` is a compile error, not a silent mask. In Python an override is silent and breaks containers, which read `child.status`. | Spec 23 §2                                                                    |
| L9   | `open(key)` cannot pass construction data.                                                                   | **Not verifiable**                             | It describes Heimdall's class; #618's per-call factory already carries data.                                                                                                                                   | #618                                                                          |
| L10  | `walk()` misses VMs held in fields or as members of an iterable node.                                        | **Confirmed**, matches the spec                | `tree/walk.ts:58-63`; spec 13 §2. C# and Swift offer no hook at all.                                                                                                                                           | —                                                                             |
| L11  | VMx has no tooltip view-model.                                                                               | **Confirmed**                                  | No flavor or adapter ships one. The catalogue's own row says Heimdall's `TooltipVM` needs no kit class.                                                                                                        | —                                                                             |
| L17a | The dispatcher exposes `foreground` and `background`.                                                        | **Confirmed**                                  | `services/dispatcher.ts:9-12`                                                                                                                                                                                  | —                                                                             |
| L17b | A long poll belongs on `background`.                                                                         | **Refuted** as a portable rule                 | Background is for lifecycle work (spec 11 §1). It is a pool thread in C# and Python. In TypeScript the choice makes no difference for delays above 0.                                                          | —                                                                             |
| L17c | A scheduler option on five classes is redundant.                                                             | **Not verifiable**                             | The classes are Heimdall's. No VMx class that takes a scheduler also holds a dispatcher.                                                                                                                       | —                                                                             |
| L19  | `GroupVM` destructs in insertion order.                                                                      | **Confirmed**, unspecified                     | As P3. Heimdall's two ordering tests rely on unspecified behavior.                                                                                                                                             | ADR-0047 §2.5                                                                 |
| L20  | `subscribeValue` suppresses unchanged values with `Object.is`.                                               | **Partial**                                    | That is only the default. `equality: () => false` fires on every matching message, including a same-reference republish (SUBV-002, ADR-0095 §3).                                                               | —                                                                             |
| L13  | Three registrations per child of a leaf class.                                                               | **Confirmed** for 3.30.0                       | Hand-written construct loops also break the background-child wait of spec 02 §6 and never roll back. `develop`'s `_transitionChildren` covers both.                                                            | —                                                                             |

The lessons on silent disposal errors, `_onDispose` order, the `errors` stream, the cancel point, `DerivedProperty` and `hint` repeat O6, O4, P7d, P8a, P5a and P5b, and P4a.

### 1.5.6. Open Items (Catalogue §4)

| ID  | Claim                                                                    | Verdict                              | Evidence                                                                                                                                                                                                            |
| --- | ------------------------------------------------------------------------ | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1  | Every node filters every `TreeStructureChangedMessage`.                  | **Confirmed**                        | Tree notifications are hub-only in all five flavors.                                                                                                                                                                |
| F2  | Narrowing the filter to the node's messages fixes the cost.              | **Refuted**                          | The hub is a broadcast subject, so every subscriber still runs its filter. A transfer is published only by the new parent, and invalidation publishes `PropertyChanged("children")`; a narrowed filter misses both. |
| F3  | The accordion fold materializes lazy siblings through `parent.children`. | **Refuted**                          | A node gets a parent only after its parent materializes, so `parent.children` is a cache hit (probe: 0 factory calls). Only reads of a sibling's own `children` or `isLeaf` load one level.                         |
| F4  | An explicit `retention: undefined` overrides the poll default.           | **Confirmed**, as a Heimdall kit bug | VMx merges retention with `??` (`state/asyncResourceVM.ts:97`).                                                                                                                                                     |
| F5  | `useCommand` ignores the bound `ICommandOf` parameter.                   | **Not verifiable**                   | Heimdall code. The requirement is sound.                                                                                                                                                                            |
| F6  | A read of `value.value` in a subscriber is tracked inside an effect.     | **Confirmed**                        | Probe. The VMx recipe does not read it; Heimdall's own L2 fix introduced it.                                                                                                                                        |
| F7  | A binding outside an effect scope warns and leaks.                       | **Confirmed**, and there is more     | The recipe leaks even inside an `effectScope`, and every setup-time subscription leaks under `renderToString`.                                                                                                      |

### 1.5.7. Tally

| Group             | Rows | Confirmed | Partial | Refuted | Not verifiable |
| ----------------- | ---- | --------- | ------- | ------- | -------------- |
| Kit               | 4    | 3         | 1       | 0       | 0              |
| Vue               | 16   | 15        | 1       | 0       | 0              |
| Builders          | 16   | 8         | 5       | 2       | 1              |
| Further proposals | 21   | 8         | 9       | 3       | 1              |
| Lessons           | 15   | 9         | 3       | 1       | 2              |
| Open items        | 7    | 4         | 0       | 2       | 1              |
| Total             | 79   | 47        | 19      | 8       | 5              |

V4 to V7 and V14 to V15 each count as one row, as in the tables. Of the 47 confirmed claims, 19 describe a decision that the spec or an ADR records rather than a gap: K1, K4, V4 to V7, V14 to V15, V17, V18, O3, O6, O7, P2, P5a, P5c, P7d, P7e, L3, L4, L6, L7 and L10.

## 1.6. Evidence Across Consumers

A gap that two independent consumers hit is stronger evidence than one consumer's line counts. This matrix places Heimdall beside nnx-studio (#593), the VMx showcases and the earlier pilots.

| Gap                                 | Heimdall                                  | nnx-studio (#593)                               | VMx showcases and pilots                                                                                   | Reading                                       |
| ----------------------------------- | ----------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Current selection in a tree         | `SelectableTreeNodeVM`                    | —                                               | All four Notes showcases avoid `HierarchicalVM` for this reason; the React tree hand-codes keyboard moves. | Strong                                        |
| One child per key, open or activate | `KeyedPageCompositeVM`                    | Item 5, now #618                                | —                                                                                                          | Two consumers                                 |
| Delayed or periodic work            | `PollingResourceVM`, six transient timers | Item 13: polling, autosave, delayed fetch       | ADR-0073 deferred TTL for want of a clock.                                                                 | Two consumers                                 |
| Leaf VM with child fields           | 26 `components()` lists                   | —                                               | `WorkspaceVM` hand-cascades three members; `NotesViewVM` and `NotebooksRootVM` hand-dispose.               | Two sources                                   |
| Popover and menu state              | Two menus, one popover, twelve tooltips   | Staged `PopoverVM`; item 8 (cursor) is now #620 | —                                                                                                          | Triaged into `ExpandableState` and #620       |
| Focus and announcements             | `useFocusOnChange`, `useScrollTarget`     | Item 7, folded into #413                        | `ModalShell` focus restore in the React showcase                                                           | Two consumers; host-owned                     |
| Key gestures                        | `useShortcut`                             | Item 2, declined                                | `useHotkeys` in the React showcase                                                                         | Host concern                                  |
| Restart admission for async work    | `reloadPolicy`                            | Item 1, concurrency half, folded into #376      | —                                                                                                          | Two consumers                                 |
| Compare-and-assign setter           | `declare<T>`                              | Staged `_set`, dropped                          | —                                                                                                          | Ruled out twice                               |
| Per-construct cleanup               | 26 `Subscription` fields                  | —                                               | —                                                                                                          | One consumer; boilerplate, no defect reported |
| Command ownership without nesting   | 115 `own(builder…)` calls                 | —                                               | —                                                                                                          | One consumer; #371 asks the C# form           |
| Vue adapter                         | 19 binding files                          | —                                               | Executed recipe only                                                                                       | One consumer plus the recipe                  |
| Derived value on the hub            | `StatusBarVM` seeding                     | —                                               | The VMx `StatusBarVM` example binds `DerivedProperty` directly.                                            | #100 closed as not planned                    |

## 1.7. Dispositions

| ID  | Candidate                                                                                             | Disposition                                                 | Reason                                                                                                                                                       | Home                  |
| --- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------- |
| D1  | K1 navigation and request messages                                                                    | Decline in core; recipe                                     | App routing vocabulary (spec 00 §2). App-defined messages already work in four flavors.                                                                      | Docs; #403, #413      |
| D2  | K2 tree-level current selection                                                                       | **Adopt**, normative                                        | Strongest cross-consumer evidence; composes with `HierarchicalVM` without new base members.                                                                  | §1.8.1                |
| D3  | K2 and P10 open, close and toggle commands                                                            | **Adopt**, normative                                        | Small; serves tree nodes, popovers and menus alike.                                                                                                          | §1.8.2                |
| D4  | K2 dispose cascade                                                                                    | Decline; recipe                                             | Contradicts spec 18 §3 and ADR-0105. A blind cascade is unsafe under reparenting.                                                                            | Docs                  |
| D5  | K2 accordion fold, `select()` that navigates                                                          | Decline                                                     | App policy. `select()` semantics are normative (spec 05 §6).                                                                                                 | Heimdall              |
| D6  | K3 keyed pages and L9                                                                                 | Fold into #618 and widen it                                 | Same primitive as nnx-studio's keyed slot; Heimdall needs a retention policy.                                                                                | §1.8.7                |
| D7  | K4 polling                                                                                            | Recipe now; use case for #388 and D30                       | ADR-0100 §2.1, §2.7, §4.6. `AsyncResourceVM` is sealed in C# and final in Swift.                                                                             | Docs; #388            |
| D8  | Vue core bindings                                                                                     | **Adopt** as `@thekaveh/vmx-vue`                            | Mirrors the React package; one consumer plus the recipe; #394's gates apply.                                                                                 | §1.8.11               |
| D9  | Vue recipe fixes (L1, L2, F6, F7)                                                                     | **Fix now**                                                 | Defects in a documented, executed recipe.                                                                                                                    | §1.8.11               |
| D10 | React parity items                                                                                    | **Adopt** in `@thekaveh/vmx-react`                          | Release the unreleased fixes, including #638, before Vue semantics freeze.                                                                                   | §1.8.11               |
| D11 | DOM-behavior bindings (scroll, in-view, pan, resize, dismiss, document sync, shortcuts, roving focus) | Decline for core and for the first Vue release              | Core is DOM-free; #593 declined key handling; VueUse covers the primitives. Focus and announcements return only through #413.                                | Heimdall; #413        |
| D12 | App-specific bindings (`hoverAt`, `datePicker`, `v-tip`, `eventValue`)                                | Keep in Heimdall                                            | They name app markup or app VMs.                                                                                                                             | Heimdall              |
| D13 | O14 `ownedBy`, `owner` option, `registerOwned`                                                        | Decline as proposed                                         | Does not prevent omission; public registration path against ADR-0090 §3; parent-first child disposal against LIFE-013; a second owner invisible to ADR-0107. | §1.8.8; #371          |
| D14 | P2 construct-scope ownership                                                                          | **Adopt in principle** as `whileConstructed`, after a pilot | ADR-0041 §4 named this exact helper as the way to revisit. The catalogue's semantics have gaps.                                                              | §1.8.3                |
| D15 | P3 `adopt(child)`                                                                                     | Defer to a design gate                                      | Would turn every leaf into a container (ADR-0018). A supported helper gives most of the value first.                                                         | §1.8.4                |
| D16 | P3 child-transition helper                                                                            | **Adopt**, normative                                        | Already protected in TypeScript, C# and Python; documenting it and exposing it in Swift and Rust is cheap.                                                   | §1.8.4                |
| D17 | P3 `destructOrder`                                                                                    | **Adopt**, opt-in, both containers                          | Matches ADR-0090's own LIFO rationale. Needs a refining ADR, because ADR-0047 §2.5 leaves order unspecified.                                                 | §1.8.4                |
| D18 | P4 optional `hint`                                                                                    | **Adopt**, flavor-level                                     | Raw constructors catch up with builders and options; no spec change.                                                                                         | §1.8.6                |
| D19 | P4 services bundle                                                                                    | Fold into #144                                              | Needs a five-flavor decision on dispatcher exposure.                                                                                                         | #144                  |
| D20 | P4 `parent` option                                                                                    | Decline                                                     | The name collides with the internal container `Parent`; ambient inheritance was declined by ADR-0003 §3.                                                     | —                     |
| D21 | P5 `declare<T>` and `derive<T>`                                                                       | Decline                                                     | Spec 05 §2.3, ADR-0040, ADR-0083 §4.1 and §4.4, #78, #100, #593. "Announce once for two causes" contradicts lossless hub deferral (spec 03 §3.3).            | Docs                  |
| D22 | P5 variadic `_notifyPropertyChanged`                                                                  | Defer                                                       | Low value for a five-flavor change to a pinned contract (CVM-007).                                                                                           | —                     |
| D23 | P6 `onProperty`                                                                                       | Recipe; optional multi-name `whenPropertyChanged`           | Existing helpers cover it in one line. Construct scope is D14.                                                                                               | §1.8.12               |
| D24 | P7 `reloadPolicy`                                                                                     | Fold into #376                                              | Same admission question as nnx-studio's `concurrency`.                                                                                                       | §1.8.9                |
| D25 | P7 `retryCommand`                                                                                     | Decline; recipe                                             | `reloadCommand` is the specified retry; a fourth command would change ARES-001 to ARES-004.                                                                  | Docs                  |
| D26 | P7 predicate exceptions on an `errors` stream                                                         | Fold an opt-in hook into #372                               | No VM has an error stream and commands have no owner link. The default behavior is normative.                                                                | §1.8.9                |
| D27 | P8 `cancelOnDestruct`                                                                                 | Decline as an option                                        | Contradicts ADR-0100 §2.7; D14 or a one-line hook covers it.                                                                                                 | §1.8.3                |
| D28 | P8 `current` value accessor                                                                           | Fold into #378 as `valueOr`                                 | Gap in TypeScript and Python only. `current` collides with composites and `isCurrent`.                                                                       | §1.8.9                |
| D29 | P8 and L17 scheduler from the dispatcher only                                                         | Decline as a portable rule                                  | Null dispatchers diverge for delayed work; Swift and Rust cannot express a delay.                                                                            | D30                   |
| D30 | P9 `TransientStateVM`                                                                                 | Decline as a VM; open a clock contract issue                | Second consumer for #593 item 13. A clock contract also unblocks polling, TTL, retry and Rust debounce.                                                      | §1.8.10               |
| D31 | P10 `PopupVM`, `MenuVM`, `TooltipVM`                                                                  | Decline as classes; absorb the parts                        | Widget VMs (ADR-0072 §3). Parts go to D3, #620, #619 and #413.                                                                                               | §1.8.2                |
| D32 | P11 instance arguments for callbacks                                                                  | Decline; docs                                               | Premise refuted in TypeScript; breaking in four flavors.                                                                                                     | §1.11                 |
| D33 | P12 property bubbling                                                                                 | Decline in core                                             | Sender identity is normative (spec 03 §1); adapters can resolve paths with selectors.                                                                        | §1.8.11               |
| D34 | L3 private hub in the TypeScript raw constructor                                                      | TypeScript 4.0; deprecation now                             | ADR-0009 defers the breaking change to the next TypeScript major.                                                                                            | §1.8.14               |
| D35 | L5 selector on reconstruct                                                                            | Clarify and test                                            | Behavior exists in all five flavors; the spec says "once".                                                                                                   | §1.8.13               |
| D36 | L7 discard-mode retry baseline                                                                        | Resolve the open decision                                   | Already item §1.1 of `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md`.                                                                           | Open-decisions ledger |
| D37 | L8 reserved baseline names                                                                            | Docs                                                        | Renaming `status` would break all five flavors.                                                                                                              | Docs                  |
| D38 | O6 silent cleanup errors                                                                              | Keep; diagnostics through #407                              | Normative and tested (DISP-009, ADR-0108). Surfacing them by default is a behavior change.                                                                   | #407                  |
| D39 | `own()` on forwarding decorators (found during verification)                                          | **Adopt**, normative                                        | The flavors disagree: TypeScript never releases the registration and Python raises. It must land before any new ownership surface.                           | §1.8.5                |

## 1.8. Designs for Adopted and Folded Items

### 1.8.1. Tree Selection Helper (D2)

**Problem.** A tree node cannot be the current item: `select()` targets the container back-reference, which `HierarchicalVM` never sets. Every showcase and Heimdall rebuild the same rule.

**Shape.** A helper composed on a structural root, not new `HierarchicalVM` members. New base members would collide with subclass members in TypeScript, C# and Swift, and Rust's `HierarchicalVm<M>` has no subclass hook.

| Flavor     | Sketch                                                                                                                                             |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| C#         | `TreeSelection<TVM>`: `TVM? Current`, `bool CanSelect(TVM)`, `void Select(TVM)`, `void Clear()`, `IObservable<TVM?> CurrentChanged`, `IDisposable` |
| Python     | `TreeSelection[TVM]`: `current`, `can_select(node)`, `select(node)`, `clear()`, `current_changed`                                                  |
| TypeScript | `TreeSelection<TVM>`: `current`, `canSelect(node)`, `select(node)`, `clear()`, `currentChanged`, `dispose()`                                       |
| Swift      | `TreeSelection<TVM>`: `select(_:) throws` for a non-member (ADR-0053), `currentChanged: AnyPublisher`                                              |
| Rust       | `TreeSelection<M>`: `select(&node) -> VmxResult<()>`, a `ValueStream` for changes                                                                  |

**Rules for the ADR.**

1. Selection accepts only a node inside the root's materialized tree.
1. Selection clears when the current node leaves the tree: removal, transfer out, invalidation of an ancestor, or disposal.
1. Like `ExpandableState`, the helper exposes its own change stream, and the VM that owns it forwards changes to the hub (ch14 rule 6).
1. Nodes may declare `ISelectable` and delegate to it.
1. Selection does not navigate. A host maps the current node to a route.

**Enablers to decide in the same ADR.**

- Leaving a tree is not observable today. A transfer is published only by the new parent (spec 18 §7), and invalidation publishes `PropertyChanged("children")`. Either the helper watches the ancestors of the current node, or spec 18 §7 gains a notification from the old parent. The second is a behavior change that needs IDs.
- `IsChildrenMaterialized` in all flavors (Rust has `is_children_materialized()`), so a helper or a disposal recipe can walk without loading.

**Conformance.** About six HIER IDs (HIER-033 onward). **Size:** M per flavor. **Semver:** minor.

### 1.8.2. Open, Close and Toggle Commands on `ExpandableState` (D3, Parts of D31)

`ExpandableState` gains `ExpandCommand`, `CollapseCommand` and `ToggleExpansionCommand`. Their predicates are the existing `Can*` checks, and their triggers come from `IsExpandedChanged`. Names follow the capability verbs, not the catalogue's `toggleExpand`:

| C#                       | Python                     | TypeScript               | Swift                    | Rust                         |
| ------------------------ | -------------------------- | ------------------------ | ------------------------ | ---------------------------- |
| `ToggleExpansionCommand` | `toggle_expansion_command` | `toggleExpansionCommand` | `toggleExpansionCommand` | `toggle_expansion_command()` |

Hub publication stays with the owning VM (ch14 rule 6); the docs show the one-line forwarder. Disposing the helper disposes its commands.

The rest of P10 goes elsewhere:

| Part                                                                           | Home                                      |
| ------------------------------------------------------------------------------ | ----------------------------------------- |
| Menu moves with first, last and wrap                                           | #620, on the `FilteredCompositeVM` cursor |
| "A choice closes the menu"; "a closed popup refuses a choice"; a cancel result | #619 (`ChoiceVM` through `Present`)       |
| Return focus to the opener                                                     | #413                                      |
| Tooltip anchor and target                                                      | Host geometry (spec 00 §2)                |
| Close a popup when a command of its menu runs                                  | App recipe with `succeedWith`             |

**Conformance.** Two or three EXP IDs (EXP-006 onward). **Size:** S. **Semver:** minor.

### 1.8.3. Construct-Scope Effects: `whileConstructed` (D14, D27, Part of D23)

**Basis.** ADR-0041 §4: "If a future consumer pattern repeatedly forgets `OnDestruct` cleanup, revisit as a `RegisterPerConstruct(IDisposable)` ergonomic helper rather than reintroducing a second bag." ADR-0090 §2 adds: "Keep per-construct resources explicit in `OnConstruct`/`OnDestruct` … Do not add two mutable bags." A new ADR must refine both.

**Evidence gap.** Heimdall's 26 fields and 28 `unsubscribe()` calls show repeated code, not forgotten cleanup. ADR-0090's own bar was a measured pilot diff with green tests. Heimdall can pilot this helper in its kit, as it piloted `ownedBy`, and report the diff.

**The catalogue's semantics have gaps.**

- "Released at once when not constructed" would release everything registered in `_onConstruct`, because the status there is `Constructing`.
- "Before `_onDestruct()`" reverses the disposal rule, where hooks run before their resources are released. If `_onDestruct` then throws, LIFE-014 rolls back to `Constructed` with the wiring already gone.
- A failed construct must release what it set up.
- `dispose()` from `Constructed` never calls `_onDestruct`, so the effects must also end at disposal, in a defined order.

**Proposed shape: a declarative effect, registered once.**

| Flavor     | Sketch                                                                              |
| ---------- | ----------------------------------------------------------------------------------- |
| C#         | `protected void WhileConstructed(Func<IDisposable?> setup)`                         |
| Python     | `_while_constructed(setup: Callable[[], Disposable \| Callable[[], None] \| None])` |
| TypeScript | `protected whileConstructed(setup: () => OwnedResource \| void): void`              |
| Swift      | `public func whileConstructed(_ setup: @escaping () -> AnyCancellable?)`            |
| Rust       | `while_constructed(impl Fn(&Self) -> Option<Box<dyn FnOnce() + Send>>)`             |

```ts
constructor(opts: PanelOptions) {
  super(opts);
  this.whileConstructed(() =>
    whenPropertyChanged(this.chart.hub, this.chart, "plot").subscribe(() => this.#refresh()),
  );
  this.whileConstructed(() => () => this.resource.cancel()); // replaces cancelOnDestruct
}
```

**Proposed rules.**

1. Setups run in registration order after `_onConstruct` succeeds and before `Constructed` is published, on every construct, including reconstruct.
1. A throwing setup fails the construct: earlier teardowns run in LIFO order, and LIFE-014 rollback follows.
1. Destruct runs `_onDestruct`, then the teardowns in LIFO order, then publishes `Destructed`. Hooks therefore always see the resources of their own scope.
1. Dispose from `Constructed` runs `_onDispose`, then the effect teardowns, then the `own()` registrations, all LIFO. The inner scope closes before the outer one.
1. A registration while `Constructed` runs its setup at once. A registration after disposal is ignored.
1. Teardown failures are isolated, as for `own()` (DISP-009).

`onProperty(…, "construct")` (P6) becomes one line on top of this helper.

**Conformance.** Four or five DISP or LIFE IDs. They touch DISP-011, LIFE-014 and LIFE-015. **Size:** M; the lifecycle core changes in every flavor. **Semver:** minor.

### 1.8.4. Children of Leaf Classes (D15, D16, D17)

**Step 1, the supported child-transition helper (D16).** `develop` already has a protected `_transitionChildren(children, construct, after?, joined?)` in TypeScript; C# has `TransitionChildrenAsync` and Python `_transition_children`. Make it documented, supported API in all five flavors: `open` in Swift and a public analogue in Rust. Add a matching best-effort disposal helper that disposes children depth-first before the parent publishes `Disposed`, as LIFE-013 requires of containers. A leaf class then keeps one member list and three one-line overrides. The helper waits for background children, and a failed child rolls back the parent's own transition; siblings that already constructed are not undone (`docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` §1.3).

```ts
readonly #members = [this.chart, this.table, this.tooltip];
protected override _onConstruct(): void { super._onConstruct(); this._transitionChildren(this.#members, true); }
protected override _onDestruct(): void { this._transitionChildren([...this.#members].reverse(), false, () => super._onDestruct()); }
```

`own(child)` disposes a child parent-first today, after the parent has published `Disposed`. The docs should say so until the disposal helper exists.

**Step 2, opt-in child order for containers (D17).** Add `ChildOrder.Reverse` for destruct and dispose on `GroupVM` and `CompositeVM`. The default stays unchanged. A refining ADR must amend ADR-0047 §2.5, which leaves visitation order unspecified. Idioms: C# `.DestructOrder(ChildOrder.Reverse)`, Python `.destruct_order(ChildOrder.REVERSE)`, TypeScript `.destructOrder("reverse")`, Swift `.destructOrder(.reverse)`, Rust `.destruct_order(ChildOrder::Reverse)`, plus the options forms (BLD-006). New IDs GRP-014 and COMP-046. A future major could make LIFO the default.

**Step 3, `adopt(child)`, behind a design gate (D15).** Decide only after steps 1 and 2 ship. `adopt` would have to:

- set a parent link like the aggregate's fixed-slot parent;
- reject duplicates, cycles and already-owned children (ADR-0107);
- wait for background children and roll back;
- dispose depth-first;
- extend `walk()` to visit both items and adopted members (spec 13, a new UTIL ID);
- coexist with hand-written `components()` methods.

Rust's same-type `TreeNode` is the largest parity obstacle.

**Not a substitute: `AggregateVM`.** Its factories run on every construct, and reconstruct replaces the slots (AGG-007). Children created once in a constructor are a different model, and arity is capped at 6 (ADR-0058) while Heimdall's panel has 11 children.

**Size.** Step 1 S to M (mostly docs, plus Swift and Rust exposure). Step 2 S. Step 3 L.

### 1.8.5. `own()` on Forwarding Decorators

This came out of verification (§1.9, item 1). Spec 09 is silent, and the flavors disagree:

| Flavor      | Behavior today                                                                                                                                                                                                               |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TypeScript  | `ForwardingComponentVM` extends `ComponentVMBase`, and its `dispose()` only delegates (`forwarding/forwardingComponentVM.ts:166`). An `own()` registration lands in the decorator's unused base state and is never released. |
| Python      | `_own` raises `AttributeError`, because the decorator never runs the base initializer.                                                                                                                                       |
| C#          | The decorator is not a `ComponentVMBase`, so it has no `Own`.                                                                                                                                                                |
| Swift, Rust | `own` forwards to the wrapped VM.                                                                                                                                                                                            |

**Proposal.** Spec 09 states that resource ownership forwards to the canonical ownership identity (ADR-0124), as Swift and Rust do. TypeScript and Python are fixed to match, and a new FWD-005 pins the rule. This must land before any new ownership surface (§1.8.3, §1.8.8).

### 1.8.6. Optional `hint` in Raw Constructors (D18)

- **TypeScript:** `hint?: string`, defaulting to `""`, in every raw constructor. `modeledHinter` becomes optional in the `ComponentVMOf` and `ReadonlyComponentVMOf` constructors, defaulting to `() => ""`.
- **Python:** `hint: str = ""`.
- **C#:** a protected overload without `hint`, because a positional parameter cannot take a trailing default here.
- **Swift:** already defaults it. **Rust:** not applicable.

There is no spec change and no new ID (BLD-004 already pins the builder default). Unit tests and CHANGELOG entries; a minor bump in the three flavors.

### 1.8.7. Keyed Composite: #618 Widened (D6)

Heimdall becomes the second consumer of #618. Widen its scope from a slot that keeps one child to a keyed container with a retention policy:

| Policy             | Meaning                                            | Consumer                             |
| ------------------ | -------------------------------------------------- | ------------------------------------ |
| `DisposeInactive`  | Activating another key disposes the previous child | nnx-studio's keyed slot (#618)       |
| `RetainAll`        | Children stay members; activation only selects     | Heimdall's pages                     |
| `DestructInactive` | Inactive children are destructed, not disposed     | Later, with #392's activation leases |

**Shape.** A `CompositeVM` subclass, so the key-uniqueness check runs inside the membership transaction (ADR-0118). `Open(key, create)` returns the child: an existing child is selected; a new one is added, constructed and selected. The per-call factory carries construction data (L9). Also `TryGet` (`get`, `get_by_key`), `ActiveKey` and `Close(key)`, named after the keyed serviced collection (ADR-0097). Idioms: C# `KeyedCompositeVM<TKey, VM>.Open(TKey, Func<TKey, VM>)`, Swift `open(_:create:) throws -> VM`, Rust `open(key, create) -> VmxResult<T>`.

**The ADR must define:**

- `Open` while the container is `Destructed` (auto-construct acts only once it is `Constructed`, spec 06 §5.1);
- background children, whose selection needs `Constructed`;
- re-entrant `Open` from hooks, and a throwing factory;
- external removal or transfer of a keyed child (ADR-0107);
- restoring `ActiveKey` after reconstruct through `Current(selector)` (§1.8.13);
- disposal during a switch.

**Conformance.** Six to eight IDs under a new prefix. **Size:** L. **Semver:** minor.

### 1.8.8. Command-Builder Ownership: #371 (D13)

**Decline the catalogue's shape.** It does not remove the silent omission. ADR-0090 justified `own()` by "The omission creates a silent leak class", and forgetting `.ownedBy(this)` is as silent as forgetting `this.own(...)`. A forgotten registration mostly leaves a command executable after disposal. It leaks a subscription only when the command has external triggers: a trigger on the owner's own `propertyChanged` completes at disposal.

Three options remain for #371:

| Option                                                   | Effect                                                                                                                                                                                                                                           | Cost                                                                         |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| A. Docs plus a lint rule                                 | A rule that flags command fields not wrapped in `own()` is the only option that catches omission (#371 lists "analyzer/docs-only").                                                                                                              | A lint package or a documented rule; no core change                          |
| B. Narrow `ownedBy(owner)` on the three command builders | Defined as `build()` followed by `owner.own(command)`; owner typed as the component base; package-internal registration (an unexported symbol in a leaf module in TypeScript, an internal method in C#). No VM `owner` option, no helper owners. | 3 builders × 5 flavors; DISP-015 and BLD-007; a refining ADR for ADR-0090 §3 |
| C. A public lifetime signal                              | A disposal signal on every VM (`AbortSignal` in TypeScript, `CancellationToken` in C#, a publisher in Swift) lets any code tie a resource to a VM, like Angular's `takeUntilDestroyed`.                                                          | New public surface in five flavors; the same ADR-0090 §3 question            |

The recommendation is A now, then B or C through #371's design gate. Under option B, Heimdall's local `kit/ownedBy.ts` keeps its call sites; under A or C they change.

### 1.8.9. Async Resources and Commands: #376, #378, #372 (D24, D26, D28)

**#376, restart admission.** Add the catalogue's `restart` to the policies under study. Verified constraint: for a resource, restart must mean supersession inside the resource (spec 23 §6). Cancelling the command and then executing it again ends in `Idle` under the default retention, and the second execution is refused there. The default drop rule and CMD-012, CMD-019, DISP-002 and ARES-008 must stay unchanged.

**#378, value accessor.** Add `valueOr(fallback)` to the TypeScript and Python states:

| C#                  | Python               | TypeScript          | Swift                              | Rust                                      |
| ------------------- | -------------------- | ------------------- | ---------------------------------- | ----------------------------------------- |
| `ValueOr(fallback)` | `value_or(fallback)` | `valueOr(fallback)` | `state.value ?? fallback` (exists) | `value().cloned().unwrap_or(..)` (exists) |

- **Naming:** do not use `current`. It collides with `isCurrent` and with the `current` of composites and `ISelectable`.
- **Binding:** it must be a pure function of `state`. ARES-002 announces only `state`, so a getter bound by its own name would never refresh.
- **Presence:** decide it by the state's shape, because `T` may itself be `undefined` or `null`.

**#372, predicate diagnostics.** Add an opt-in builder hook: C# `OnPredicateError(Action<Exception>)`, Python `on_predicate_error`, TypeScript `onPredicateError`, Rust a panic hook. Swift would need an additive throwing-predicate overload. The default stays as spec 04 §2 requires: the exception is not propagated. Sending predicate errors to an `errors` stream on the owning VM is not possible: no VM has one, commands have no owner link, and `canExecute` runs on every render, so the hook needs a deduplication rule.

**Retry and polling.** No new API (D25, D7); both become recipes (§1.11).

### 1.8.10. Clock and Test-Scheduler Contract (D30, D29, Part of D7)

#593 item 13 declined a delayed-task primitive in favor of "a recipe over the dispatcher schedulers". Heimdall is a second consumer with the same needs: polling, transient state and a delayed revert. Verification shows the recipe is not portable:

- Delayed work on the null dispatchers differs. TypeScript defers through `setInterval`. Python raises `WouldBlockException`. C# blocks the thread for the delay.
- Swift and Rust dispatcher closures cannot take a delay.
- TypeScript's `ManualDispatcher` can only flush everything; a periodic action never terminates under it.

**Proposal.** Open one design issue for a cross-flavor clock and virtual-time test-scheduler contract. A small `DelayedTask` helper would sit on top:

- `Schedule(duration, action)` replaces a pending call;
- `Cancel()` and `IsPending`;
- an injected clock.

The contract unblocks several deferred items: polling (#388), TTL invalidation (ADR-0073), retry and timeout (#388), the injected test clock that admission tests need (#376), and the Rust debounce gap in `SearchableState`. The issue should reopen #593 item 13 explicitly and cite this document.

Duration idioms: C# `TimeSpan`, Python `timedelta`, TypeScript milliseconds, Swift `TimeInterval` (ADR-0063), Rust `Duration`.

`TransientStateVM`, a polling VM and a dispatcher-only scheduler rule are all declined in favor of this contract.

### 1.8.11. Vue Adapter `@thekaveh/vmx-vue`, Recipe Fixes, React Parity (D8, D9, D10, D33)

**Fix the recipe now** (independent of the package; a follow-up to #342):

```ts
if (!getCurrentScope()) throw new TypeError("useVm must run inside setup() or an effect scope");
const raw = toRaw(vm);                       // a proxied VM throws on #private reads
let current = raw[property];
const value = shallowRef(current);
let sub: Subscription | undefined;
const start = () => {
  current = raw[property];                   // catch up with changes before mount
  value.value = current;
  sub = raw.hub.messages
    .pipe(filter((m) => m.sender === raw && (m as PropertyChangedMessage<unknown>).propertyName === property))
    .subscribe(() => {
      const next = raw[property];            // a closure read, not a tracked ref read
      if (Object.is(next, current)) triggerRef(value); // same-reference republish
      else { current = next; value.value = next; }    // one trigger per message
    });
};
if (getCurrentInstance()) onMounted(start);  // mounted hooks never run under SSR
else start();
onScopeDispose(() => sub?.unsubscribe());
```

Add tests for a synchronous watcher, a proxied input, an effect scope and SSR. Add one sentence to `docs/content/integration/vue.md`: "Hold view-models in `shallowRef` or `markRaw`."

**The package.** `packages/vue`, version 0.1.0, independent SemVer, `vue-v*` tags, an `npm-vue` environment. ESM, CJS and declarations through tsup. Peers: `@thekaveh/vmx` from 3.24.1, `vue` from 3.5.0, `rxjs` from 7.8.0. React names:

| API                                                         | Note                                                                                        |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `createVmxStore(hub)`, `useVmx(store, selector, equality?)` | Version moves on every message (the #638 lesson). Selectors also answer P12's dotted paths. |
| `useVm(vm)`, `useVm(vm, selector, equality?)`               | Whole-VM or selected                                                                        |
| `useVmProperty(vm, key)`                                    | Recipe-compatible name binding. Keeping it is an owner decision (§1.12).                    |
| `useCommand(command)`, `useCommand(command, parameter)`     | Includes the `ICommandOf<T>` overload; re-reads on next and complete                        |
| `useVmCollection`, `useVmChildren`, `useObservableList`     | Frozen snapshots; `useVmChildren` refreshes on any `TreeStructureChangedMessage`            |
| `useDerivedProperty`, `useAsyncResource`                    | As React; the internal `DerivedProperty` seam may need to become public                     |
| `createVmKey`, `provideVm`, `injectVm`                      | `markRaw` on provide; a clear error outside setup                                           |

**Acceptance rules:**

1. **Raw identity.** Unwrap inputs with `toRaw`, and compare the sender without `instanceof`, as React already does.
1. **One trigger per message.**
1. **No tracked reads in subscribers.**
1. **Lifetime.** Subscribe on mount, catch up, release on unmount or scope disposal. Throw outside a scope; never leak under SSR.
1. **Reactive inputs.** Exactly one listener at a time.
1. **Borrowed lifetime.** Never construct or dispose a VM.
1. **Commands.** Bind the parameter of an `ICommandOf<T>`.
1. **Collections.** Identity and order stay stable.
1. **ADR-0101 §2.4.** The package keeps every invariant there.

CI, release and docs mirror PR #278: `tools/check-vue-package.py`, `tools/smoke-vue-consumer.py`, jobs in `typescript.yml` and `release.yml`, the namespace in `check-version-consistency.py`, `compatibility-matrix.md` §2.2, and the integration docs on all three surfaces.

**Gates (#394).**

- Pilot the package in a minimal real application, with Heimdall as the independent consumer.
- Record the result as a pilot ledger, like the React one.
- Rejection is a valid outcome.

The DOM-behavior helpers stay out of 0.1.0 (D11).

**React parity before Vue semantics freeze.**

1. Release the unreleased fixes in `packages/react/CHANGELOG.md`, with #638.
1. Add the `ICommandOf<T>` overload of `useCommand`.
1. Add a tree-children hook, or document `useVmx(store, () => node.children, shallowEqual)`.
1. Decide context helpers for both packages, or for neither.

### 1.8.12. Multi-Name `whenPropertyChanged` (Part of D23)

An informative overload in the four flavors that ship the helper: C# `params string[]`, Python `*names`, TypeScript `string | readonly string[]`, Swift `String...`. It follows the ADR-0032 and ADR-0050 pattern: a small ADR and a text change to spec 03 §7.2, with no ID. Rust has no such helper (spec 03 §7.2). Until then the one-liner is `this.own(whenPropertyChanged(source.hub, source, "x").subscribe(…))`.

### 1.8.13. Composite Selector on Reconstruct (D35)

All five flavors re-run `Current(selector)` on every construct. Spec 06 §3.2 says "Invoked once during the composite's construct phase", and COMP-025 tests a single construct. A clarifying ADR states that the selector runs on each construct, reconstruct included; COMP-025 is extended or COMP-047 added. Heimdall can then restore its last page with `.current(...)` and `.onCurrentChanged(...)` today and rely on it.

### 1.8.14. TypeScript `HierarchicalVM` Services (D34)

ADR-0009 records the fallback to a private hub in the raw TypeScript constructor as deferred "to the next TypeScript major". Now:

- mark the hub-less overload `@deprecated`;
- document passing services in the children factory, `childrenFactory: (parent) => [new Node({ hub: parent.hub, dispatcher })]`;
- record Rust's `new()` conveniences, which also fabricate hubs, in ADR-0009.

In TypeScript 4.0, `hub` and `dispatcher` become required. Inheriting the parent's hub is declined: the hub is immutable and injected at construction, nodes are built before they are attached, and transfers can cross trees.

## 1.9. Defects and Inconsistencies Found During Verification

| #   | Finding                                                                                                                                                                                                                                      | Action                                                       | Size |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ---- |
| 1   | `own()` on a forwarding decorator: never released in TypeScript, raises in Python, forwarded in Swift and Rust; spec 09 is silent.                                                                                                           | §1.8.5: spec rule, fixes, FWD-005                            | S    |
| 2   | `docs/content/primitives/viewmodel-families/hierarchical-family.md` says a node "owns … its recursive `Children`", against spec 18 §3 and ADR-0105. This likely caused Heimdall's L4 surprise.                                               | Docs fix; add a recipe for disposing a materialized subtree  | S    |
| 3   | Spec 18 §9 cites `ExpandableState<TVM>` "to gate lazy child materialization". The type is non-generic, and it gates traversal (`walkExpanded`), not materialization. ADR-0028 §3.1's materialization through `Expand()` exists in no flavor. | Editorial ADR                                                | S    |
| 4   | Rust `new()` conveniences fabricate private hubs; ADR-0009 does not list this.                                                                                                                                                               | Record in ADR-0009                                           | S    |
| 5   | Re-running `Current(selector)` on reconstruct is untested and the spec says "once".                                                                                                                                                          | §1.8.13                                                      | S    |
| 6   | Python `_own` returns a union, not the generic resource type (`langs/python/src/vmx/components/base.py:1228`), which weakens inline assignment under `mypy --strict`.                                                                        | Typing fix (patch)                                           | S    |
| 7   | Children registered with `own()` are disposed after the parent publishes `Disposed`, the reverse of the depth-first rule for containers.                                                                                                     | Document now; §1.8.4 step 1                                  | S    |
| 8   | `TokenPagedComposition` fetch faults surface only on its commands' `errors` streams.                                                                                                                                                         | Docs                                                         | S    |
| 9   | TypeScript has no `isTreeStructureChanged` raw-message predicate.                                                                                                                                                                            | Optional TypeScript-only addition under the ADR-0094 pattern | S    |
| 10  | AGENTS.md calls TypeScript member-aligned, but chapter 09 records the TypeScript `ForwardingCompositeVM` child gap.                                                                                                                          | Docs accuracy                                                | S    |
| 11  | `@thekaveh/vmx-react` 0.1.1 on npm lacks four unreleased fixes, and #638 is open.                                                                                                                                                            | Release 0.1.2                                                | S    |
| 12  | A typed app message in Rust can only use the payload-less `Message::Custom`; a new variant is source-breaking.                                                                                                                               | Record as a Rust hub ergonomics item; no action now          | —    |

## 1.10. Roadmap

Each phase with a spec change is one additive minor. Phases can merge or reorder; the dependencies in the last column are the only hard order.

| Phase                              | Content                                                                                                                                                                                                                                                                                                                                                                           | Spec                 | Conformance                                                                                   | Depends on                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 0. Fix and document                | Vue recipe fix (§1.8.11). Docs fixes 2, 7, 8 and 10 in §1.9. The consumer recipes in §1.11: requests, polling, retry, latest-wins, cancel at destruct, child cascade, reserved names, `this` capture, `subscribeValue` equality, tree services, restoring the current page. Editorial ADR for items 3 and 4 in §1.9. Python `_own` typing. `@thekaveh/vmx-react` 0.1.2 with #638. | No version change    | None                                                                                          | —                                              |
| 1. Small evidence-backed additions | Forwarding `own()` rule (§1.8.5). `ExpandableState` commands (§1.8.2). Supported child-transition helper and opt-in child order (§1.8.4, steps 1 and 2). Composite selector on reconstruct (§1.8.13). Optional `hint` (§1.8.6, flavor-level). Multi-name `whenPropertyChanged` (§1.8.12, informative).                                                                            | 3.30.0               | About 7: FWD-005, EXP-006 to EXP-008, GRP-014, COMP-046, COMP-047, plus 1 or 2 for the helper | Phase 0 docs for the helper                    |
| 2. Trees and keyed containers      | Tree selection helper with its enablers (§1.8.1). Keyed composite (#618 widened, §1.8.7).                                                                                                                                                                                                                                                                                         | 3.31.0               | About 14: HIER-033 onward and a new keyed prefix                                              | Phase 1 child helper (for the keyed composite) |
| 3. Lifecycle scopes                | `whileConstructed` (§1.8.3) after Heimdall's pilot. #371's decision on command-builder ownership (§1.8.8). The `adopt` design gate (§1.8.4 step 3).                                                                                                                                                                                                                               | 3.32.0               | About 7: DISP or LIFE, BLD-007, UTIL                                                          | §1.8.5 first; pilot evidence                   |
| 4. Async policies and time         | #376 admission with restart. #378 `valueOr`. #372 predicate hook. The clock contract and `DelayedTask` (§1.8.10), then polling and TTL on top.                                                                                                                                                                                                                                    | 3.33.0 and later     | About 10: ARES, CMD and a new timing prefix                                                   | Design issues approved                         |
| V. Vue adapter                     | `@thekaveh/vmx-vue` 0.1.0 (§1.8.11)                                                                                                                                                                                                                                                                                                                                               | None (non-normative) | None                                                                                          | Phase 0 recipe fix; React 0.1.2; #394 gates    |
| M. TypeScript 4.0                  | Required services in the raw `HierarchicalVM` constructor (§1.8.14), together with any other breaking TypeScript changes                                                                                                                                                                                                                                                          | Flavor major         | None                                                                                          | A TypeScript major release                     |

Across phases 1 to 4 the catalog grows from 425 to about 465 library IDs, each with stubs and passing tests in all five flavors.

## 1.11. Guidance for Heimdall Now

These steps use only what VMx 3.30.0 already ships.

| Heimdall code                               | What to do now                                                                                                                                                                                                                                                    |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 37 `{ self }` holders                       | Delete them. Pass `loader: (signal) => this.#fetch(signal)` directly in `super({…})`. VMx calls the loader, the child projection and `currentSelector` only after construction. Do not read subclass state in `modeledHinter`, which runs inside the constructor. |
| 17 `.catch(() => undefined)`                | `void this.resource.reload()` is enough: a superseded or failing reload resolves normally. It rejects only when a hub observer throws during publication.                                                                                                         |
| 6 retry commands                            | `this.own(wrapWith(resource.reloadCommand, () => resource.state.status === AsyncResourceStatus.Error))`.                                                                                                                                                          |
| Seven latest-wins call sites                | `reloadCommand` already supersedes a load that another path started; only its own execution blocks it.                                                                                                                                                            |
| 9 `cancel()` calls in destruct hooks        | Keep them, or pass an owned `AbortController` signal to `load(signal)` and abort it at destruct. `whileConstructed` (§1.8.3) would replace both.                                                                                                                  |
| `PollingResourceVM`                         | Keep it as app code. Merge `retention` with `??`. The tick rule is correct: `Idle` loads, `Loading` skips, anything else reloads. Use the foreground scheduler; `background` is a pool thread in other flavors.                                                   |
| `subscribeValue` avoided in bindings        | `subscribeValue(vm, select, cb, { equality: () => false })` fires on every matching message, including a same-reference republish.                                                                                                                                |
| 18 hand-written property filters            | Use `whenPropertyChanged(hub, source, name)` or `isPropertyChanged(message, { sender, propertyName })`.                                                                                                                                                           |
| One recorder per child in tests             | One `recordPropertyChanges(hub)` without a sender filter records every sender on the shared hub.                                                                                                                                                                  |
| Pages with a null current after reconstruct | Add `.current(...)` and `.onCurrentChanged(...)` to remember the last key. All flavors re-run the selector on each construct (§1.8.13).                                                                                                                           |
| Tree nodes without the app hub              | Pass `hub: parent.hub` and the dispatcher in the children factory.                                                                                                                                                                                                |
| Reverse-order child loops                   | Keep them: insertion order is unspecified, so the two ordering tests rely on behavior VMx does not promise. Move to `_transitionChildren` once it is released, and to `ChildOrder.Reverse` once §1.8.4 step 2 lands.                                              |
| Children registered with `own(new …VM())`   | They are disposed in reverse registration order, after the parent publishes `Disposed`. If sibling order matters, register them in the reverse of the order you need.                                                                                             |
| `status` naming                             | Keep `panelStatus`. Treat `status`, `isConstructed`, `isCurrent`, `name`, `hint`, `type`, `hub` and `propertyChanged` as reserved.                                                                                                                                |
| Vue bindings                                | Hold view-models in `shallowRef` or `markRaw`. Replace the tracked read of `value.value` with a closure variable. Guard every binding with `getCurrentScope()`. Subscribe on mount for SSR.                                                                       |
| `kit/ownedBy.ts`                            | It is a fine interim. Its call sites survive only if #371 picks option B (§1.8.8).                                                                                                                                                                                |
| `kit/selectableTreeNodeVM.ts`               | Keep it until §1.8.1 and §1.8.2 ship. For the open items, watch transfers and invalidation as well as the node's own messages. To model the accordion without reading siblings, use a `DiscriminatorVM` over the sibling keys.                                    |
| `kit/keyedPageCompositeVM.ts`               | Keep it, and bring its `open(key, options)` evidence to #618.                                                                                                                                                                                                     |
| `kit/messages.ts`                           | Keep it as app messages. The hub is hot without replay: a request sent before the host subscribes is lost, and two hosts would both act.                                                                                                                          |

## 1.12. Decisions Needed From the Owner

1. **Clock contract.** Does Heimdall, as a second consumer, justify reopening #593 item 13 as a cross-flavor clock and test-scheduler contract (§1.8.10)?
1. **Construct scope.** A declarative `whileConstructed` or an imperative `ownUntilDestruct`? Which ordering rules? Is a Heimdall pilot the required evidence (§1.8.3)?
1. **Command ownership.** For #371: lint and docs only, narrow builder sugar, or a public lifetime signal (§1.8.8)?
1. **Children of leaf classes.** Ship the supported helper and stop, or open the `adopt` design gate as well (§1.8.4)?
1. **Child order.** Opt-in reverse order on both containers, and LIFO as the default in a future major?
1. **Tree transfers.** Should the old parent publish a notification when a node is transferred out (spec 18 §7), or should the selection helper watch ancestors (§1.8.1)?
1. **Keyed composite.** Accept the widened #618 with retention policies (§1.8.7)?
1. **Vue adapter.** Proceed with Heimdall plus a minimal application as the two pilots? Keep a name-based `useVmProperty`, or offer selectors only? Add context helpers to both packages, or to neither?
1. **Forwarding `own()`.** Confirm that it forwards to the canonical ownership identity (§1.8.5).
1. **TypeScript 4.0.** When does the next TypeScript major land, carrying the required `HierarchicalVM` services?
1. **Catalogue issue.** File a catalogue issue for Heimdall, as #593 did for nnx-studio, and post the folded items on #618, #376, #378, #372, #388, #394, #413, #620, #619, #371, #144 and #407?

## 1.13. Checklist for Each Normative Item

AGENTS.md §4 applies to every item marked normative:

1. Update the chapter and its `## Conformance` section.
1. Add an ADR (ADR-0150 onward) and a row in `spec/ADRs/README.md`. Name the ADRs it refines: ADR-0041 and ADR-0090 for §1.8.3; ADR-0047 for §1.8.4; ADR-0042 for §1.8.13; ADR-0124 and spec 09 for §1.8.5.
1. Add the IDs to `spec/12-conformance.md`, with markers in all five suites in the same PR and a passing executed test for each (`tools/check-conformance-execution.py`).
1. Implement in all five flavors with ADR-0006 names, and add every new disposable type to the disposal inventory.
1. Bump `spec/VERSION`, every flavor version and minimum spec declaration, `compatibility-matrix.md`, every CHANGELOG, and the count claims (README, `spec/README.md`, AGENTS.md, the chapter 00 glossary, chapter 12, the flavor READMEs).
1. Update the three documentation surfaces through `docs/manifest.yaml`, the cross-language naming page and the diagrams (`--check`).

## 1.14. Traceability

- **Claim index.** K, V, O, P, L and F IDs map one-to-one to rows of the catalogue: §2.1 for K, §2.2 for V, §2.3 for O, §2.4 for P, §3 for L and §4 for F. The rows of §1.5 quote each claim in short form.
- **Issues cited.**
  - Open: #142, #144, #364, #371, #372, #376, #378, #388, #391, #392, #394, #403, #407, #413, #618, #619, #620, #638.
  - Closed: #78, #100, #342, #593.
- **Pull requests cited:** #278 (React adapter), #470 (Vue and Solid recipes), #636 and #647 (current `develop`).
- **Main spec references:**
  - spec 00 §2; spec 02 §2.3, §2.4 and §6; spec 03 §1, §3.3 and §7;
  - spec 04 §2 and §8.4; spec 05 §2.3 and §6; spec 06 §3.2, §5 and §9;
  - spec 09; spec 10 §4; spec 13 §2; spec 18 §3, §7 and §9; spec 23 §1, §4, §6, §7 and §8.
- **Main ADRs:** 0003, 0009, 0011, 0015, 0018, 0028, 0040, 0041, 0047, 0050, 0052, 0058, 0072, 0073, 0075, 0083, 0090, 0094, 0095, 0097, 0100, 0101, 0105, 0107, 0108, 0118, 0124, 0129, 0134.
