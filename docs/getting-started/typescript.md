# Getting Started with VMx — TypeScript

This tutorial walks you through building viewmodels with the VMx TypeScript
library. You will build a `ComponentVMOf<UserModel>`, a `RelayCommand` with a
reactive trigger, and a `CompositeVM<TabVM>` with tab selection — all in a Node
script or test.

> For the normative contracts behind each type, see `spec/05-component-vm.md`,
> `spec/04-commands.md`, and `spec/06-composite-vm.md`.

______________________________________________________________________

## 1. Install

The source tree currently implements v3.8.0. The npm package is not published
yet; use the package command after a `typescript-v*` release publishes it.

```bash
npm install @thekaveh/vmx rxjs
```

For local development from a checked-out clone:

```bash
npm install /path/to/VMx/langs/typescript
```

`@thekaveh/vmx` (renamed in v2.4.0 from the unscoped `vmx` name, which was
unavailable on the npm registry) ships dual ESM + CJS bundles and full
TypeScript declarations. No extra `@types/vmx` package is needed.

______________________________________________________________________

## 2. Wire up `MessageHub` and `RxDispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that knows about your scheduler pair.

### 2.1 Option A — immediate (Node scripts / synchronous tests)

```ts
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();
// Both foreground and background use queueScheduler (synchronous).
// Safe for Node scripts and vitest suites with no async event loop.
```

### 2.2 Option B — custom schedulers (browser / async environments)

```ts
import { asyncScheduler, animationFrameScheduler } from "rxjs";
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";

const hub = new MessageHub();
const dispatcher = new RxDispatcher(
  animationFrameScheduler, // foreground — UI thread / rAF
  asyncScheduler,          // background — macro-task queue
);
```

______________________________________________________________________

## 3. Build a `ComponentVMOf<UserModel>`

`ComponentVMOf<M>` is the primary leaf viewmodel. It holds a typed model, fires
`PropertyChangedMessage` on the hub when the model changes, and participates in
the lifecycle state machine
(`Destructed → Constructing → Constructed → Destructing → Destructed`).

```ts
import {
  ComponentVMOf,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "@thekaveh/vmx";

interface UserModel {
  name: string;
  email: string;
}

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

// Build the viewmodel — every builder setter returns a NEW builder (immutable).
const userVM = ComponentVMOf.builder<UserModel>()
  .name("user-card")
  .model({ name: "Alice", email: "alice@example.com" })
  .services(hub, dispatcher)
  // Derive a display hint from the model.
  .modeledHinter((m) => m.name)
  // Optional callbacks.
  .onConstruct(() => console.log("user-card constructed"))
  .onDestruct(() => console.log("user-card destructed"))
  .build();

// Subscribe to hub messages BEFORE constructing.
hub.messages.subscribe((msg) => {
  if (msg instanceof PropertyChangedMessage && msg.sender === userVM) {
    console.log(`Property '${msg.propertyName}' changed on ${msg.senderName}`);
  }
});

// construct() transitions Destructed → Constructing → Constructed.
userVM.construct();
// stdout: "user-card constructed"

// Update the model.
userVM.model = { name: "Alice Smith", email: "asmith@example.com" };
// stdout: "Property 'model' changed on user-card"

console.log(userVM.modeledHint); // "Alice Smith"
console.log(userVM.isConstructed); // true
```

> See `spec/05-component-vm.md` for the full component contract and
> `spec/03-messages.md` for the `PropertyChangedMessage` schema.

______________________________________________________________________

## 4. Build a `RelayCommand`

`RelayCommand` wraps an optional `execute` callback, an optional `canExecute`
predicate, and a set of RxJS `Observable` triggers that signal `canExecute` may
have changed.

```ts
import { Subject } from "rxjs";
import { RelayCommand } from "@thekaveh/vmx";

const canSaveTrigger = new Subject<void>();
let isDirty = false;

const saveCommand = RelayCommand.builder()
  .task(() => {
    console.log("Saving…");
    isDirty = false;
    canSaveTrigger.next(); // re-evaluate canExecute
  })
  .predicate(() => isDirty)
  .triggers(canSaveTrigger)
  .build();

console.log(saveCommand.canExecute()); // false

isDirty = true;
canSaveTrigger.next(); // fires canExecuteChanged

saveCommand.canExecuteChanged.subscribe(() =>
  console.log(`  canExecute is now ${saveCommand.canExecute()}`)
);

console.log(saveCommand.canExecute()); // true
saveCommand.execute();                 // prints "Saving…"
console.log(saveCommand.canExecute()); // false again

// Dispose to unsubscribe all trigger subscriptions.
saveCommand.dispose();
```

> See `spec/04-commands.md` for the full command contract.

______________________________________________________________________

## 5. Build a `CompositeVM<TabVM>`

