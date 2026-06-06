# @thekaveh/vmx — TypeScript

Hierarchical lifecycle-aware MVVM viewmodel framework for TypeScript and
JavaScript, spec-compatible with the C#, Python, and Swift (subset) flavors.

## 1. Status

**v2.4.0** — implements `spec-v2.4.0` end-to-end. 232/232 conformance IDs
pass. Requires Node ≥ 20 and rxjs ≥ 7.8. Dual ESM + CJS bundles;
TypeScript declarations are bundled — no `@types/vmx` needed. Opt-in
sub-path export `@thekaveh/vmx/notifications` ships an `INotificationHub`.

> **Package rename in v2.4.0:** the npm package is now
> **`@thekaveh/vmx`** (scoped). The previous unscoped name `vmx` could
> not be claimed on the public npm registry. Imports change from
> `from "vmx"` to `from "@thekaveh/vmx"`; everything else is
> source-compatible.

## 2. Install

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

// 4. Transition the lifecycle from Created → Constructed before use.
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

## 3.4 Cross-language naming

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

## 3.5. Browser usage

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
`examples/typescript/react/notes-showcase/` (shipped on the
`examples-notes-showcase` branch, merging in a follow-up).

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
| `SearchableState<T>`            | Debounced filter helper (spec v2.0)              |
| `ILocalizer` / `NullLocalizer`  | i18n hook + null-default (spec v2.0)             |
| 22× capability interfaces       | `vmx/capabilities/*` (re-exported) — opt-in v2.0+ |
| `HierarchicalVM<TModel, TVM>`   | Recursive tree-structured VM (spec v2.1)         |
| `TreeStructureChangedMessage`   | Tree-structural-change notification (spec v2.1)  |
| `FormVM<TM>` / `FormVMOptions<TM>` | Snapshot/revert form lifecycle (spec v2.1)    |
| `IDialogService` / `NullDialogService` | File/confirm/notify dialogs + null (spec v2.1) |
| `ServicedObservableCollection<T>` | Hub-aware observable collection (spec v2.1)    |
| `ObservableList<T>`             | Granular per-mutation events (spec v2.1)         |
| `ObservableDictionary<K1, K2, V>` | Multi-key observable dictionary (spec v2.1)    |
| `PagedComposition<TVM>`         | Pageable iterable decorator (spec v2.1)          |
| Fluent command helpers          | `confirm` / `precedeWith` / `succeedWith` / `wrapWith` over commands (spec v2.1) |
| `propertyValueChangedMessagesFor` | Hub helper yielding an `Observable<TProperty>` of property-value snapshots (spec v2.1) |

The opt-in `@thekaveh/vmx/notifications` sub-path export (spec v2.0+) adds:

| Export                                                            | Description                            |
| ----------------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`      | Notification primitives                |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub`    | Async notification hub + null variant  |
| `makeConfirm(hub, prompt)`                                        | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                                  | Render-side VM for `Notification` (spec v2.1) |
| `ConfirmationVM`                                                  | Render-side VM with Approve/Reject (spec v2.1) |

## 5. Conformance

All 232 conformance IDs from `spec/12-conformance.md` are covered.

```
v1.x   LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
       CVM-001..006   COMP-001..013 GRP-001..006   AGG-001..005
       FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
v2.0   CAP-001..020   NULL-001..003 DPROP-001..012 CMDD-001..009
       NOTIF-001..010 COMP-014..024 GRP-007..010   EXP-001..005
       LOC-001..003
v2.1   HIER-001..014  DIA-001..008  FORM-001..010  NOTIF-011..016
       COL-001..023   CMD-008..011  CAP-021..022
v2.2   AGG-006
v2.3   BLD-005        FORM-011..013 HIER-015..017
v2.4   THEME-001..005
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
npm run lint
npm run build
npm test
```

## 7. License

MIT
