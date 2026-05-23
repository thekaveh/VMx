# vmx — TypeScript

Hierarchical lifecycle-aware MVVM viewmodel framework for TypeScript and
JavaScript, spec-compatible with the C# and Python flavors.

## Install

```bash
npm install vmx
```

Requires Node.js ≥ 18 and rxjs ≥ 7.8. TypeScript declarations are bundled —
no `@types/vmx` needed.

## Quick start

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

## API surface

The public API is re-exported from a single entry point:

```ts
import { ... } from "vmx";
```

Key exports:

| Export                   | Description                                      |
| ------------------------ | ------------------------------------------------ |
| `ComponentVM`            | Leaf viewmodel (no model)                        |
| `ComponentVMOf<M>`       | Leaf viewmodel with a typed model                |
| `ReadonlyComponentVMOf<M>` | Leaf VM with read-only model               |
| `CompositeVM<VM>`        | Ordered collection of children + current slot    |
| `CompositeVMOf<M, VM>`   | Model-driven composite                           |
| `GroupVM<VM>`            | Collection without current selection             |
| `AggregateVM1..5<...>`   | Fixed-arity named component slots                |
| `ForwardingComponentVM<M>` | Decorator for `IComponentVMOf<M>`           |
| `ForwardingCompositeVM<VM>` | Decorator for composites                   |
| `RelayCommand`           | Executable command with `canExecute` predicate   |
| `RelayCommandOf<T>`      | Typed command with argument                      |
| `MessageHub`             | Pub/sub hub (rxjs `Subject`-backed)              |
| `RxDispatcher`           | Foreground/background scheduler pair             |
| `ConstructionStatus`     | 5-state lifecycle enum                           |
| `StatusTransitionError`  | Raised on illegal lifecycle operations           |
| `walk(root)`             | DFS pre-order tree traversal generator           |
| `find(root, predicate)`  | Short-circuit tree search                        |

## Conformance

All 75 conformance IDs from `spec/12-conformance.md` are covered.

```
LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
CVM-001..006   COMP-001..013 GRP-001..006   AGG-001..005
FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
```

Run the suite:

```bash
npm test
```

## Development

```bash
# From this directory
npm ci
npm run sync-fixtures   # copy spec/fixtures/*.json → src/fixtures/
npm run typecheck
npm run lint
npm run build
npm test
```

## License

MIT
