# 7.4. TypeScript

## 7.4.1. Snapshot

- Current source: TypeScript 3.31.0 implementing spec 3.30.0
- Install and package status: see [Installation](../installation.md) and
  [Availability](../index.md#11-availability).
- Reactive primitive: `rxjs`
- Runtime floor: Node 20.5.0 (the first Node 20 release with `Symbol.dispose`);
  CI tests that exact floor plus Node 20, 22, 24, and 26
- Package name: `@thekaveh/vmx`
- Bundles: dual ESM + CJS, with `notifications`, `conformance`, `testing`, and
  `devtools` subpaths
- Naming idiom: camelCase

## 7.4.2. What To Reach For

TypeScript is the best fit when you want browser-safe VMx usage with modern
bundlers, React-style external-store wiring, or a shared VM layer across web
and desktop webview hosts.

## 7.4.3. Serviced Collections

`ServicedObservableCollection<T>` exposes a local `collectionChanged`
observable and can forward the same message to an optional hub:

```typescript
const notes = new ServicedObservableCollection<Note>(hub);
const local = notes.collectionChanged.subscribe(message => render(message));

notes.push(first);
notes.push(second);
notes.replace(0, revised);           // setAt remains an alias
notes.move(0, notes.length - 1);     // one Move locally, then on the hub
notes.replaceAll(serverSnapshot);    // one Reset

local.unsubscribe();
```

`remove` deletes only the first `indexOf` match and returns `false` when absent.
`removeAt`, `replace`, and `move` require integer positions in range and reject
invalid positions atomically. Equal-index move, empty clear, and empty-to-empty
replacement are no-ops. Collection messages carry legacy `index` plus
`oldIndex` / `newIndex`. Items remain caller-owned. Choose `ObservableList<T>`
for list-local batching and the `Count` channel.

Use `KeyedServicedObservableCollection<TKey,TItem>` when that ordered list also
needs captured-key access:

```typescript
const notesById = new KeyedServicedObservableCollection<string, Note>({
  keyOf: note => note.id,
  hub,
});
notesById.push(first);
const note = notesById.get(first.id);
const added = notesById.upsert(revised); // false: Replace at stable position
const removed = notesById.delete(first.id);
```

`has` tests membership. `pop` and native `splice` behavior remain available;
splice projects inserted items and validates the complete candidate atomically
before commit.

Captured membership keys do not follow mutable item properties;
use indexed replacement or delete-then-add to rekey explicitly. Upserting the
same mutated instance can add a second membership under its new projected key.
Duplicate/projector failure preserves state and emits nothing. Lookup and
target discovery are expected O(1), append is amortized O(1), and ordered
middle shifts remain O(n). Local delivery precedes optional hub publication;
hub transactions defer only the latter. The collection has no batch, VM
lifecycle interface, or ownership of stored items.

## 7.4.4. Imperative Engine Bridge

`subscribeValue` returns an RxJS `Subscription` and uses `Object.is` unless an
`equality` option is supplied:

```typescript
const exposureSubscription = subscribeValue(
  cameraVm,
  vm => vm.model.exposure,
  exposure => { material.uniforms.exposure.value = exposure; },
  { fireImmediately: true },
);

// Host adapter disposal:
exposureSubscription.unsubscribe();
```

The callback receives `(current, previous)`; immediate delivery uses the
initial value for both. The selector reevaluates after every property message
from this fixed VM rather than on every render frame. The host adapter owns the
subscription; VMx does not attach it to the observed VM's lifetime.

## 7.4.5. Raw Message Predicates

The package root and message barrel export three filter-safe type predicates:

| Call                                                                            | Narrowed message                                                   |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `isPropertyChanged(message)` or `isPropertyChanged(message, { propertyName? })` | `PropertyChangedMessage<unknown>`                                  |
| `isPropertyChanged(message, { sender, propertyName? })`                         | `PropertyChangedMessage<TSender>` inferred from the checked sender |
| `isCollectionChanged(message)` or any source/action constraints                 | `CollectionChangedMessage<unknown>`                                |
| `isConstructionStatusChanged(message)` or its sender/status constraints         | `ConstructionStatusChangedMessage`                                 |

Each predicate also has a unary overload, so calls such as
`messages.filter(isPropertyChanged)` and RxJS
`filter(isPropertyChanged)` narrow without a consumer cast. Property sender
narrowing requires a supplied sender. Collection predicates always retain an
`unknown` payload, even for a typed `ServicedObservableCollection<TItem>` source,
because source identity cannot prove the independently constructed message item
type. Optional constraint fields use own-property presence, so a field explicitly
supplied as `undefined` compares exactly instead of behaving like an omitted
field.

Use these predicates for mixed raw message arrays and streams. When the hub,
sender, and property are already known, `whenPropertyChanged` is the shorter
message-returning helper, while `propertyValueChangedMessagesFor` emits the
property's current value.

These predicates are TypeScript-only; see ADR-0094.

## 7.4.6. Consumer Conformance Adapter

The optional `@thekaveh/vmx/conformance` subpath validates versioned JSON
operation/assertion suites and executes consumer factories without depending on
a test framework. It is isolated from the root runtime entry. Full schema,
factory, teardown, diagnostics, and non-goal guidance lives in
[Specification & Conformance](../specification-conformance.md).

## 7.4.7. Runner-Neutral Testing Support

The `@thekaveh/vmx/testing` subpath is isolated from the root runtime entry.
The root `@thekaveh/vmx` entry re-exports nothing from it, and the package
remains `sideEffects: false`. The subpath adds:

- `RecordingMessageHub`, which retains real delivery order;
- `createTestServices()` and `ManualDispatcher`, which separates explicitly
  flushed foreground and background queues;
- semantic property, serviced-collection, and `ObservableList` recorders that
  own their subscriptions;
- parameterless, parameterized, and async command doubles that control
  admission, faults, completion, and cancellation; and
- `createFormHarness()`, which drives the real FormVM state machine through
  set, approve, deny, validation, and persistence failures.

The helpers return ordinary readonly records and import no Vitest or Jest API,
so they work with any runner. Every disposable helper has idempotent
`dispose()`. `RecordingMessageHub`, the recorders, the command doubles, and the
form harness also expose `clear()`, which drops recorded history.

The subpath follows TypeScript-package SemVer. Incompatible removal waits for a
major release. Replacements are deprecated in declarations, documentation, and
the changelog first.

```typescript
import { createTestServices, recordPropertyChanges } from "@thekaveh/vmx/testing";

const services = createTestServices();
const changes = recordPropertyChanges(services.hub, { sender: viewModel });
viewModel.refresh();
expect(changes.propertyNames).toContain("model");
changes.dispose();
services.dispose();
```

The `sender` filter is optional. Without it, one recorder keeps the property
messages of every sender on a shared hub, in delivery order:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#record-every-sender -->

```typescript
const services = createTestServices();
const first = new ComponentVMOf({
  name: "first",
  initialModel: 1,
  hub: services.hub,
  dispatcher: services.dispatcher,
});
const second = new ComponentVMOf({
  name: "second",
  initialModel: 1,
  hub: services.hub,
  dispatcher: services.dispatcher,
});
// No sender filter: the recorder keeps every sender on the hub.
const changes = recordPropertyChanges(services.hub);

first.model = 2;
second.model = 2;

expect(changes.records.map((record) => record.sender)).toEqual([first, second]);
expect(changes.propertyNames).toEqual(["model", "model"]);
changes.dispose();
services.dispose();
```

## 7.4.8. DevTools Observability

The `@thekaveh/vmx/devtools` subpath keeps optional observability out of the
root bundle. `observeHub()` emits transport-neutral events for a custom sink.
`connectReduxDevtools()` adapts them to a structurally typed Redux DevTools
extension without adding an extension dependency. Dispose the bridge before
its owning hub.

Default actions expose only the message type, `senderName`, sequence, and
bounded scalar metadata. VMx never traverses `sender`, models, or collection
items by default. These fields are graph-safe, not necessarily non-sensitive:
consumer-controlled names and scalars can contain identifiers, so redact
actions as well as snapshots when required.

Consumer state exists only when the consumer supplies a named snapshot
selector. An optional per-source serializer can reduce domain values before
bounded JSON sanitization. Circular references, throwing getters, functions,
symbols, and large strings, arrays, and objects are represented safely.
Built-in message names are canonical across ESM and CommonJS builds. Custom
message classes can use `mapAction` for a name that is stable across the
application's own minifier or bundler.

Allow/deny filters run before `sampleEvery`. `throttleMs` coalesces accepted
messages into one action batch, bounds its details with the same serialization
limits, and captures snapshots once at flush. Selector, serializer, redactor,
clock, scheduler, sink, and Redux transport failures are isolated and reported
through `onError` with their phase.

Disposal is idempotent. Pending batches are cancelled when a hub completes, and
reconnecting creates a fresh sequence. `{ extension: null }`, or a missing
Redux DevTools extension, returns a frozen no-op before any hub subscription,
snapshot, or timer exists.

The bridge ignores incoming DevTools dispatches. Hub messages do not encode
complete or inverse mutations, so replay, time travel, inverse mutation, and
state reconstruction are out of scope. See the
[TypeScript getting-started guide](../getting-started/typescript.md#349-observe-a-hub-safely)
for a complete example.

## 7.4.9. Pointers

- Flavor README:
  [langs/typescript/README.md](../../../langs/typescript/README.md)
- Getting started guide:
  [Getting Started with VMx — TypeScript](../getting-started/typescript.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- React recipe:
  [React Integration](../integration/react.md)

## 7.4.10. Current Example Coverage

- Console: `examples/typescript/console/hello-vmx/`
- React flagship: `examples/typescript/react/notes-showcase/`

The TypeScript README also documents the browser-safety contract and the peer
dependency requirement for `rxjs`.
