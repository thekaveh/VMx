# 7.4. TypeScript

## Snapshot

- Install: `npm install @thekaveh/vmx rxjs`
- Publication status: the scoped package name is the supported surface, but it
  has not been published yet; use a local workspace or source reference until a
  `typescript-v*` release publishes it.
- Reactive primitive: `rxjs`
- Naming idiom: camelCase

## What To Reach For

TypeScript is the best fit when you want browser-safe VMx usage with modern
bundlers, React-style external-store wiring, or a shared VM layer across web
and desktop webview hosts.

## Raw Message Predicates

The package root and message barrel export three filter-safe type predicates:

| Predicate                                                          | Optional exact constraints                                         | Narrowed message                   |
| ------------------------------------------------------------------ | ------------------------------------------------------------------ | ---------------------------------- |
| `isPropertyChanged<TSender>(message, { sender?, propertyName? }?)` | sender identity and property name                                  | `PropertyChangedMessage<TSender>`  |
| `isCollectionChanged<TItem>(message, { source?, action? }?)`       | source identity and `"add"`, `"remove"`, `"replace"`, or `"reset"` | `CollectionChangedMessage<TItem>`  |
| `isConstructionStatusChanged(message, { sender?, status? }?)`      | sender identity and `ConstructionStatus`                           | `ConstructionStatusChangedMessage` |

Each predicate also has a unary overload, so calls such as
`messages.filter(isPropertyChanged)` and RxJS
`filter(isPropertyChanged)` narrow without a consumer cast. Supply the explicit
`TItem` to `isCollectionChanged<TItem>` when the collection item type matters;
the message source itself cannot carry that generic information.

Use these predicates for mixed raw message arrays and streams. When the hub,
sender, and property are already known, `whenPropertyChanged` is the shorter
message-returning helper, while `propertyValueChangedMessagesFor` emits the
property's current value.

These predicates are TypeScript-only type ergonomics, not new message behavior.
The other flavors already have idiomatic nominal/runtime checks, so ADR-0094
intentionally adds no artificial cross-flavor API parity requirement and no
conformance ID.

## Pointers

- Flavor README:
  [langs/typescript/README.md](../../../langs/typescript/README.md)
- Getting started guide:
  [docs/getting-started/typescript.md](../../getting-started/typescript.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- React recipe:
  [docs/integration/react.md](../../integration/react.md)

## Current Example Coverage

- Console: `examples/typescript/console/hello-vmx/`
- React flagship: `examples/typescript/react/notes-showcase/`

The TypeScript README also documents the browser-safety contract and the peer
dependency requirement for `rxjs`.
