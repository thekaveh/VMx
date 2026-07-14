# 7.4. TypeScript

## 7.4.1. Snapshot

- Current source: TypeScript 3.21.0 implementing spec 3.20.0
- Install: `npm install @thekaveh/vmx rxjs`
- Publication status: the scoped package name is the supported surface, but it
  has not been published yet; use a local workspace or source reference until a
  `typescript-v*` release publishes it.
- Reactive primitive: `rxjs`
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
`removeAt`, `replace`, and `move` require integer positions in range;
equal-index move and empty clear are no-ops. Collection messages carry legacy
`index` plus `oldIndex` / `newIndex`. Items remain caller-owned.

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
before commit. Captured membership keys do not follow mutable item properties;
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
initial value for both. The host adapter owns the subscription, and the
selector reevaluates after every property message from this fixed VM rather
than on every render frame.

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

These predicates are TypeScript-only type ergonomics, not new message behavior.
The other flavors already have idiomatic nominal/runtime checks, so ADR-0094
intentionally adds no artificial cross-flavor API parity requirement and no
conformance ID.

## 7.4.6. Consumer Conformance Adapter

The optional `@thekaveh/vmx/conformance` subpath validates versioned JSON
operation/assertion suites and executes consumer factories without depending on
a test framework. It is isolated from the root runtime entry. Full schema,
factory, teardown, diagnostics, and non-goal guidance lives in
[Specification & Conformance](../specification-conformance.md).

## 7.4.7. Pointers

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

## 7.4.8. Current Example Coverage

- Console: `examples/typescript/console/hello-vmx/`
- React flagship: `examples/typescript/react/notes-showcase/`

The TypeScript README also documents the browser-safety contract and the peer
dependency requirement for `rxjs`.
