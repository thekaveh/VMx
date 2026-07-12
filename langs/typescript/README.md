# @thekaveh/vmx — TypeScript

Hierarchical lifecycle-aware MVVM viewmodel framework for TypeScript and
JavaScript, spec-compatible with the C#, Python, and Swift flavors.

## 1. Status

**v3.20.0** — implements `spec-v3.20.0` end-to-end. 391/391 library conformance IDs
pass. Requires Node ≥ 20 and rxjs ≥ 7.8. Dual ESM + CJS bundles;
TypeScript declarations are bundled — no `@types/vmx` needed. Opt-in
sub-path export `@thekaveh/vmx/notifications` ships an `INotificationHub`.

> **Package rename in v2.4.0:** the npm package is now
> **`@thekaveh/vmx`** (scoped). The previous unscoped name `vmx` could
> not be claimed on the public npm registry. Imports change from
> `from "vmx"` to `from "@thekaveh/vmx"`; everything else is
> source-compatible.

## 2. Install

The source tree currently implements v3.20.0. The scoped npm package has not
been published yet; use a local workspace/package reference until a
`typescript-v*` release tag publishes it.

```bash
npm install @thekaveh/vmx rxjs
```

`rxjs` is declared as a **peer dependency** (≥ 7.8) so consumers share a
single rxjs instance with VMx — VMx exposes rxjs types (`Observable<T>`
etc.) in its public API. Installing it alongside `@thekaveh/vmx` keeps
pnpm strict isolation happy and avoids double-installation.

## 3. Quick start

The minimum-viable shape is `imports → services → builder
(name + model + services + optional modeledHinter) → construct() → read status`:

```ts
import {
  ComponentVMOf,
  CompositeVM,
  MessageHub,
  RxDispatcher,
} from "@thekaveh/vmx";

interface TabModel { title: string }

// 1. Services (a hub + a dispatcher).
const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

// 2. Build leaves: name, model, services, optional modeledHinter.
const tab1 = ComponentVMOf.builder<TabModel>()
  .name("home")
  .model({ title: "Home" })
  .modeledHinter(m => m.title)            // optional — defaults to () => ""
  .services(hub, dispatcher)
  .build();

const tab2 = ComponentVMOf.builder<TabModel>()
  .name("settings").model({ title: "Settings" }).services(hub, dispatcher).build();

// 3. Build a composite over the leaves.
const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
  .name("tab-bar")
  .services(hub, dispatcher)
  .children(() => [tab1, tab2])
  .build();

// 4. Transition the lifecycle from Destructed → Constructed before use.
tabs.construct();
console.log(tabs.status);             // ConstructionStatus.Constructed

tabs.current = tab2;
console.log(tabs.current?.model.title); // "Settings"

tabs.dispose();
hub.dispose();
```

