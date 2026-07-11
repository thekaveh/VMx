# TypeScript Raw-Message Predicates Design

## 1. Status and authorization

Issue #88 is approved for continuous implementation by the active goal directive
and its refined acceptance criteria. This design narrows the original proposal to
the demonstrated TypeScript type-system gap. It does not add artificial APIs to
the other language flavors.

## 2. Problem

VMx exposes higher-level typed hub helpers such as `whenPropertyChanged` and
`propertyValueChangedMessagesFor`, but consumers still need to inspect mixed raw
`IMessage` streams. TypeScript cannot use a bare generic
`PropertyChangedMessage` constructor as the desired type guard in every filter
position. DayDreams therefore repeats local predicates across nine property
sites and one collection site.

The missing layer is runner-agnostic runtime classification with useful
TypeScript narrowing. It is not another observable operator and it is not a new
cross-flavor message behavior.

## 3. Considered approaches

### 3.1 Three direct predicates — selected

Export one predicate per public raw-message family:

```typescript
isPropertyChanged(message, sender?, propertyName?)
isCollectionChanged(message, source?, action?)
isConstructionStatusChanged(message, sender?, status?)
```

This is the most discoverable shape, directly models the three concrete message
classes, and gives TypeScript a type-predicate return at the point where
`Array.filter` and RxJS `filter` need it.

### 3.2 One generic matcher — rejected

A generic `isMessage(message, MessageClass, constraints)` helper would reduce the
function count, but it would require conditional types or unsafe constructor
signatures to preserve each class's generic payload. It would also make sender,
property, action, and status constraints less discoverable.

### 3.3 New RxJS operators — rejected

Curried `filterMessages` operators would couple the raw classification layer to
RxJS and overlap `whenPropertyChanged`. The predicates already compose with
RxJS's existing `filter`; no additional operator is justified.

## 4. Public API

Create `langs/typescript/src/messages/predicates.ts` with these exports:

```typescript
export function isPropertyChanged<TSender = unknown>(
  message: IMessage,
  sender?: TSender,
  propertyName?: string,
): message is PropertyChangedMessage<TSender>;

export function isCollectionChanged<TItem = unknown>(
  message: IMessage,
  source?: object,
  action?: CollectionMutationAction,
): message is CollectionChangedMessage<TItem>;

export function isConstructionStatusChanged(
  message: IMessage,
  sender?: object,
  status?: ConstructionStatus,
): message is ConstructionStatusChangedMessage;
```

Each function first checks the corresponding class with `instanceof`. Optional
constraints use strict identity or exact field equality and are ignored only
when the argument is `undefined`. VMx collection and construction senders are
objects; property-message senders emitted by VMx are also objects, so an omitted
sender is unambiguous for supported messages.

The property predicate infers `TSender` when a sender is supplied. The collection
predicate permits an explicit `TItem` because the current message contract types
its sender as `object` and cannot infer item type from the source. With no generic
argument, it safely narrows to `CollectionChangedMessage<unknown>`.

Export all three functions from both `src/messages/index.ts` and the package root
`src/index.ts`. Do not export an options type, alias, or RxJS-specific wrapper.

## 5. Runtime and type behavior

- A matching concrete message returns `true` when every supplied constraint
  matches.
- A different message family returns `false` before reading family-specific
  fields.
- A wrong sender/source identity, property name, collection action, or status
  returns `false`.
- The functions do not mutate messages, subscribe to a hub, allocate observables,
  or catch errors.
- `messages.filter(isPropertyChanged)` narrows to property messages.
- Constrained arrow predicates narrow the generic sender in both `Array.filter`
  and RxJS `filter` without a cast.
- Existing `whenPropertyChanged` and `propertyValueChangedMessagesFor` remain the
  preferred higher-level APIs when the caller already has a hub, sender, and
  property.

## 6. Specification and versioning

Add ADR-0094 and a TypeScript-specific, non-normative subsection to
`spec/03-messages.md`. The ADR records why runtime/type-guard parity is not added
to languages that already narrow nominal messages idiomatically.

This is an additive public API, so the source line advances to spec/stable
version 3.14.0 and Rust 0.14.0 under the repository's synchronized current-line
policy. All flavors continue to implement 342 library IDs and five THEME
scenarios. No conformance ID is added because the predicates are TypeScript-only
type ergonomics, not language-neutral message behavior.

Update compatibility metadata, all flavor version declarations and changelogs,
current-facing version text, and the TypeScript package lock. Non-TypeScript
changelogs state that their runtime API is unchanged while their declared spec
line advances.

## 7. Tests

Add focused TypeScript unit/type coverage that proves:

- positive and wrong-family runtime classification;
- sender/source identity, property, action, and status constraints;
- generic sender and collection-item types;
- `Array.filter` and RxJS `filter` output types without casts;
- public root and message-barrel exports;
- the generated declaration bundle contains the three signatures.

Follow strict red/green order: add tests and observe missing-export/type failures,
then add the minimal implementation and exports. Run the focused test,
`typecheck:tests`, lint, build, full 715+ test suite, package audit, repository
version/conformance tools, docs gates, examples, and pre-commit.

## 8. Documentation

Update the canonical services/messages page with:

```typescript
hub.messages.pipe(filter(isPropertyChanged))
```

and a constrained sender/property example. Explain when to choose a raw
predicate versus `whenPropertyChanged`. Update the TypeScript flavor page and
in-repo TypeScript README. Generated MkDocs `.io` and wiki output must remain in
sync through the existing docs pipeline. No architecture diagram changes.

## 9. Consumer pilot

Use a disposable DayDreams clone and a local VMx package build. Replace all ten
current local `isPropertyChanged` / `isCollectionChanged` definitions with VMx
exports, preserving each call site's filters. Run the viewmodel tests and
typecheck, the full workspace test suite, and relevant production builds. Record
pre-existing failures separately, commit only inside the disposable clone for
evidence, never push, and verify the user's real DayDreams checkout is unchanged.

## 10. Non-goals

- No cross-flavor predicate APIs.
- No generic `isMessage` abstraction.
- No RxJS operator package or new dependency.
- No replacement or deprecation of existing typed hub helpers.
- No changes to message delivery, ordering, lifecycle, or payload shapes.
- No DayDreams commit or push.
