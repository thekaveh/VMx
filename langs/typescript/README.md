# vmx — TypeScript

Hierarchical lifecycle-aware MVVM viewmodel framework for TypeScript and
JavaScript, spec-compatible with the C# and Python flavors.

## 1. Status

**v2.2.0** — implements `spec-v2.2.0` end-to-end. 220/220 conformance IDs
pass. Requires Node ≥ 18 and rxjs ≥ 7.8. Dual ESM + CJS bundles;
TypeScript declarations are bundled — no `@types/vmx` needed. Opt-in
sub-path export `vmx/notifications` ships an `INotificationHub`.

## 2. Install

```bash
npm install vmx
```

## 3. Quick start

```ts
import {
  ComponentVMOf,
  CompositeVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "vmx";

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

interface TabModel { title: string }

const tab1 = ComponentVMOf.builder<TabModel>()
  .name("home").model({ title: "Home" }).services(hub, dispatcher).build();

const tab2 = ComponentVMOf.builder<TabModel>()
  .name("settings").model({ title: "Settings" }).services(hub, dispatcher).build();

const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
  .name("tab-bar")
  .services(hub, dispatcher)
  .children(() => [tab1, tab2])
  .build();

tabs.construct();

tabs.current = tab2;
console.log(tabs.current?.model.title); // "Settings"

tabs.dispose();
hub.dispose();
```

See [docs/getting-started/typescript.md](../../docs/getting-started/typescript.md)
for the full walkthrough.

## 4. API surface

The public API is re-exported from a single entry point:

```ts
import { ... } from "vmx";
```

Key exports:

| Export                          | Description                                      |
| ------------------------------- | ------------------------------------------------ |
| `ComponentVM`                   | Leaf viewmodel (no model)                        |
| `ComponentVMOf<M>`              | Leaf viewmodel with a typed model                |
| `ReadonlyComponentVMOf<M>`      | Leaf VM with read-only model                     |
| `CompositeVM<VM>` / `CompositeVMOf<M,VM>` | Ordered collection + current slot      |
| `GroupVM<VM>`                   | Collection without current selection             |
| `AggregateVM1..5<...>`          | Fixed-arity named component slots                |
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

The opt-in `vmx/notifications` sub-path export (spec v2.0+) adds:

| Export                                                            | Description                            |
| ----------------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction`      | Notification primitives                |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub`    | Async notification hub + null variant  |
| `makeConfirm(hub, prompt)`                                        | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                                  | Render-side VM for `Notification` (spec v2.1) |
| `ConfirmationVM`                                                  | Render-side VM with Approve/Reject (spec v2.1) |

## 5. Conformance

All 220 conformance IDs from `spec/12-conformance.md` are covered.

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