The C# and Python flavors mirror this shape: see
[C# Quick start](../csharp/README.md#3-quick-start) and
[Python Quick start](../python/README.md#3-quick-start) — only the
identifier casing differs.

See [docs/getting-started/typescript.md](../../docs/getting-started/typescript.md)
for the full walkthrough.

### 3.1 Cross-language naming

The conceptual surface is identical across the four flavors; identifier
casing follows the per-language idiom (see ADR-0006).

| Concept             | C#                  | Python             | TypeScript         | Swift              |
| ------------------- | ------------------- | ------------------ | ------------------ | ------------------ |
| Unmodeled VM        | `ComponentVM`       | `ComponentVM`      | `ComponentVM`      | `ComponentVM`      |
| Modeled VM          | `ComponentVM<M>`    | `ComponentVMOf[M]` | `ComponentVMOf<M>` | `ComponentVMOf<M>` |
| Status property     | `Status`            | `status`           | `status`           | `status`           |
| Builder entrypoint  | `Builder()`         | `builder()`        | `builder()`        | `builder()`        |
| Null hub singleton  | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` |

C# uses PascalCase, Python uses snake_case, TypeScript and Swift use
camelCase. The single substantive divergence is that C# names the modeled
variant with a generic-parameter suffix (`ComponentVM<M>`), while Python,
TypeScript, and Swift use a separate `ComponentVMOf` type because their
generics syntax cannot overload an unparameterised name.

### 3.2 Browser usage

VMx-TS is browser-safe and works out of the box with all modern bundlers —
**Vite, Webpack, esbuild, Rollup, Bun, and Tauri webviews**. The dist
contains no runtime imports of `node:fs`, `node:path`, or `node:url`; the
lifecycle-transitions fixture is bundled in at build time.

Minimal Vite/SvelteKit/Next.js install, after the npm package is published:

```bash
npm install @thekaveh/vmx rxjs
```

No bundler plugins, polyfills, or `node:*` stubs are required. You can
import `@thekaveh/vmx` directly from any browser-side module:

```ts
import { ComponentVMOf, MessageHub, RxDispatcher } from "@thekaveh/vmx";
```

For a worked browser example, see the React `notes-showcase` app under
[`examples/typescript/react/notes-showcase/`](../../examples/typescript/react/notes-showcase/),
with cross-flavor parity documented in
[`examples/notes-showcase-parity.md`](../../examples/notes-showcase-parity.md).

A JSDOM smoke test (`tests/browser-build/smoke.test.ts`) runs on every CI
build and asserts that the package keeps loading cleanly in a browser-like
environment — regressions in this area will fail CI.

## 4. API surface

The public API is re-exported from a single entry point:

```ts
import { ... } from "@thekaveh/vmx";
```

Key exports:

| Export                          | Description                                      |
| ------------------------------- | ------------------------------------------------ |
| `ComponentVM`                   | Leaf viewmodel (no model)                        |
| `ComponentVMOf<M>`              | Leaf viewmodel with a typed model                |
| `ReadonlyComponentVMOf<M>`      | Leaf VM with read-only model                     |
| `CompositeVM<VM>` / `CompositeVMOf<M,VM>` | Ordered collection + current slot      |
| `GroupVM<VM>`                   | Collection without current selection             |
| `IVmCollection<VM>`            | Shared group/composite collection + atomic move  |
| `ISelectableVmCollection<VM>`  | Composite-only current-selection extension       |
| `AggregateVM1..6<...>`          | Fixed-arity named component slots (arity 6 added in spec v2.2.0 — see ADR-0034) |
| `ForwardingComponentVM<M>`      | Decorator for `IComponentVMOf<M>`                |
| `ForwardingCompositeVM<VM>`     | Decorator for composites                         |
| `RelayCommand` / `RelayCommandOf<T>` | Executable command with `canExecute`        |
| `CompositeCommand`              | Aggregate N inner commands (spec v2.0)           |
| `DecoratorCommand`              | Wrap a command with pre/post + can-execute gate  |
| `ConfirmationDecoratorCommand`  | Wrap a command with an async confirm delegate    |
| `ModeledCrudCommands<M, VM>`    | Create / UpdateCurrent / DeleteCurrent helper    |
| `MessageHub`                    | Pub/sub hub (rxjs `Subject`-backed)              |
| `NullMessageHub.INSTANCE`       | Null-object variant per ADR-0017                 |
| `RxDispatcher`                  | Foreground/background scheduler pair             |
| `NullDispatcher.INSTANCE`       | Null-object variant per ADR-0017                 |
| `ConstructionStatus`            | 5-state lifecycle enum                           |
| `StatusTransitionError`         | Raised on illegal lifecycle operations           |
| `BuilderValidationError`        | Raised when a builder is missing required fields |
| `walk(root)`                    | DFS pre-order tree traversal generator           |
| `walkExpanded(root)`            | DFS walk gated on `IExpandable.isExpanded` (v2.0) |
| `find(root, predicate)`         | Short-circuit tree search                        |
| `DerivedProperty<TValue>` / `fromSources` | N-source computed value (v2.0)   |
| `ExpandableState`               | `IExpandable`+`ICollapsible` helper (spec v2.0)  |
| `SearchableState<T>`            | Debounced filter + optional source signal (v3.19) |
| `AsyncResourceVM<T>`            | Cancellable latest-wins async value state (v3.20) |
| `ILocalizer` / `NullLocalizer`  | i18n hook + null-default (spec v2.0)             |
| 22× capability interfaces       | `vmx/capabilities/*` (re-exported) — opt-in v2.0+ |
| `HierarchicalVM<TModel, TVM>`   | Recursive tree VM with key-aware `attachMany`    |
| `TreeStructureChangedMessage`   | Tree-structural-change notification (spec v2.1)  |
| `FormVM<TM>` / `FormVMOptions<TM>` | Snapshot/revert form lifecycle (spec v2.1)    |
| `IDialogService` / `NullDialogService` | File/confirm/notify dialogs + null (spec v2.1) |
| `ServicedObservableCollection<T>` | Complete local-before-hub mutation surface (spec v3.16) |
| `KeyedServicedObservableCollection<TKey, TItem>` | Ordered serviced surface plus captured-key index (spec v3.17) |
| `ObservableMembershipSource<T>` / `AggregateChangeStream<T>` | Dynamic membership-and-item fan-in with provenance (spec v3.18) |
| `ObservableList<T>`             | Granular events + atomic `replaceAll`            |
| `ObservableDictionary<K1, K2, V>` | Multi-key observable dictionary (spec v2.1)    |
| `PagedComposition<TVM>`         | Pageable iterable decorator (spec v2.1)          |
| Fluent command helpers          | `confirm` / `precedeWith` / `succeedWith` / `wrapWith` over commands (spec v2.1) |
| `propertyValueChangedMessagesFor` | Hub helper yielding an `Observable<TProperty>` of property-value snapshots (spec v2.1) |
| `whenPropertyChanged`           | Hub helper yielding matching property-change messages |
| `isPropertyChanged` / `isCollectionChanged` / `isConstructionStatusChanged` | Filter-safe predicates for mixed raw messages (spec v3.14) |
| `subscribeValue`                | Fixed-VM selected-state bridge returning an RxJS `Subscription` (spec v3.15) |

### 4.1 Serviced collections

Use `ServicedObservableCollection<T>` for local `collectionChanged` delivery
plus optional hub publication:

```ts
const notes = new ServicedObservableCollection<Note>(hub);
const local = notes.collectionChanged.subscribe(render);

notes.push(first);
notes.push(second);
notes.replace(0, revised);        // setAt remains an alias
notes.move(0, notes.length - 1);  // one Move locally, then on the hub
notes.replaceAll(serverSnapshot); // one Reset

local.unsubscribe();
```

`remove` deletes the first `indexOf` match and returns `false` when absent.
Indexed operations reject invalid positions atomically. Same-index move, empty
clear, and empty-to-empty replacement are no-ops. Messages retain `index` and
add `oldIndex` / `newIndex`; items remain caller-owned. Choose
`ObservableList<T>` for list-local batching and the `Count` channel.

Choose `KeyedServicedObservableCollection<TKey,TItem>` for stable-key access
without changing the ordered message shape:

```ts
const notesById = new KeyedServicedObservableCollection<string, Note>({
  keyOf: note => note.id,
  hub,
});
notesById.push(first);
const note = notesById.get(first.id);
const added = notesById.upsert(revised); // false: Replace at stable position
const removed = notesById.delete(first.id);
```

`has` tests membership; `pop` and atomic final-result `splice` remain available.
Keys are captured until indexed replacement or delete-then-add. Duplicate and
projector failures preserve state. Lookup/target discovery are expected O(1),
while ordered middle shifts remain O(n). Local delivery stays immediate before
optional hub delivery, and stored items remain caller-owned.

### 4.2 Raw message predicates

All three predicates accept an `IMessage` and narrow it to an existing concrete
message type. Each has a unary overload for direct use with `Array.filter` or
RxJS `filter`, plus inline constraint-object overloads:

| Call signature | Result after a match |
| -------------- | -------------------- |
| `isPropertyChanged(message)` or `isPropertyChanged(message, { propertyName? })` | `PropertyChangedMessage<unknown>` |
| `isPropertyChanged(message, { sender, propertyName? })` | `PropertyChangedMessage<TSender>` inferred from the checked sender |
| `isCollectionChanged(message)` or any source/action constraints | `CollectionChangedMessage<unknown>` |
| `isConstructionStatusChanged(message)` or its sender/status constraints | `ConstructionStatusChangedMessage` |

The unconstrained unary form is the shortest way to classify a whole mixed
stream:

```ts
import {
  ConstructionStatus,
  isCollectionChanged,
  isConstructionStatusChanged,
  isPropertyChanged,
  ServicedObservableCollection,
} from "@thekaveh/vmx";
import { filter } from "rxjs";

interface Note { readonly title: string }

const notes = new ServicedObservableCollection<Note>(hub);

const propertyChanges = hub.messages.pipe(filter(isPropertyChanged));

const modelChanges = hub.messages.pipe(
  filter((message) =>
    isPropertyChanged(message, { sender: vm, propertyName: "model" }),
  ),
);

const addedNotes = hub.messages.pipe(
  filter((message) =>
    isCollectionChanged(message, {
      source: notes,
      action: "add",
    }),
  ),
);

const constructed = hub.messages.pipe(
  filter((message) =>
    isConstructionStatusChanged(message, {
      sender: vm,
      status: ConstructionStatus.Constructed,
    }),
  ),
);
```

Generic property senders cannot be selected without runtime evidence and are
inferred only from a supplied sender constraint. Collection predicates always
retain `CollectionChangedMessage<unknown>`, even for a typed
`ServicedObservableCollection<TItem>` source, because source identity cannot
prove the independently constructed message payload type. Optional fields use
own-property presence: an explicitly supplied `undefined` value compares
exactly, while an omitted field disables that constraint. No cast is required
for any predicate.

Use raw predicates to classify mixed `IMessage` arrays or streams. If the hub,
sender, and property are already known, prefer `whenPropertyChanged` for the
matching message or `propertyValueChangedMessagesFor` for the property's current
value.

This API is intentionally TypeScript-only. It fills a TypeScript type-narrowing
gap without changing message semantics; other flavors already use their
idiomatic nominal/runtime checks, so ADR-0094 adds no artificial cross-flavor
surface or conformance ID.

### 4.3 Imperative engine bridge

Use `subscribeValue` to update an engine uniform only when selected VM state
changes:

```typescript
const exposureSubscription = subscribeValue(
  cameraVm,
  vm => vm.model.exposure,
  exposure => { material.uniforms.exposure.value = exposure; },
  { fireImmediately: true },
);

// When the host adapter is disposed:
exposureSubscription.unsubscribe();
```

The callback receives `(current, previous)`; immediate delivery passes the
initial value for both. The selector runs after every property message from
this fixed VM, and `Object.is` suppresses unchanged selections. Pass an
`equality` option for custom equality. The host owns the returned RxJS
`Subscription`; VMx does not attach it to the observed VM's lifetime.

The opt-in `@thekaveh/vmx/notifications` sub-path export (spec v2.0+) adds:

| Export                                                            | Description                            |
| ----------------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`      | Notification primitives                |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub`    | Async notification hub + null variant  |
| `makeConfirm(hub, prompt)`                                        | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                                  | Render-side VM for `Notification` (spec v2.1) |
| `ConfirmationVM`                                                  | Render-side VM with Approve/Reject (spec v2.1) |

## 5. Conformance

All 391 library conformance IDs from `spec/12-conformance.md` are covered (the 5 THEME scenario IDs live in the flagship example apps — see CONTRIBUTING §2.5).

```
v1.x   LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
       CVM-001..010   COMP-001..013 GRP-001..006   AGG-001..005
       FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
v2.0   CAP-001..020   NULL-001..003 DPROP-001..012 CMDD-001..009
       NOTIF-001..010 COMP-014..024 GRP-007..010   EXP-001..005
       LOC-001..003
v2.1   HIER-001..014  DIA-001..008  FORM-001..010  NOTIF-011..016
       COL-001..023   CMD-008..011  CAP-021..022
v2.2   AGG-006
v2.3   BLD-005        FORM-011..013 HIER-015..017
v2.4   THEME-001..005
v2.5   HIER-018       NOTIF-017     FORM-014
v2.6   COMP-025..026
v3.0   LIFE-014       FORM-015      CMDD-010      COMP-027      CMD-012
v3.1   CMD-013        COL-024..031  COMP-028..037 FORM-016..023
       DIA-009..013   HIER-019..022 DISC-001..006 BLD-006 GRP-011
v3.2   HUB-008..013
v3.3   CVM-007..009
v3.4   DISP-001..006
v3.5   COL-032..039
v3.6   CMD-014..019
v3.7   FORM-024..029
v3.8   HIER-023..030
v3.9   COL-040..047
v3.10  DISP-007..013
v3.11  DISP-014
v3.12  FORM-030
v3.15  SUBV-001..004
v3.16  COL-048..055
v3.17  COL-056..064
v3.18  AGCH-001..010
```

Run the suite:

```bash
npm test
```

## 6. Development

```bash
# From this directory
npm ci
npm run sync-fixtures   # copy spec/fixtures/*.json → src/fixtures/
npm run typecheck
npm run typecheck:tests
npm run lint
npm run build
npm test
```

## 7. License

Apache-2.0 — see [`LICENSE`](../../LICENSE) and [`NOTICE`](../../NOTICE).
