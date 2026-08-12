# 3.4. Getting Started with VMx — TypeScript

This tutorial walks you through building viewmodels with the VMx TypeScript
library. You will build a `ComponentVMOf<UserModel>`, a `RelayCommand` with a
reactive trigger, and a `CompositeVM<TabVM>` with tab selection — all in a Node
script or test.

> For the contracts behind each type, see the [component
> family](../primitives/viewmodel-families/component-family.md), [command
> families](../primitives/command-families.md), and [composite
> family](../primitives/viewmodel-families/composite-family.md).

______________________________________________________________________

## 3.4.1. Install

The source tree currently implements v3.24.0. The npm package is not published
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

## 3.4.2. Wire up `MessageHub` and `RxDispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that knows about your scheduler pair.

### 3.4.2.1. Option A — immediate (Node scripts / synchronous tests)

```ts
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();
// Both foreground and background use queueScheduler (synchronous).
// Safe for Node scripts and vitest suites with no async event loop.
```

### 3.4.2.2. Option B — custom schedulers (browser / async environments)

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

## 3.4.3. Build a `ComponentVMOf<UserModel>`

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

> See the [component family](../primitives/viewmodel-families/component-family.md)
> for the full component contract and [Services, Messages &
> Dispatching](../primitives/services-messages-dispatching.md) for the
> `PropertyChangedMessage` schema.

______________________________________________________________________

## 3.4.4. Build a `RelayCommand`

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

> See [command families](../primitives/command-families.md) for the full command
> contract.

______________________________________________________________________

## 3.4.5. Build a `CompositeVM<TabVM>`

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

> See the [composite family](../primitives/viewmodel-families/composite-family.md)
> for the full `CompositeVM` contract, including
> `CollectionChangedEvent` and `BatchUpdate` semantics.

______________________________________________________________________

## 3.4.6. Lifecycle and cleanup

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

> See [Lifecycle & Messaging](../architecture/lifecycle-messaging.md) for the
> full lifecycle contract (`LIFE-001..015`),
> including the transition table and admitted-hook/disposal coordination.

______________________________________________________________________

## 3.4.7. Threading

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

> See [Services, Messages &
> Dispatching](../primitives/services-messages-dispatching.md) for the
> THR-001..THR-004 conformance rules.

______________________________________________________________________

## 3.4.8. Test viewmodels without runner-specific fixtures

The `@thekaveh/vmx/testing` subpath supplies hermetic services and semantic
recorders without importing Vitest or Jest:

```ts
import { createTestServices, recordPropertyChanges } from "@thekaveh/vmx/testing";

const services = createTestServices();
const changes = recordPropertyChanges(services.hub, {
  sender: userVM,
  propertyName: "model",
});

userVM.model = { name: "Updated", email: "updated@example.com" };

expect(changes.records).toHaveLength(1);
changes.dispose();
services.dispose();
```

Use `ManualDispatcher` when foreground and background work must remain queued
until the test explicitly flushes it. `CommandDouble`, `CommandDoubleOf<T>`,
and `AsyncCommandDouble` expose execution records and controlled admission,
fault, completion, and cancellation. `createFormHarness()` exercises a real
FormVM through set/approve/deny and validation or persistence failures.

These are supported TypeScript-package APIs, isolated from the root runtime
entry and governed by its SemVer. The source-ready subpath becomes installable
from npm only after the first TypeScript publication in issue #57.

______________________________________________________________________

## 3.4.9. Where to go next

| Resource             | Documentation page                                                                             |
| -------------------- | ---------------------------------------------------------------------------------------------- |
| Specification status | [Specification & Conformance](../specification-conformance.md)                                 |
| Lifecycle contract   | [Lifecycle & Messaging](../architecture/lifecycle-messaging.md)                                |
| Messages & threading | [Services, Messages & Dispatching](../primitives/services-messages-dispatching.md)             |
| Commands             | [Command Families](../primitives/command-families.md)                                          |
| Component contract   | [Component Family](../primitives/viewmodel-families/component-family.md)                       |
| Composite contract   | [Composite Family](../primitives/viewmodel-families/composite-family.md)                       |
| Builders & tree      | [Builders, Collections & Tree Utilities](../primitives/builders-collections-tree-utilities.md) |
| Architecture         | [Architecture Map](../architecture/index.md)                                                   |
| TypeScript status    | [TypeScript Flavor](../flavors/typescript.md)                                                  |
| Examples             | [Smaller Examples](../examples/smaller-examples.md)                                            |
