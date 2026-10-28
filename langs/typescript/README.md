# @thekaveh/vmx — TypeScript

Hierarchical lifecycle-aware MVVM viewmodel framework for TypeScript and
JavaScript, spec-compatible with the C#, Python, Swift, and Rust flavors.

## 1. Status

**v3.31.0 source** — implements `spec-v3.30.0` end-to-end. 444/444 library
conformance IDs pass. Published runtime requires Node ≥ 20.5.0 and rxjs ≥ 7.8;
repository tests require Node 20.19+, 22.13+, or 24+ for jsdom 29. Dual ESM + CJS
bundles; TypeScript declarations are bundled — no `@types/vmx` needed.
Opt-in subpaths provide `@thekaveh/vmx/notifications` and the
test-framework-neutral `@thekaveh/vmx/conformance` adapter runner. The
`@thekaveh/vmx/testing` subpath adds runner-neutral fixtures, recorders,
command doubles, and a FormVM harness, and `@thekaveh/vmx/devtools` adds an
optional Redux DevTools bridge.

## 2. Install

```bash
npm install @thekaveh/vmx rxjs
```

Releases are published to [npm](https://www.npmjs.com/package/@thekaveh/vmx)
from `typescript-v*` tags on `main`, with provenance. Version 3.30.0 is on npm
and implements spec 3.29.0; the 3.31.0 source line is not published.

To build from source instead of npm, use a VMx checkout cloned beside the
consumer:

```bash
npm --prefix ../VMx/langs/typescript ci
npm --prefix ../VMx/langs/typescript run build
npm install ../VMx/langs/typescript rxjs
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
[C# Quick start](https://github.com/thekaveh/VMx/blob/main/langs/csharp/README.md#3-quick-start) and
[Python Quick start](https://github.com/thekaveh/VMx/blob/main/langs/python/README.md#3-quick-start) — only the
identifier casing differs.

See [Getting Started with VMx — TypeScript](https://github.com/thekaveh/VMx/blob/main/docs/content/getting-started/typescript.md)
for the full walkthrough.

### 3.1 Cross-language naming

The concepts are identical across the five flavors; identifier casing follows
each language idiom (ADR-0006). See the
[cross-language naming table](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/cross-language-naming.md).

### 3.2 Browser usage

VMx-TS is browser-safe and works out of the box with all modern bundlers —
**Vite, Webpack, esbuild, Rollup, Bun, and Tauri webviews**. The dist
contains no runtime imports of `node:fs`, `node:path`, or `node:url`; the
lifecycle-transitions fixture is bundled in at build time.

Minimal Vite/SvelteKit/Next.js install:

```bash
npm install @thekaveh/vmx rxjs
```

No bundler plugins, polyfills, or `node:*` stubs are required. You can
import `@thekaveh/vmx` directly from any browser-side module:

```ts
import { ComponentVMOf, MessageHub, RxDispatcher } from "@thekaveh/vmx";
```

For a worked browser example, see the React `notes-showcase` app under
[`examples/typescript/react/notes-showcase/`](https://github.com/thekaveh/VMx/tree/main/examples/typescript/react/notes-showcase/),
with cross-flavor parity documented in
[`examples/notes-showcase-parity.md`](https://github.com/thekaveh/VMx/blob/main/examples/notes-showcase-parity.md).

A JSDOM smoke test (`tests/browser-build/smoke.test.ts`) runs on every CI
build and asserts that the package keeps loading cleanly in a browser-like
environment — regressions in this area will fail CI.

## 4. API surface

The public API is re-exported from a single entry point:

```ts
import {
  ComponentVM,
  ConstructionStatus,
  MessageHub,
  RelayCommand,
  RxDispatcher,
} from "@thekaveh/vmx";
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
| `AggregateVM1..6<...>`          | Fixed-arity named component slots (ADR-0034) |
| `ForwardingComponentVM<M>`      | Decorator for `IComponentVMOf<M>`                |
| `ForwardingCompositeVM<VM>`     | Decorator for composites                         |
| `RelayCommand` / `RelayCommandOf<T>` | Executable command with `canExecute`        |
| `CompositeCommand`              | Aggregate N inner commands           |
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
| `walkExpanded(root)`            | DFS walk gated on `IExpandable.isExpanded` |
| `find(root, predicate)`         | Short-circuit tree search                        |
| `DerivedProperty<TValue>` / `fromSources` | N-source computed value   |
| `ExpandableState`               | Expansion helper + expand/collapse/toggle commands |
| `SearchableState<T>`            | Debounced filter + optional source signal |
| `AsyncResourceVM<T>`            | Cancellable latest-wins async value state |
| `ILocalizer` / `NullLocalizer`  | i18n hook + null-default             |
| 22× capability interfaces       | `vmx/capabilities/*` (re-exported) — opt-in |
| `HierarchicalVM<TModel, TVM>`   | Recursive tree VM with key-aware `attachMany`    |
| `TreeSelection<TVM>`            | One current node per tree, cleared when it leaves the tree |
| `TreeStructureChangedMessage`   | Tree-structural-change notification  |
| `FormVM<TM>` / `FormVMOptions<TM>` | Snapshot/revert form lifecycle    |
| `IDialogService` / `NullDialogService` | File/confirm/notify dialogs + null |
| `ServicedObservableCollection<T>` | Complete local-before-hub mutation surface |
| `KeyedServicedObservableCollection<TKey, TItem>` | Ordered serviced surface plus captured-key index |
| `ObservableMembershipSource<T>` / `AggregateChangeStream<T>` | Dynamic membership-and-item fan-in with provenance |
| `ObservableList<T>`             | Granular events + atomic `replaceAll`            |
| `ObservableDictionary<K1, K2, V>` | Multi-key observable dictionary    |
| `PagedComposition<TVM>`         | Pageable iterable decorator          |
| Fluent command helpers          | `confirm` / `precedeWith` / `succeedWith` / `wrapWith` over commands |
| `propertyValueChangedMessagesFor` | Hub helper yielding an `Observable<TProperty>` of property-value snapshots |
| `whenPropertyChanged`           | Hub helper yielding matching property-change messages for one name or an array of names |
| `isPropertyChanged` / `isCollectionChanged` / `isConstructionStatusChanged` / `isTreeStructureChanged` | Filter-safe predicates for mixed raw messages |
| `subscribeValue`                | Fixed-VM selected-state bridge returning an RxJS `Subscription` |

### 4.1 Serviced collections

`ServicedObservableCollection<T>` provides local `collectionChanged` delivery
plus optional hub publication. `KeyedServicedObservableCollection<TKey,TItem>`
adds a captured stable-key index (`get`, `upsert`, `delete`, `has`) without
changing the ordered message shape.

Same-index move, empty clear, and empty-to-empty replacement are no-ops. Items
remain caller-owned. Use `ObservableList<T>` for list-local batching and the
`Count` channel. See
[TypeScript serviced collections](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/typescript.md#743-serviced-collections).

### 4.2 Raw message predicates

`isPropertyChanged`, `isCollectionChanged`, `isConstructionStatusChanged`, and
`isTreeStructureChanged` narrow a mixed `IMessage` array or stream without a
cast. Each works directly with `Array.filter` or RxJS `filter`.
`isTreeStructureChanged` also matches a tree message from a second package
copy. They are TypeScript-only type ergonomics (ADR-0094, ADR-0163). See
[TypeScript raw message predicates](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/typescript.md#745-raw-message-predicates).

### 4.3 Imperative engine bridge

`subscribeValue` pushes a selected value from one fixed VM into an imperative
host as `(current, previous)`. It returns an RxJS `Subscription` that the host
owns; VMx does not attach it to the observed VM's lifetime. See
[TypeScript imperative engine bridge](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/typescript.md#744-imperative-engine-bridge).

### 4.4 Consumer conformance adapter

`@thekaveh/vmx/conformance` runs strict, test-runner-neutral
operation/assertion suites against consumer factories. It imports no Vitest or
Jest API and does not parse YAML. See the
[v1 schema](https://github.com/thekaveh/VMx/blob/main/spec/schemas/consumer-conformance-v1.schema.json),
ADR-0102, and
[TypeScript consumer conformance adapter](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/typescript.md#746-consumer-conformance-adapter).

### 4.5 Testing utilities

`@thekaveh/vmx/testing` adds runner-neutral services, recorders, command
doubles, and a FormVM harness. The root entry re-exports nothing from it, and
the package stays `sideEffects: false`. The subpath is public API under package
SemVer. See
[TypeScript runner-neutral testing support](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/typescript.md#747-runner-neutral-testing-support).

### 4.6 DevTools observability

`@thekaveh/vmx/devtools` provides `observeHub()` and an optional
`connectReduxDevtools()` bridge outside the root entry. Default actions carry
only bounded scalar metadata; state appears only through consumer snapshot
selectors. Dispose the bridge before its owning hub. The bridge ignores
incoming DevTools dispatches and gives no replay or time-travel guarantee. See
[TypeScript DevTools observability](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/typescript.md#748-devtools-observability).

## 5. Notifications

The opt-in `@thekaveh/vmx/notifications` sub-path export adds:

| Export                                                            | Description                            |
| ----------------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`      | Notification primitives                |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub`    | Async notification hub + null variant  |
| `makeConfirm(hub, prompt)`                                        | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                                  | Render-side VM for `Notification`      |
| `ConfirmationVM`                                                  | Render-side VM with Approve/Reject     |

## 6. Conformance

Implements all 444 library conformance IDs; THEME scenario IDs live in the
example apps. See [`spec/12-conformance.md`](https://github.com/thekaveh/VMx/blob/main/spec/12-conformance.md).

Run the suite:

```bash
npm test
```

## 7. Development

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

See [`CONTRIBUTING.md`](https://github.com/thekaveh/VMx/blob/main/CONTRIBUTING.md) for the contributor workflow and
[`RELEASING.md`](https://github.com/thekaveh/VMx/blob/main/langs/typescript/RELEASING.md) for the npm release runbook.

## 8. License

Apache-2.0 — see [`LICENSE`](https://github.com/thekaveh/VMx/blob/main/LICENSE) and [`NOTICE`](https://github.com/thekaveh/VMx/blob/main/NOTICE).