`CompositeVM<VM>` owns an ordered child collection and a `current` selection
slot. Children are provided by a factory that runs on the first `construct()`
call.

```ts
import {
  ComponentVMOf,
  CompositeVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "@thekaveh/vmx";

interface TabModel {
  title: string;
}

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

const tab1 = ComponentVMOf.builder<TabModel>()
  .name("home-tab")
  .model({ title: "Home" })
  .services(hub, dispatcher)
  .build();

const tab2 = ComponentVMOf.builder<TabModel>()
  .name("settings-tab")
  .model({ title: "Settings" })
  .services(hub, dispatcher)
  .build();

const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
  .name("tab-bar")
  .services(hub, dispatcher)
  .children(() => [tab1, tab2])
  .onConstruct(() => console.log("tab-bar ready"))
  .build();

// Watch for current-selection changes via the hub.
hub.messages.subscribe((msg) => {
  if (msg instanceof PropertyChangedMessage && msg.sender === tabs) {
    if (msg.propertyName === "current") {
      const title = tabs.current ? tabs.current.model.title : "(none)";
      console.log(`Selected tab: ${title}`);
    }
  }
});

// construct() cascades: the composite constructs itself then each child.
tabs.construct();
// stdout: "tab-bar ready"

// Select a tab — publishes PropertyChangedMessage for "current" and
// sets child.isCurrent.
tabs.current = tab2; // stdout: "Selected tab: Settings"
tabs.current = tab1; // stdout: "Selected tab: Home"

console.log([...tabs].map((c) => c.name)); // ["home-tab", "settings-tab"]
console.log(tab2.isCurrent);               // false
```

> See `spec/06-composite-vm.md` for the full `CompositeVM` contract, including
> `CollectionChangedEvent` and `BatchUpdate` semantics.

______________________________________________________________________

## 6. Lifecycle and cleanup

Every VM follows a five-state lifecycle:
`Destructed → Constructing → Constructed → Destructing → Destructed`, plus the
terminal `Disposed`.

```ts
import { ConstructionStatus } from "@thekaveh/vmx";

console.log(userVM.status); // ConstructionStatus.Constructed

// reconstruct() is destruct() + construct() in a single call. It is only valid
// from Constructed (canReconstruct() is true iff status === Constructed); it
// round-trips through Destructed and back to Constructed.
userVM.reconstruct();
console.log(userVM.status); // ConstructionStatus.Constructed

// destruct() transitions back to Destructed and runs onDestruct.
userVM.destruct();
console.log(userVM.status); // ConstructionStatus.Destructed

// dispose() is terminal and idempotent. Calling construct() or destruct()
// on a disposed VM raises StatusTransitionError.
userVM.dispose();
console.log(userVM.status); // ConstructionStatus.Disposed

// CompositeVM.dispose() disposes children, then itself.
tabs.dispose();

// MessageHub.dispose() completes the underlying Rx Subject.
hub.dispose();
```

> See `spec/02-lifecycle.md` for the full transition table (LIFE-001..014).

______________________________________________________________________

## 7. Threading

`RxDispatcher` pairs two RxJS schedulers:

| Scheduler               | Typical mapping                       |
| ----------------------- | ------------------------------------- |
| `dispatcher.foreground` | UI thread / `animationFrameScheduler` |
| `dispatcher.background` | `asyncScheduler` / worker threads     |

All hub observations delivered on `foreground` are safe to bind to UI controls.
Use `observeOn` from `rxjs/operators` to marshal:

```ts
import { filter, observeOn } from "rxjs/operators";
import { PropertyChangedMessage } from "@thekaveh/vmx";

hub.messages.pipe(
  filter((m): m is PropertyChangedMessage<unknown> => m instanceof PropertyChangedMessage),
  observeOn(dispatcher.foreground), // marshal to UI scheduler
).subscribe((msg) => updateLabel(msg));
```

> See `spec/11-threading.md` for the THR-001..THR-004 conformance rules.

______________________________________________________________________

## 8. Where to go next

| Resource                      | Path                                     |
| ----------------------------- | ---------------------------------------- |
| Spec overview                 | `spec/00-overview.md`                    |
| Lifecycle contract            | `spec/02-lifecycle.md`                   |
| Message schema                | `spec/03-messages.md`                    |
| Commands                      | `spec/04-commands.md`                    |
| ComponentVM contract          | `spec/05-component-vm.md`                |
| CompositeVM contract          | `spec/06-composite-vm.md`                |
| Builder spec                  | `spec/10-builders.md`                    |
| Threading rules               | `spec/11-threading.md`                   |
| Tree utilities (`walk/find`)  | `spec/13-tree-utilities.md`              |
| Architecture decision records | `spec/ADRs/`                             |
| Hello-VMx example             | `examples/typescript/console/hello-vmx/` |
| Conformance test suite        | `langs/typescript/tests/conformance/`    |
