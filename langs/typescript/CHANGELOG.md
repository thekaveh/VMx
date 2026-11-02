# Changelog — @thekaveh/vmx (TypeScript)

All notable changes to the TypeScript flavor of vmx are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `TreeSelection<TVM>`, an opt-in helper that keeps one current node per
  `HierarchicalVM` tree (#667, ADR-0164, HIER-033..HIER-040). Construct it on
  a root node. It exposes `current`, `canSelect(node)`, `select(node)`,
  `clear()`, a hot `currentChanged` stream and `dispose()`. `select` throws an
  `Error` for a node that does not reach the root through `parent` links or
  that has a disposed node on that path. The helper watches the hubs of the
  path from the current node to the root. It clears the selection when the
  node is removed, transferred to another tree, dropped by an ancestor's
  `invalidateChildren`, or disposed, and it keeps the selection after a move
  inside the tree. It never reads `children`, publishes nothing to a hub, and
  never changes a node. The owning VM forwards `currentChanged` to its own
  property notification.
- `isTreeStructureChanged(message, { sender?, change? })`, a fourth raw-message
  predicate (#666, ADR-0163). It narrows to `TreeStructureChangedMessage` and
  works directly with `Array.filter` and RxJS `filter`. It classifies by shape
  as well as by class, so a tree message from a second copy of the package
  still matches.
- `ComponentVMBase._transitionChildren(children, construct, after?)` is now
  supported API, and `ComponentVMBase.ownMember(member)` is new (#661,
  ADR-0162, LIFE-016..LIFE-020). A leaf VM calls `_transitionChildren` from its
  own construct or destruct hook to settle member VMs, one at a time in the
  order given, before it publishes its terminal status. A background member
  defers that status, a member failure rolls the VM back, and a member already
  in transit is joined. A call from outside the VM's own hook throws an `Error`
  and starts no child. `ownMember` registers a member VM that `dispose()`
  disposes, in registration order, before the VM publishes `Disposed`; the
  first member failure is thrown after the whole teardown. The container-only
  `joined` parameter moved to an internal method.
- `ExpandableState.expandCommand`, `collapseCommand` and
  `toggleExpansionCommand` (#660, ADR-0159, EXP-006..008). Each command's
  predicate is the matching `can*` check, its task calls the verb, and its
  `canExecuteChanged` fires on every expansion change. The helper builds each
  command on first read and owns it: `dispose()` disposes the commands, which
  are then inert. An owner re-exports a command instead of building one.
- `whenPropertyChanged` accepts an array of property names:
  `whenPropertyChanged(hub, chart, ["plot", "range"])` emits each message from
  `chart` whose property name is any of the names. It makes one hub
  subscription and emits each matching message once, in hub order. An empty
  array throws `RangeError`. A single string behaves as before (spec/03 §7.2,
  ADR-0160, #664).
- The raw constructors default `hint` to `""`, as the builders do (spec/10
  §4): `ComponentVMBase`, `ComponentVMOf`, `ReadonlyComponentVMOf`,
  `CompositeVMBase`, `CompositeVM`, `CompositeVMOf`, `GroupVM`, and
  `AggregateVM1` to `AggregateVM6`. `ComponentVMOf` and `ReadonlyComponentVMOf`
  also default `modeledHinter` to a hinter that returns `""`. A subclass no
  longer passes `hint: ""` through `super(...)` (#663).
- An opt-in reverse child order for container teardown (ADR-0161, #662).
  `GroupVM`, `CompositeVM` and `CompositeVMOf` builders gain
  `.destructOrder(order)`, and `GroupVM.create` and `CompositeVM.create` accept
  a `destructOrder` field. The new `ChildOrder` type is `"insertion" |
  "reverse"`. With `"reverse"`, destruct, the destruct phase of `reconstruct()`
  and `dispose()` walk the children last child first. The default
  `"insertion"` keeps today's order. Construct order does not change, and
  every child is still disposed before its container (LIFE-013). Covered by
  GRP-014 and COMP-046.

### Changed

- Development type checking now runs TypeScript 7.0. `npm run typecheck` and
  `npm run typecheck:tests` use the native `tsc` of the `typescript-7` alias
  (`npm:typescript@^7.0.2`). `typescript` stays at `^6.0.3`, because
  TypeScript 7 has no JavaScript compiler API, which `@typescript-eslint` and
  the `tsup` declaration build need. The published package does not change.
- `dispose()` re-entered while the VM is disposing is now a no-op (#661,
  ADR-0162). The first call finishes the work: it disposes the registered
  members, then publishes `Disposed`.

### Deprecated

- Building a `HierarchicalVM` subclass without `hub` and `dispatcher`. The
  raw constructor then falls back to a private hub that no application observer
  sees. That overload is `@deprecated`; pass both, or build through
  `HierarchicalVMBuilder`. `@thekaveh/vmx` 4.0 requires them (ADR-0009, #665).
  `HierarchicalVMConstructionContext`, which the builder passes to `vmFactory`,
  now types `hub` and `dispatcher` as required, since `build()` always
  supplies both. A `super(context)` call therefore binds the overload with
  services. Code that builds its own context object must supply both.

### Fixed

- A background VM that waits on a child now rolls back and clears its in-flight
  guard when that wait fails (#1053). The wait can fail in a deferred
  `_transitionChildren` walk, a member hook, a `CompositeVM` selector or a
  member `reconstruct()`, at any nesting depth. Before, the error was thrown
  inside a foreground flush, which dropped the queued rollbacks of waiting
  parents. Those parents stayed `Constructing` or `Destructing`. On a shared
  `queueScheduler` (`RxDispatcher.immediate()`, `NullDispatcher`), the outermost
  background `construct()` or `destruct()` in the flush throws the first failure
  after the flush drains. With separate schedulers, a background hook failure
  still throws on the background (#842). A foreground action throws any other
  failure after the queued lifecycle actions have run. #726 fixed the first
  level of this drop for a throwing background hook.
- `observeHub` now labels a tree message from a second package copy as
  `TreeStructureChangedMessage` (#1079). It classifies tree messages with
  `isTreeStructureChanged`, which matches by class and then by shape (ADR-0163).
  Before, such a message used its constructor name, such as a bundler-renamed
  `TreeStructureChangedMessage$1`, or `Object` for a plain object. Devtools
  filters and grouping by `messageType` then missed it. An application message
  class with the same shape now gets this label too. Use `mapAction` to keep a
  custom name.
- `ObservableDictionary`: `delete` and `clear` now update `keys2` before
  `keys1`, as `add` does (#1075). A `keys1` subscriber now sees the updated
  `keys2`. Before, an entry that a `keys1` subscriber added during `clear` was
  missing from `keys2`. A later add with the same key2 did not list it either.
  If a `keys2` subscriber changes the entries, `keys1` then lists only the keys
  that the entries use.
- The locked ESLint dependency graph now uses `minimatch` 11.0.3 through an
  `overrides` entry. This removes the glob-pattern denial-of-service advisory
  GHSA-g3hv-75wg-m249. ESLint and typescript-eslint still declare `minimatch`
  `^10`, and no 10.x release has the fix.
- `CompositeVM` and `GroupVM` `add`, `insert` and `setAt` throw
  `Error("child must not be null")` for a `null` or `undefined` child and
  leave the children unchanged. Before, they threw `TypeError` after they
  opened the membership transaction and never closed it. Every later
  membership change then threw, and `dispose()` returned without disposing
  the container (#1048).

- `ObservableDictionary`: an entry added from a `keys1` subscriber no longer
  puts `keys2` out of first-appearance order. `keys2` now updates first, so a
  `keys1` subscriber already sees the new key2. When a `keys2` subscriber
  changes the entries, the new key1 goes to its first-appearance position in
  `keys1` (#772).

- `DecoratorCommand`, `CompositeCommand` and `ConfirmationDecoratorCommand`
  now notify their own `canExecuteChanged` subscribers once on `dispose()`. A
  binding then re-reads `canExecute` and shows the disposed wrapper as
  disabled. Before, the wrapper passed the inner stream through and sent
  nothing, so a button bound to it stayed enabled. The wrapper still passes
  on every inner notification and completion. Subscribers of the inner command
  get no notification (#771).

- An index of `-0` no longer reaches a collection event or hub message as
  `-0`. `Number.isInteger(-0)` is true and `-0 < 0` is false, so every index
  guard admitted it. `ObservableList` (`insert`, `removeAt`, `replace`),
  `CompositeVM` and `GroupVM` (`insert`, `removeAt`, `setAt`, `move`), and
  `ServicedObservableCollection` and `KeyedServicedObservableCollection`
  (`removeAt`, `replace`, `setAt`, `move`) now emit `+0`. After
  `replace(-0, …)`, a later keyed `upsert` or `delete` also emits `+0`. The
  `PagedComposition.currentPageIndex` setter also stores `+0` (#769).
- The default `FormVM` dirty comparison (`deepEquals`) checks the four boxed
  primitive constructors directly instead of in a loop. The loop almost
  doubled the cost of comparing most object pairs. On a 2,000-row model one
  comparison now takes about 1.05x its cost before #636, against 1.69x (#767).
- `ConfirmationVM.dispose()` runs the base teardown before it disposes
  `approveCommand` and `rejectCommand`. An observer of a command's final
  `canExecuteChanged` value can no longer resolve the hub during disposal
  (#753).
- The default `FormVM` equality compares a `DOMException` by its `name` and
  `message`, which its clone keeps on Node 22 and later (ADR-0152). Before, any two `DOMException`
  values compared equal, so `setModel` dropped an edit that replaced one with
  a different one. A value that only inherits `DOMException.prototype` no
  longer makes the comparator throw (#734).
- A background VM whose `onConstruct` or `onDestruct` throws now rolls back
  to `Destructed` or `Constructed` and releases its in-flight guard on
  `RxDispatcher.immediate()` and `NullDispatcher`. Each of these uses rxjs
  `queueScheduler` for both channels, and the active flush dropped the queued
  rollback when the background action threw, so the VM stayed `Constructing`
  or `Destructing` and later lifecycle calls failed. A top-level `construct()`
  or `destruct()` now throws the hook error after the flush drains, so work
  that rollback observers queue also runs; inside an outer flush, the error
  reaches that flush's caller (#726).
- A container that waits on a busy child now checks the child's status when
  it acts on it, as in C#, Python, and Swift (spec/02 §6). Before, a container
  whose `destruct()` joined a reconstructing child reported `Destructed` while
  the child was `Constructed` again. A container whose waiting child was
  disposed after it published a settled status but before it released its
  transition guard, such as mid-reconstruct, stayed `Destructing`, and its
  next lifecycle call threw `StatusTransitionError` from `Destructing`. In both
  cases the container now rolls back to `Constructed` (#722).
- `FormVM.setModel(null)` called during approval settlement now throws to its
  caller and changes nothing, as in C# and Python (spec/20 §5.2). Before, the
  call returned and queued the `null`, whose replay then rejected the
  approval that had already persisted and been reported, and dropped later
  queued models (#721).
- `CompositeVM` and `GroupVM` with auto-construct-on-add construct a child
  added while the container is still `Constructing` (waiting on a background
  child) and wait for it before reaching `Constructed` (spec/02 §6, spec/06
  §5.1). The child walk joins such a child like a population child, so one
  that fails while the walk waits on it rolls the container back and its hook
  runs once. Before, the add skipped auto-construction until the container was
  `Constructed` and the walk used a snapshot taken before the add, so the
  container reached `Constructed` with the added child still `Destructed`.
- `CompositeVM` and `GroupVM` join the background children that factory
  population starts and never construct them again. A later child that fails
  while the container waits on an earlier one rolls the container back, and
  its construct hook runs once (spec/02 §6, LIFE-014). Before, the child walk
  restarted the failed child and ran its hook a second time.
- Aggregates, `CompositeVM`, `GroupVM`, and eager `HierarchicalVM` reach
  `Constructed` only after every child settles; aggregates, composites, and
  groups also wait for every child before `Destructed` (spec/02 §6, spec/08
  §2-§3). Before, with a `.background(true)` child, an aggregate
  reported `Constructed` while the child was still `Constructing`, and a
  composite or group threw `StatusTransitionError` from `construct()`.
- A container rolls back when a background child rolls back or is disposed.
  The composite's initial-current selector and the composite and group
  `onDestruct` callbacks run after the children settle. Children that settle
  synchronously keep the whole transition synchronous.
- A waiting container continues only after the child publishes its terminal
  status and releases its in-flight guard. A background VM therefore rejects a
  reentrant transition from an observer of its terminal status, as a
  synchronous VM does.
- When a container's deferred continuation fails, the container rolls back and
  the error comes from the dispatcher work that settled the child, as for a
  throwing background hook (VMX-049). Examples: a throwing `current` selector,
  or a synchronous sibling whose construct throws after a background child.
  Before, rxjs reported the error as an unhandled subscriber error. A container
  whose children are all synchronous still throws from `construct()`.
- `FilteredCompositeVM.setPredicate` restores the previous predicate when the
  new one throws, so later source changes keep using the working predicate.
- `CompositeVM` and `GroupVM` `insert`/`removeAt`/`setAt` reject a
  `NaN` or fractional index with a `RangeError` before any change, like `move`.
  Before, `removeAt(NaN)` removed a child, then threw and left the membership
  transaction open, so every later mutation failed (spec/06 §4, spec/07 §4).
- `FormVM`'s default deep equality compares boxed `Number`, `Boolean`,
  `String`, and `BigInt` values by value (with `+0` equal to `-0` and `NaN`
  equal to `NaN`, as for primitives), so `setModel` no longer drops a change to
  one of them (spec/20 §4).
- `AsyncResourceVM` treats a loader result that is not a promise as a failed
  load: the state becomes `Error` and `load()` completes, instead of staying
  in `Loading` and rejecting with a `TypeError` (spec/23 §7, ARES-003). A
  non-native thenable is adopted, and one whose `then` throws fails the load.
- `PagedComposition` declares the `IPageable` capability, so
  `hasCapability(paged, "IPageable")` returns true, as for the other
  capability types (spec/14 §2.10).
- `ConfirmationDecoratorCommand.canExecute` re-checks disposal after the inner
  predicate, which may dispose the wrapper, as the other wrappers do
  (spec/04 §8.4).
- `TokenPagedComposition` stops auto-constructing page items once a hook
  disposes it or starts a newer operation (spec/21 §6).
- A disposed view model's `select` and `deselect` are silent no-ops and
  `canDeselect` returns false, so a disposed child no longer changes its live
  parent's selection (spec/02 §3).
- A disposed `DerivedProperty` rejects writes: `canSet` returns false and
  `setValue` raises instead of running the write-back action (spec/15 §4).
- A disposed `NotificationVM` ignores its internal resolution paths.
- A disposed `FilteredCompositeVM` ignores `setPredicate`, `setCurrent`, and
  the visible navigation methods, so it stays frozen as the disposal contract
  states (DISP-006).
- `ObservableDictionary`: the add index is captured before `keys1`/`keys2`
  update and the local event fires, so a key-view or local subscriber that adds
  another entry no longer shifts the first entry's reported hub index. If such
  a subscriber deletes an entry or clears the dictionary, the hub message
  reports the key pair's current index, or -1 when the key pair is gone (#733).
- `CompositeVM.removeAt`, `clear`, and `setAt` emit their collection events
  even when `onCurrentChanged` throws, then rethrow. Before, the committed
  change reached no observer.
- `ServicedObservableCollection.splice` resolves a fractional or `NaN` start
  like `Array.prototype.splice` before it reports the Remove index. Before, it
  could report `2.5` or `NaN`.
- `NullDialogService.present` returns the result of a modal that was already
  dismissed, because the first result wins. Before, it returned the
  cancellation result (spec/19 §3, DIA-012).
- A disposed `CompositeVM` or `GroupVM` no longer sends a `CollectionChangedMessage`
  on the hub when a batch it was disposed inside closes, or when a local
  `collectionChanged` subscriber disposes it (ADR-0142, COMP-045, GRP-012).
- `ConfirmationDecoratorCommand` no longer calls `confirm` when the inner
  command's `canExecute` predicate disposes the decorator (spec/04 §8.4).

### Documentation

- The Vue recipe's `useVm` notifies watchers once per hub message. Before, a
  replacement or scalar change ran a synchronous `watch` or `watchEffect`
  twice. It binds the raw view-model and hub, so a view-model held in `ref()`,
  `reactive()` or `data()` works. It requires `setup()` or an effect scope,
  releases its subscription when that scope stops, and subscribes just before
  the first render, so a server render leaves no subscription (#651).

## [3.31.0] — unreleased source version

### Fixed

- `own()` on a `ForwardingComponentVM` subclass registers the resource on the
  wrapped component. The resource is released, in LIFO order with the wrapped
  component's other resources, when that component is disposed through any
  decorator or directly, and at once if it is already disposed. Before, the
  decorator kept the resource and never released it, even when it was
  registered after disposal (`FWD-005`, ADR-0151, spec 3.30.0) (#650).
- A decorator that wraps a component not derived from `ComponentVMBase` throws
  a `TypeError` from `own()`. The error message, which container membership
  also uses, now names both uses.

## [3.30.0] — 2026-10-16

First version published to npm. Earlier versions were source-only releases;
this package contains every change listed below for them.

### Changed

- An awaited `executeAsync()` on `ConfirmationDecoratorCommand` now completes
  when an asynchronous inner command (an `IAsyncCommand`, or a nested
  confirmation wrapper) finishes, not when it starts. After a true confirmation
  the decorator invokes the inner exactly once through its awaitable entry
  point, and an inner failure reaches the awaiter instead of the inner's
  `errors`. The fire-and-forget `execute()` still starts an asynchronous inner
  through the inner's own `execute()`, so its failures stay on the inner's
  `errors`; the decorator's `errors` carries only confirmation failures and
  synchronous-inner failures. The decorator adds no admission, cancellation, or
  ownership of the inner (`CMDD-014..017`, ADR-0145, spec 3.29.0) (#355).
- The `execute()` doc comment no longer claims that the void method returns a
  promise (#355).

## [3.29.0] — unreleased source version

### Changed

- `FormVM` model updates are failure-atomic. `setModel` and deny run the
  equality comparison, the validators, and (for deny) the snapshotter on the
  candidate before changing anything; if one throws, the error reaches the
  caller and the model, snapshot, errors, dirty and valid state, and command
  state are unchanged, with no notification. A failure is never turned into a
  validation error. A validator that reads the form's model sees the previous
  model; it receives the candidate as its argument. If a validator disposes the
  form or makes another edit, the interrupted update commits nothing and the
  newest edit stands, while edits from other threads still wait for an update in
  progress (`FORM-035..038`, ADR-0144, spec 3.28.0) (#337).

## [3.28.0] — unreleased source version

### Changed

- `FormVM` admits one approval at a time. While an approval is in flight,
  `approveCommand.canExecute()` is false and any other approve call through
  `approveAsync()` or `approveCommand.execute()` does nothing: it does not call
  the persister, change state, raise, or emit on `onApproved` or
  `approveErrors`. Admission marks the approval in flight and captures the model
  before raising `approveCommand.canExecuteChanged` once; settlement clears the
  mark first, then publishes `errorsChanged` if needed, one can-execute
  notification, and the outcome, so an approval started by an outcome observer
  is admitted. `setModel` and deny are not blocked. A double-executed save now
  persists once; to save again after an in-flight approval, await it and approve
  again (`FORM-031..034`, ADR-0143, spec 3.27.0) (#327).

## [3.27.0] — unreleased source version

### Changed

- `CompositeVM` and `GroupVM` publish each local collection change to their
  message hub as a `CollectionChangedMessage` sent by the container, after the
  local `collectionChanged` event. A batch publishes one `Reset` when its
  outermost scope completes after a change, an ownership transfer publishes the
  old container's `remove` before the new container's `add`, and a rejected or
  rolled-back mutation, a disposed container, or a `ForwardingCompositeVM`
  publishes nothing. Hub transactions defer the messages like any other send.
  Hub-only observers, including the React adapter's `useVmx` stores, now see
  membership changes (`COMP-042..045`, `GRP-012..013`, ADR-0142, spec 3.26.0)
  (#579).

## [3.26.0] — unreleased source version

### Fixed

- `TokenPagedComposition` refresh keeps `items` and `currentToken` describing
  one loaded prefix. A refreshed first page that matches a longer accumulator
  keeps the prior continuation, so the next `loadMoreCommand` no longer
  refetches and duplicates page two. A matching page as long as the accumulator
  adopts the refreshed token, and an empty or terminal first page shorter than
  the accumulator replaces it (`COL-065`, ADR-0136, spec 3.25.0) (#326).

## [3.25.0] — unreleased source version

### Fixed

- Disposed `CompositeCommand`, `DecoratorCommand`, and
  `ConfirmationDecoratorCommand` are now inert: `canExecute()` is false and
  `execute()` runs no inner command, predicate, pre/post action, or confirmation.
  Disposal observed during execution stops further inner work while an admitted
  pre/post pair stays balanced, and a confirmation that resolves after disposal
  runs nothing and emits nothing (`CMDD-011..013`, ADR-0134).
- `PagedComposition` materializes a direct one-shot iterator source, such as a
  generator object, once at construction, as Python does, so `items`, `count`,
  and `pageCount` stay coherent in any read order. Arrays, `ObservableList`,
  other repeatable iterables, and factories stay live; a throwing one-shot
  source fails construction without leaving subscriptions behind (#352).
- `FormVM`'s default equality treats two invalid `Date` values as equal, so a
  model holding an invalid `Date` no longer starts dirty against its
  `structuredClone` snapshot and stays clean through strict approval, deny, and
  reset. The FormVM guide lists the supported equality domain (#353).
- `FormVM`'s default equality compares `Error` values by what
  `structuredClone` keeps: the error kind named by `name`, the own `message`,
  and the own `cause`, recursively. Errors with different messages or causes
  now make the form dirty, and a model holding a custom error subclass or an
  `AggregateError` starts clean against its snapshot. Stacks, custom
  properties, and subclass identity are not compared (ADR-0135, #353).

## [3.24.1] — unreleased source version

### Fixed

- `FormVM` treats every validation field name as data. Validator and error maps
  are null-prototype records, so `__proto__`, `constructor`, `toString`,
  `hasOwnProperty`, and the empty string register, report, clear, deduplicate,
  and gate approval like any other field; `fieldError()` never returns an
  inherited member, and `errors` snapshots keep every key as an own property.
  The builder's `validator("__proto__", …)` now registers a validator instead of
  replacing the internal map's prototype (#331).
- `ObservableList.insert()`, `removeAt()`, and `replace()` reject `NaN`,
  ±`Infinity`, and fractional indices with `RangeError` before any mutation,
  lookup, or notification (#335).
- `DerivedProperty` now signals its silent first value, and every later change,
  through an internal, non-enumerable seam that `@thekaveh/vmx-react` observes,
  so a binding mounted before the first value renders it as soon as it arrives.
  The seam is not part of the public type or the specified surface;
  `valueChanged` and its DPROP-009 trace are unchanged (#415).

### Documentation

- The Vue and Solid integration recipes now republish a view model whose
  `PropertyChangedMessage` reports the current value, run save through the
  supplied command instead of selecting the view model, and leave the view
  model's lifecycle to its owner. Both guides embed files that the new
  `examples/typescript/integration-recipes` fixture type-checks and tests in CI
  against pinned Vue and Solid versions (#342).
- The Svelte store recipe re-reads the view model on every connection, so a
  change made before the first subscriber or between reconnections is not
  served stale. It shares one hub subscription across subscribers, and a
  failed setup releases its listener and surfaces the error. A new Svelte 5
  runes component returns its `$effect` cleanup and follows changed `vm` and
  `hub` inputs. Both run in the integration-recipes fixture against pinned
  `svelte` 5.57.1 (#343).

## [3.24.0] — 2026-07-25

### Added

- A tree-shakeable `@thekaveh/vmx/testing` subpath now provides recordable
  hubs, immediate/manual dispatchers, semantic property and collection
  recorders, configurable sync/async command doubles, and a real-FormVM harness
  without a Vitest/Jest dependency (#84).
- A tree-shakeable `@thekaveh/vmx/devtools` subpath now provides a
  transport-neutral hub observer and optional Redux DevTools adapter with
  explicit snapshots, privacy controls, sampling/throttling, bounded
  sanitization, deterministic disposal, and no replay promise (#96).
- `DiscriminatorVM` now exposes `modalDepth` and `clearModals()` for explicit
  modal-history ownership (`DISC-007/008`, ADR-0128).

### Changed

- A public non-modal `setActiveKey` releases every saved modal frame, including
  for a same-key notification no-op, while modal close preserves nested LIFO
  restoration (`DISC-009`, ADR-0128).

### Fixed

- `AsyncRelayCommand` now rejects re-entrant or disposal-invalidated predicate
  admission and preserves the first cancellation channel when command and
  caller cancellation race.
- Relay-command predicate disposal now invalidates both ordinary and
  parameterized execution admission.
- A taskless async command is now a true no-op and does not emit transient
  execution-state notifications.
- The locked ESLint dependency graph now uses `brace-expansion` 5.0.8, removing
  the unbounded-expansion denial-of-service advisory.

## [3.23.1] — 2026-07-23

### Changed

- CI now enforces calibrated library coverage floors of 85% statements, 78%
  branches, 85% functions, and 88% lines.
- The React Notes Showcase now verifies React 19, Vite 8, and ESLint 10. The
  library uses ESLint 10 while retaining TypeScript 5.9 until the current
  `@typescript-eslint` peer range supports TypeScript 7.

### Fixed

- Hierarchy child factories now validate their complete snapshot before
  assigning parents, rejecting duplicate, cyclic, or already-parented nodes
  atomically and preserving retryability (HIER-031, ADR-0127).
- Valid factory hydration now clears prewarmed descendant path caches, and
  same-receiver structural re-entry rejects without mutation or messages
  (HIER-031/032, ADR-0127).
- Re-entrant disposal now defers terminal cleanup until the admitted lifecycle
  hook returns, preserving the hook's causal failure (LIFE-015, ADR-0126).
- The published runtime floor is now Node 20.5.0, the first Node 20 release
  with the `Symbol.dispose` protocol used by `BatchUpdateHandle`; CI exercises
  the built artifact on that exact version.
- Lazy aggregate reconstruction now reserves every proposed child from
  validation through disposal, assignment, and parent commit, preventing two
  concurrent aggregates or a re-entrant disposal hook from retaining the same
  slot. A factory that returns any currently owned slot is rejected before
  mutation.
- Pre-owned and multiply decorated components now retain one canonical,
  transferable container identity (FWD-004, ADR-0124).
- Async-resource replacement cleanup can synchronously start a newer reload
  without the superseded completion publishing another state notification.
- Repository DOM tests now use jsdom 29 without the deprecated
  `whatwg-encoding` transitive dependency.
- Composite and group disposal now closes child admission before taking the
  cascade snapshot. Membership transactions now isolate hooks, population,
  replacement rollback, and selection; re-entrant structure changes reject,
  post-construction commits recheck destination disposal, and lifecycle
  compensation failures are surfaced with the initiating error.
- CI and published-consumer verification retain the Node 20 line while adding
  Node 24 LTS and Node 26 Current coverage.
- Packed npm artifacts now include the repository's byte-identical Apache-2.0
  `LICENSE` and `NOTICE` files.
- Token pagination now treats reentrant disposal during page comparison,
  child construction, or reset notification as terminal without committing
  losing state or publishing later notifications.

- `ServicedObservableCollection.splice` now distinguishes an omitted
  `deleteCount` from explicit `undefined`, matching native array removal and
  insertion semantics (ADR-0115).
- `PagedComposition` now rejects non-finite or fractional page sizes and indexes
  before mutation or notification while retaining zero clamping for negative
  integers (COL-016, ADR-0114).
- `FormVM` structural equality now compares binary buffers and views by concrete
  constructor and visible bytes, so `ArrayBuffer`/`DataView` edits are no longer
  suppressed as equal empty-enumerable objects (FORM-003, ADR-0113).
- Common VM options factories now retain each independently supplied service
  through the builder's combined services validation (BLD-006, ADR-0112).
- `ObservableDictionary` now preserves native `Map` equality independently on
  both key axes, so differently typed primitives and distinct object or symbol
  identities cannot collide through string coercion (COL-010, ADR-0111).

## [3.23.0] — 2026-07-14

Implements `spec-v3.22.0` with 395/395 library conformance IDs covered.

### Fixed

- Terminal disposal now attempts every child and all base teardown before
  rethrowing the first failure, so one faulty child or subclass hook cannot
  strand siblings, commands, resources, or streams (LIFE-013, ADR-0108).

## [3.22.0] — 2026-07-14

Implements `spec-v3.21.0` with 395/395 library conformance IDs covered.

### Changed

- Components now have one authoritative owning parent. Mutable composite and
  group attachment transfers ownership atomically; fixed aggregate slots reject
  transfers, duplicate identities, and ownership cycles (COMP-038..041,
  ADR-0107).

### Fixed

- Form reset publication now defers model edits requested by validation
  observers until `onApproved` has observed the pristine committed state.
- Hierarchy cache invalidation now detaches discarded children so retained
  nodes have a truthful parent and can be attached again.
- A newer token-page refresh now supersedes an older in-flight load, preventing
  stale results from being appended after the refreshed first page.
- `FormVM` now completes admitted synchronous assignment, reset, revert, and
  error-publication work before reentrant disposal tears down its RxJS signals.
- `NotificationHub` serializes reentrant pending snapshots in mutation order
  and gives late subscribers one current snapshot without queued history.

## [3.21.1] — 2026-07-14

Implements `spec-v3.20.1` with 391/391 library conformance IDs covered.

### Fixed

- `AsyncRelayCommand.executeAsync` now detaches an external `AbortSignal`
  listener after success, fault, or disposal-driven cancellation.
- `HierarchicalVM.addChild` rejects cycles and atomically transfers an attached
  child (HIER-018, ADR-0105).
- `ForwardingCompositeVM` delegates hub, parent selection, snapshots,
  membership subscriptions, and moves in addition to the existing surface.

## [3.21.0] — 2026-07-12

Continues to implement `spec-v3.20.0` with 391/391 library conformance IDs.

### Added

- `@thekaveh/vmx/conformance` provides the versioned consumer adapter schema,
  strict validation, ordered factory runner, structural state and exact message
  assertions, path-addressed diagnostics, and deterministic teardown (ADR-0102).
- `adaptCommandTruthTableFixture` proves the runner against every unchanged VMx
  command truth-table row without replacing CMD-007.

### Changed

- Isolated ESM, CommonJS, and declaration outputs keep Ajv and runner APIs out
  of the root package entry.
- Release CI validates an explicit package-content allowlist and clean ESM,
  CommonJS, NodeNext, notifications, and conformance consumers before publish;
  it supports a one-time token bootstrap followed by npm trusted publishing,
  public-registry polling, provenance verification, and GitHub release notes.

## [3.20.0] — 2026-07-12

Implements `spec-v3.20.0` and keeps TypeScript at full library parity: 391/391
conformance IDs covered.

### Added

- `AsyncResourceVM<T>` models one cancellable async value with immutable
  Idle/Loading/Ready/Error state and load, reload, and cancel commands
  (`ARES-001..011`, ADR-0100).

### Changed

- Latest-start-wins admission rejects stale completion, optional retention
  keeps the accepted value visible, and acquisition-based cleanup releases
  discarded, replaced, stale, and terminal values exactly once.

## [3.19.0] — 2026-07-12

Implements `spec-v3.19.0` and keeps TypeScript at full library parity: 380/380
conformance IDs covered.

### Added

- `SearchableStateOptions<T>.sourceChanges` refreshes the current term after
  source mutations (`SRCH-001..007`, ADR-0099).

### Changed

- Source pulses bypass without resetting term debounce, preserve upstream batch
  boundaries and value-equal emissions, isolate signal failure/completion, and
  cancel only the helper-owned subscription on disposal. The VMX-093
  snapshot-only warning is removed.

## [3.18.0] — 2026-07-12

Implements `spec-v3.18.0` and keeps TypeScript at full library parity: 373/373
conformance IDs covered.

### Added

- `ObservableMembershipSource<T>` and `AggregateChangeStream<T>` follow
  committed membership in composites, groups, and both serviced collection
  families while reporting `Initial`, `Membership`, `Item`, or `Batch`
  provenance (`AGCH-001..010`, ADR-0098).
- `forComponents` selects standard component property changes; the general
  selector can observe nested local state.

### Changed

- Duplicate occurrences of the same object identity share one selected
  subscription; distinct identities each have their own. Explicit nested
  batches coalesce aggregate output, and idempotent disposal detaches only
  aggregate-owned subscriptions without owning source items.

## [3.17.0] — 2026-07-12

Implements `spec-v3.17.0` and keeps TypeScript at full library parity: 363/363
conformance IDs covered.

### Added

- `KeyedServicedObservableCollection<TKey, TItem>` adds captured-key `get`,
  `has`, `upsert`, and `delete` operations while retaining ordered serviced
  collection and array conveniences (`COL-056..064`, ADR-0097).
- Duplicate-key validation and final-result preflight make `splice`,
  `replaceAll`, and indexed rekeying atomic.

### Changed

- Key lookup and present-key upsert use the captured-key index; item lifecycle
  remains caller-owned and external transactions still defer only hub delivery.

## [3.16.0] — 2026-07-12

Implements `spec-v3.16.0` and keeps TypeScript at full library parity: 354/354
conformance IDs covered.

### Added

- `ServicedObservableCollection<T>` adds first-match `remove`, strict
  `removeAt`, named `replace`, snapshot-based `replaceAll`, and atomic `move`
  while retaining `setAt`, splice, and array conveniences (`COL-048..055`,
  ADR-0096).
- Collection-change messages retain `index` and add precise `oldIndex` /
  `newIndex` positions, including one Move delivered locally before the
  optional hub sees the final state.

### Changed

- Empty clear, empty-to-empty replacement, and same-index move no-ops are
  notification-free; serviced mutations never acquire item lifecycle ownership.

## [3.15.0] — 2026-07-11

Implements `spec-v3.15.0` and keeps TypeScript at full library parity: 346/346
conformance IDs covered.

### Added

- `subscribeValue(...)` observes selected state from one fixed VM through its
  hub, supports `Object.is` or custom equality and optional immediate delivery,
  reports current/previous values, and returns an RxJS `Subscription` teardown
  handle. Re-entrant ordering, batching, disposal, and subscriber failure
  behavior follow the existing hub contract (`SUBV-001..004`, ADR-0095).

## [3.14.0] — 2026-07-11

Implements `spec-v3.14.0` and keeps TypeScript at full library parity: 342/342
conformance IDs covered.

### Added

- `isPropertyChanged`, `isCollectionChanged`, and
  `isConstructionStatusChanged` classify existing raw messages with exact
  optional constraints and filter-safe type narrowing. A generic property sender
  is inferred only from a checked sender; collection payloads remain `unknown`
  because source identity cannot prove the independently constructed item type.
  Explicitly present `undefined` constraints compare exactly. The predicates
  compose with `Array.filter`, RxJS `filter`, and the existing higher-level
  message helpers without changing message semantics (ADR-0094).

## [3.13.0] — 2026-07-11

Implements `spec-v3.13.0` and keeps TypeScript at full library parity: 342/342
conformance IDs covered.

### Added

- Writable, read-only, and forwarding modeled components expose
  `republishModel()`, which retains model and hint state, skips assignment,
  hinter, and callback work, and emits one ordinary `"model"` hub/local pair
  (`CVM-010`, ADR-0093).

## [3.12.0] — 2026-07-11

Implements `spec-v3.12.0` and keeps TypeScript at full library parity: 341/341
conformance IDs covered.

### Changed

- `FormVM.setModel` now uses its configured/default structural equality to
  suppress a no-op candidate, then publishes exactly one model
  `PropertyChangedMessage` after model, validation, and approve-command state
  settle (`FORM-030`, ADR-0092).
- Compatibility: unequal edits are now visible on the configured hub, while a
  distinct equality-equal candidate is retained silently instead of replacing
  the live model and rerunning validators.

## [3.11.0] — 2026-07-11

Implements `spec-v3.11.0` and keeps TypeScript at full library parity: 340/340
conformance IDs covered.

### Changed

- Modeled component and `FormVM.setModel` assignment return before equality,
  retained-state, hinting, validation, command-state, callback, or notification
  work after disposal (`DISP-014`, ADR-0091).

## [3.10.0] — 2026-07-10

Implements `spec-v3.10.0` and keeps TypeScript at full library parity: 339/339
conformance IDs covered.

### Added

- `IComponentVM.hub` exposes the injected shared hub read-only.
- `ComponentVMBase.own(...)` registers functions, disposables, or subscriptions
  for exactly-once LIFO terminal cleanup (`DISP-007..013`).

## [3.9.0] — 2026-07-10

Implements `spec-v3.9.0` and keeps TypeScript at full library parity: 332/332
conformance IDs covered.

### Added

- `ObservableList.replaceAll(...)` snapshots iterable input and emits one Reset
  plus cardinality-dependent `Count` (`COL-040..047`).

## [3.8.0] — 2026-07-10

Implements `spec-v3.8.0` and keeps TypeScript at full library parity: 324/324
conformance IDs covered.

### Added

- `attachMany(...)` with consumer key selectors, stable fixpoint resolution,
  non-replacing deduplication, park/reject orphan policy, structured rejection
  results, and root-owned disposal cleanup (`HIER-023..030`).

## [3.7.0] — 2026-07-10

Implements `spec-v3.7.0` and keeps TypeScript at full library parity: 316/316
conformance IDs covered.

### Added

- Immutable-builder `resetOnApproved(...)` for declarative post-persist reset,
  including independent snapshots, revalidation, deterministic race semantics,
  and existing approval error routing (`FORM-024..029`).

## [3.6.0] — 2026-07-10

Implements `spec-v3.6.0` and keeps TypeScript at full library parity: 310/310
conformance IDs covered.

### Added

- `raiseCanExecuteChanged()` on `RelayCommand`, `RelayCommandOf`, and
  `AsyncRelayCommand`, including exact live, repeated, trigger-additive,
  in-flight, and post-dispose behavior (`CMD-014..019`).

### Fixed

- Default `FormVM` snapshot failures now name the construction, approve, or
  deny/revert phase; safely identify the first failing top-level field when
  possible; preserve the native error as `cause`; and point to the paired
  `snapshotter`/`equals` escape hatch. Custom snapshotter errors remain
  unchanged (#102).

## [3.5.0] — 2026-07-10

Implements `spec-v3.5.0` and keeps TypeScript at full library parity: 304/304
conformance IDs covered.

### Added

- Shared `IVmCollection<VM>` and selection-specific
  `ISelectableVmCollection<VM>` capabilities.
- Atomic identity-preserving `move(fromIndex, toIndex)` and a `"move"`
  collection event (`COL-032..039`).
- The React collection adapter now accepts both groups and composites without
  casts.

## [3.4.0] — 2026-07-10

Implements `spec-v3.4.0` and keeps TypeScript at full library parity: 296/296
conformance IDs covered.

### Added

- Cross-cutting disposal conformance for lifecycle owners, commands, hubs,
  interaction owners, reactive helpers, and collection/projection helpers
  (`DISP-001..006`).
- A public disposal-surface inventory documenting completion, owned teardown,
  post-dispose behavior, and second-call behavior.

## [3.3.0] — 2026-07-10

Implements `spec-v3.3.0` and keeps TypeScript at full library parity: 290/290
conformance IDs covered.

### Added

- Protected `_notifyPropertyChanged` for emitting one hub
  `PropertyChangedMessage` followed by one local property-change notification
  (`CVM-007..009`).

### Changed

- Component, modeled-component, composite, aggregate, and flagship Notes
  Showcase setters now use the shared helper after equality checks and
  assignment.

## [3.2.0] — 2026-07-10

Implements `spec-v3.2.0` and keeps TypeScript at full library parity: 287/287
conformance IDs covered.

### Added

- `ITransactionalMessageHub` and `hub.batch(callback)` for nested, lossless
  FIFO transactions (`HUB-008..013`).
- Iterative re-entrant delivery and a development publish-cycle diagnostic
  that reports involved message types.

### Changed

- `NullMessageHub` executes transaction callbacks while continuing to publish
  nothing.

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps TypeScript at full library parity: 281/281
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommandOf` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.
- Pinned common options-factory conformance (`BLD-006`) and group-child
  non-selection semantics (`GRP-011`).

### Fixed

- `AsyncRelayCommand` is now inert after disposal, and fire-and-forget
  cancellation no longer emits on `errors` when `throwOnCancel()` is set.
- `AsyncRelayCommand` no longer suppresses non-cancellation task faults merely
  because `cancel()` was requested.
- `TokenPagedComposition` skips in-flight load/refresh mutation and notifications
  if it is disposed before the fetch completes.
- Group children no longer report enabled child selection into a group.
- Removed the ineffective `MessageHub` subscriber-error diagnostic constructor
  hook; RxJS reports subscriber throws through `config.onUnhandledError`.

## [3.0.0] — 2026-06-28

The **v3 framework overhaul** — a breaking release that hardens the
lifecycle/dispose concurrency path and reconciles the public surface across
flavors. Implements `spec-v3.0.0`. See ADRs 0047–0058 and
`docs/audit/2026-06-27-vmx-merged-critique.md`.

### Added

- Positional-options construction for the common VMs — a static `create(options)`
  factory alongside the unchanged fluent builders, taking an options object:
  `ComponentVM.create({ … })`, `ComponentVMOf.create({ … })`,
  `CompositeVM.create({ … })`, `GroupVM.create({ … })` (with exported
  `ComponentVMOptions` / `ComponentVMOfOptions<M>` / `CompositeVMOptions<VM>` /
  `GroupVMOptions<VM>` types). Delegates to the builder, so required-field
  validation (`BuilderValidationError`) and the resulting VM are identical to the
  fluent path (ADR-0055; VMX-020).
- `AsyncRelayCommand` — an additive async command that flows an `AbortSignal` into
  a long-running task and adds a `cancel()` method, closing the cancellation gap
  the synchronous `RelayCommand` had. Cancellation is non-throwing to the caller by
  default with an opt-in throwing mode; fire-and-forget task faults route to an
  `errors` observable. `RelayCommand` is unchanged (ADR-0056; CMD-012; VMX-052).
- `FormVM` surfaces approve-path persister failures on a new `approveErrors`
  observable instead of swallowing them; `isDirty` uses an injectable structural
  equality (the default is a deep-equal, not `JSON.stringify`) and the default
  snapshot is a `structuredClone` deep value-copy (ADR-0048; FORM-015).

### Changed

- **BREAKING (v3.0.0):** the untyped `senderObject` field is **renamed to the
  canonical `sender`** on every message — the base `IMessage` and
  `ConstructionStatusChangedMessage`, `CollectionChangedMessage`,
  `PropertyChangedMessage`, `TreeStructureChangedMessage`, `FormRevertedMessage`.
  This restores ADR-0006 cross-flavor parity with the `sender`/`Sender` field
  documented by C#/Python/Swift (ADR-0054, VMX-016/083). The base
  `IMessage.sender` is typed `unknown`; `ITypedMessage<TSender>` /
  `PropertyChangedMessage<TSender>` narrow it to `TSender`. Migration: replace
  `msg.senderObject` with `msg.sender` (identical instance, now typed).
- **BREAKING:** `ConfirmationDecoratorCommand.execute()` (synchronous
  fire-and-forget) now surfaces a rejecting `confirm` delegate or a throwing inner
  command on a new `errors` observable instead of swallowing them; the awaitable
  `executeAsync()` keeps its throw behavior (ADR-0049; CMDD-010).
  `ModeledCrudCommands` update/delete `canExecute` is now reactive to
  current-selection change so bound buttons refresh (ADR-0049; VMX-011).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.0 artifact remains MIT-licensed.

### Fixed

- **Lifecycle/dispose concurrency cluster (ADR-0047):** status transitions are
  atomic and dispose-safe behind a per-VM guard; background lifecycle completions
  marshal their terminal emission onto the foreground dispatcher; a post-dispose
  `isCurrent` change is a silent no-op; and a throwing `onConstruct`/`onDestruct`
  hook rolls `status` back to the prior settled state (LIFE-008, the new LIFE-014).

## [2.6.0] — 2026-06-13

Implements `spec-v2.6.0`. Adds two declarative selection hooks to the
composite builders, plus four ADRs capturing absorption-audit decisions.

### Added

- `CompositeVMBuilder<VM>.current(selector)` — declarative initial-current
  selector (ADR-0042, COMP-025).
- `CompositeVMBuilder<VM>.onCurrentChanged(callback)` — synchronous
  post-change selection callback (ADR-0042, COMP-026).
- Same hooks on the modeled `CompositeVMOfBuilder<M, VM>`.

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty<T>` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.current` + `onCurrentChanged` (behavior change).

## [2.5.0] — 2026-06-10

Implements `spec-v2.5.0` (ADR-0037).

### Changed

- **Hub `PropertyChangedMessage` names are camelCase everywhere** per the TS
  idiom (spec/04 §4, ADR-0037): `"model"`, `"modeledHint"`, `"current"`,
  `"component1".."component6"` — previously these emitted PascalCase while
  `FormVM`/`HierarchicalVM` emitted camelCase. Subscribers filtering on
  `"Model"`, `"Current"`, `"IsCurrent"`, or `"ComponentN"` must update
  their strings.
- `NullDialogService` now has a private constructor — consume the
  `INSTANCE` singleton, matching every other null variant and C#.

### Fixed

- `FormVM`'s `approveCommand` and `ConfirmationDecoratorCommand.execute()`
  no longer turn a rejecting persister/confirm delegate into a fatal
  unhandled rejection on Node ≥ 15.
- `CompositeVMBase.clear()` routes through the current-selection setter; the
  old current child no longer keeps `isCurrent === true` with no
  notification.
- `PagedComposition` subscribes `itemReplaced`; `replace()` on the current
  page refreshes `items`.
- `ObservableList.clear()` emits `propertyChanged("Count")` after `reset`
  when the count changed (spec/21 §3.3).
- `GroupVM` construct/destruct iterate a snapshot so a child lifecycle hook
  that mutates the group cannot skip siblings.
- A background construct/destruct racing `dispose()` could resurrect the
  VM and publish post-dispose status messages; `Disposed` is now terminal
  in `_setStatus` and the scheduled work (spec/02 invariant 3).
- `RxDispatcher.default()`'s doc no longer inverts the rxjs scheduler
  semantics (queueScheduler is a synchronous trampoline; asapScheduler is
  a Promise microtask).
- `FormVM` no longer advances its snapshot when `dispose()` runs during
  the persister await (rxjs silently swallowed the emissions, masking the
  state mutation), and `onApproved` now emits the value that was actually
  persisted rather than the live model (parity with C#'s captured
  payload). The deny path is likewise a no-op after `dispose()`, and
  `approveAsync()` on a disposed form no longer invokes the persister.
- `ObservableList.insert` throws `RangeError` for out-of-bounds indexes
  (matching `removeAt`/`replace`) — `splice` silently normalized/clamped
  while the `itemAdded` payload carried the raw index (spec/21 §3.2).
  `CompositeVM.insert` and `GroupVM.insert` get the same bounds check
  (catalogued in ADR-0009).
- `ServicedObservableCollection.splice(0, 0)` no longer emits a `Reset` for
  a mutation that never happened (spec/21 §2.4).
- Post-2.4.0 maintenance backfill: `AggregateVM6` walk/dispose drift and the
  missing `DictionaryEntry` export.

### Added

- `FORM-014` conformance coverage: a disposed `FormVM` is inert — approve
  never invokes the persister, deny does not revert (ADR-0038; pins the
  guards shipped earlier in this release).

- `HierarchicalVM.reparentChild` rejects self- and ancestor-reparenting
  with `Error` instead of silently corrupting the tree (HIER-018).
- `NotificationHub.dispose()` — resolves in-flight waiters with `Pending`,
  completes `pending`, refuses new enqueues, idempotent (NOTIF-017).
- Typed-arity `DerivedProperty` factories `fromOne`..`fromFive` plus the
  `fromMany` alias (ADR-0035 §2 DP2 always claimed TS had them; it never
  did — the recorded three-flavor parity decision is now true).
- Idempotent `dispose()` on `DecoratorCommand`,
  `ConfirmationDecoratorCommand`, and `CompositeCommand` (teardown
  symmetry with the C# IDisposable surface; the decorators own no
  subscriptions).

## [2.4.0] — 2026-06-02

Implements spec v2.4.0 — umbrella publication-readiness + Swift flavor
sibling + example-app theming scenario contract + test-coverage backfill
(ADR-0036). One published-name change (see Changed below); no behaviour
changes to existing TS APIs.

### Changed

- **npm package renamed from `vmx` to `@thekaveh/vmx`** (the unscoped
  `vmx` name was unavailable on the public npm registry). Install
  command becomes `npm install @thekaveh/vmx rxjs`; imports become
  `import { ... } from "@thekaveh/vmx"`. The opt-in notifications
  sub-path is now `@thekaveh/vmx/notifications`. Source-compatible: no
  symbol changes. See ADR-0036 §2.A.

### Added

- **ThemeVM scenario contract** (example apps): the v2.4.0
  `spec-v2.4.0` cycle defines a normative shape for example-app
  theming (`ThemeModel` + `ThemeVM extends ComponentVMOf<ThemeModel>`
  + per-framework `ThemeAdapter`) built from the existing core
  primitives (`ComponentVMOf<M>`, `DerivedProperty<TValue>`,
  `RelayCommand`, `MessageHub`). No new core types are introduced;
  the contract is implemented by the React Notes-Showcase flagship
  under `examples/typescript/react/notes-showcase/`. See
  `spec/proposals/2026-06-02-theme-vm-scenario.md` + ADR-0036 §2.C.

### Fixed

- **Example-app edge-case coverage backfill.** The React Notes-Showcase
  flagship gained dedicated tests for the filter / search / paging
  interaction matrix, capability-aware action-bar gating, and FormVM
  approve/deny edge cases that were previously implicit. No production
  code changed; tests only.

### Conformance

- 5 new IDs (`THEME-001..005`); running total goes from 227 to **232**.
  The TS flavor implements `THEME-001..005` as part of the React
  Notes-Showcase flagship's conformance suite (the contract is
  scenario-level, not a core library addition).

### Min spec version

- 2.4.0 (previously 2.3.0).

## [2.3.0] — 2026-05-31

Implements spec v2.3.0 — builder pattern audit follow-through (ADR-0035).
Purely additive at the surface level. The C# / Python flavors gain
validation parity with TS's existing Children-at-`build()` behaviour.

### Fixed

- **D1 — Browser-safe dist.** `src/lifecycle/transitionValidator.ts` no
  longer imports `node:fs` / `node:path` / `node:url` at module load. The
  `lifecycle-transitions.json` fixture is now consumed via a static
  TypeScript JSON import and bundled into both ESM and CJS dist artifacts
  by tsup/esbuild. Browsers using Vite, Webpack, esbuild, Rollup, Bun, and
  Tauri webviews can load `vmx` directly with no node-builtin stubs.

### Changed

- **D2 — `rxjs` moved to `peerDependencies`.** Previously declared as a
  hard dependency; consumers using pnpm strict isolation (default for new
  Vite/SvelteKit projects) hit resolution friction when vendoring VMx.
  Public install command is now `npm install vmx rxjs`. `rxjs` remains in
  `devDependencies` for local test runs. `peerDependenciesMeta.rxjs.optional`
  is `false` (required).

### Added

- **`FormVMBuilder<TM>`** (`vmx` — `forms/`) — fluent immutable builder for
  `FormVM<TM>` with `.initial(...)` and `.persister(...)` required, and
  optional `.hub(...)`, `.strict(boolean)`, `.snapshotter(...)`. Validates
  at `build()`. Conformance: `FORM-011..013`. See ADR-0035 §FV1/FV2.
- **`HierarchicalVMBuilder<TModel, TVM>`** (`vmx` — `hierarchical/`) —
  fluent immutable builder for `HierarchicalVM<TModel, TVM>` with
  `.model(...)`, `.childrenFactory(...)`, `.services(hub, dispatcher)`
  required, and optional `.name(...)`, `.hint(...)`,
  `.eagerChildren(boolean)`. Adds `.withDefaultServices()` Wither for
  opt-in implicit defaults. Validates at `build()`. Conformance:
  `HIER-015..017`. See ADR-0035 §H1/H2/H3.
- **`HierarchicalVMConstructionContext`** — new context type passed to
  children-factory callbacks for the hierarchical builder.
- **`withNullServices()`** Wither extension on `ComponentVMBuilder` and
  friends — chainable convenience that wires `NullMessageHub.INSTANCE`
  + `NullDispatcher.INSTANCE` in one call, for parity with the C#
  `WithNullServices()` extension. See ADR-0035 §SV1.
- `tests/browser-build/smoke.test.ts` — JSDOM environment smoke test that
  loads the public surface and instantiates a `ComponentVMOf` to catch
  future regressions of the browser-safety contract (companion to D1).
- README §3.5 "Browser usage" documenting bundler compatibility and the
  rxjs peer-dependency install command (companion to D2).

### Conformance

- 7 new IDs (`BLD-005`, `FORM-011..013`, `HIER-015..017`); running total
  goes from 220 to 227.

### Min spec version

- 2.3.0 (previously 2.2.0).

## [2.2.0] — 2026-05-30

### Added

- `AggregateVM6` — sixth-arity heterogeneous aggregate.
  Conformance: `AGG-006`. See ADR-0034.

### Conformance

- 1 new ID (`AGG-006`); running total: 220.

### Min spec version

- 2.2.0 (previously 2.1.0).

## [2.1.0] — 2026-05-28

Implements spec v2.1.0. Purely additive — no breaking changes from v2.0.x.

### Added

- **`HierarchicalVM<TModel, TVM>`** (`vmx` — `hierarchical/`) — first-class
  recursive tree VM with lazy/eager child loading, depth-first construction,
  materialized path, parent-change and structural-change hub messages.
  `TreeStructureChangedMessage` new type. (ADR-0028; HIER-001..014)
- **`IDialogService`** + **`NullDialogService`** (`vmx` — `dialogs/`) —
  host-side contract for modal interactions (file pick, confirm prompt,
  severity-tagged notify) distinct from `INotificationHub`. (ADR-0029;
  DIA-001..008)
- **`FormVM<TM>`** (`vmx` — `forms/`) — snapshot/revert edit lifecycle
  (ORM-agnostic). `denyCommand`, `approveCommand`, `onApproved` event,
  optional strict mode. `FormRevertedMessage` new type. (ADR-0030;
  FORM-001..010)
- **`NotificationVM`** + **`ConfirmationVM`** (`vmx/notifications`) —
  render-side VMs with auto-dismiss (60s/300s default), opacity decay,
  dismiss/approve/reject commands. (ADR-0031; NOTIF-011..016)
- **`ServicedObservableCollection<T>`** (`vmx` — `collections/`) —
  observable collection with hub publication. (ADR-0024; COL-001..004)
- **`ObservableList<T>`** (`vmx` — `collections/`) — granular per-mutation
  events (itemAdded/Removed/Replaced/Reset) with batch suppression.
  (ADR-0026; COL-005..009, COL-023)
- **`ObservableDictionary<K1, K2, V>`** (`vmx` — `collections/`) —
  composite-key observable dictionary with observable keys1/keys2 views and
  hub publication. (ADR-0025; COL-010..015, COL-022)
- **`PagedComposition<TVM>`** (`vmx` — `collections/`) — paging decorator
  over any composition implementing `IPageable`. (ADR-0023; COL-016..021)
- **`IFilterable<T>`** + **`IPageable`** (`vmx` — `capabilities/`) — two new
  capability interfaces. (ADR-0022, ADR-0023; CAP-021, CAP-022)
- **Fluent command helpers** (`vmx` — `commands/`) — `confirm(…)`,
  `precedeWith`, `succeedWith`, `wrapWith` extension helpers over commands.
  (ADR-0027; CMD-008..011)
- **`propertyValueChangedMessagesFor`** helper (`vmx` — `messages/`) —
  function that filters `PropertyChangedMessage` events for a given
  sender + property name and returns an observable stream of the
  property's value snapshots. (ADR-0032; informative)
- Re-exports of `IBatchable` (collections) and `IParentVM` (components)
  from the main `vmx` barrel for parity with the rest of the public
  surface — previously only reachable via deep sub-path imports.
- `tree/index.ts` re-exports `walkExpanded` alongside `walk` and `find`
  for sub-index completeness.
- **Conformance**: 67 new IDs (total 219).

### Fixed

- `CompositeVMBase.setAt` now clears `current` to null when the
  replaced slot held the current selection, mirroring `removeAt`.
- `AggregateVM1..5._onConstruct` now disposes the previous slot
  instance before invoking the factory on Reconstruct, so the old
  VM's hub subscriptions and command Subjects are released instead of
  lingering until the hub itself is disposed. (Parity with the C# fix.)
- `SearchableState.searchTerm` setter no longer pushes the new value
  through the debounce/recompute pipeline when it equals the current
  value (spec wording: "emission on a new value").
- `DecoratorCommand.execute` now wraps the inner `execute` call in
  try/finally so the `postExecute` callback always runs — a "busy"
  flag set in `preExecute` no longer gets stuck when the inner
  command throws.
- `AggregateVM4Builder.build()` / `AggregateVM5Builder.build()` now
  throw per-field `BuilderValidationError("componentN")` for the first
  missing slot, matching the arity-1/2/3 builders. Previously they
  collapsed into a single generic `"components"` error, so consumers
  could not programmatically distinguish which slot was missing.

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`vmx`): 20 opt-in micro-interfaces —
  `ISelectable`, `IDeselectable`, `ISelectionTogglable`, `IExpandable`,
  `ICollapsible`, `IExpansionTogglable`, `ISearchable`, `IClosable`,
  `IApprovable`, `ICancelable`, `INewCreatable`, `IDeletable`,
  `IUpdatable`, `ISavable`, `ICurrentDeletable`, `ICurrentUpdatable`,
  `IManagable`, `IConstructable`, `IDestructable`, `IReconstructable`
  (see `src/capabilities/registry.ts`).
- **Helpers** (`vmx`): `SearchableState<TItem>` (real `debounceTime`,
  trailing-edge), `ExpandableState`.
- **Derived properties** (`vmx`): `DerivedProperty<TValue>` plus a
  `fromSources(sources, transform, opts?)` factory for N-source
  computed values, value-equality guard via `Object.is`, optional
  write-back.
- **Commands**: `ConfirmationDecoratorCommand` + the abstract
  `DecoratorCommand` base, `makeConfirm` helper, `ModeledCrudCommands<M, VM>`
  (M is a phantom type parameter mirroring the spec contract — see ADR-0016).
- **Null-object services** (per ADR-0017): `NullMessageHub`,
  `NullDispatcher`, `NullLocalizer`, plus `NullNotificationHub` (in the
  notifications package).
- **Localization** (`vmx`): `ILocalizer` interface and `NullLocalizer`
  (identity translator).
- **Notifications sub-package** (`vmx` namespace `notifications/`,
  shipped in-package but tree-shakable): `Notification`, `NotificationType`,
  `NotificationReaction`, `INotificationHub` + `NotificationHub` reference
  impl + `NullNotificationHub`.
- **Tree utilities**: `walkExpanded(root)` variant that descends only into
  expanded composites.
- **Conformance**: 77 new IDs added (total 152).

### Changed (breaking)
- `ModeledCrudCommands<VM>` is now `ModeledCrudCommands<M, VM>` (phantom
  `M`). Update callsites from `new ModeledCrudCommands<MyVM>({...})` to
  `new ModeledCrudCommands<MyModel, MyVM>({...})`.
- `deriveFromSources(sources, transform, opts)` is renamed `fromSources`
  to match the ADR-0006 idiom mapping (`from_sources` in Python).
  Update imports.

## [1.2.0] — 2026-05-23

### Added
- `ConstructionStatusChangedMessage.sender` getter — alias of `senderObject`,
  matching the typed `sender` field on the C# and Python flavors.
- `scripts/check-version-sync.mjs` enforces `package.json.version` ↔
  `src/version.ts.__version__` agreement and runs as part of `prebuild` and
  `prepack` so a release that forgets to update one side fails fast.

### Fixed
- `scripts/sync-fixtures.mjs` now reports a clear error if `spec/fixtures/`
  is missing rather than failing inside `readdirSync` with an opaque ENOENT.

### Internal
- JSDoc note on `selectNextCommand` / `selectPreviousCommand` explaining the
  hard-coded `false` predicate semantics on orphan leaves (CVM-005).
- Module docstring on `version.ts` documenting the manual-sync contract that
  the new `check-version-sync.mjs` enforces.

## [1.1.0] — 2026-05-23

Initial release. Implements all 75 conformance IDs from spec v1.1.0 with full
parity against the C# and Python flavors.

### Added

- `ComponentVM`, `ComponentVMOf<M>`, `ReadonlyComponentVMOf<M>` — leaf viewmodels.
- `CompositeVM<VM>`, `CompositeVMOf<M, VM>` — ordered collection + current selection.
- `GroupVM<VM>` — ordered collection without selection.
- `AggregateVM1..5` — fixed-arity named-slot aggregates.
- `ForwardingComponentVM<M>`, `ForwardingCompositeVM<VM>` — forwarding decorators.
- `RelayCommand`, `RelayCommandOf<T>` — executable commands with reactive `canExecute`.
- `MessageHub` — rxjs `Subject`-backed pub/sub hub with per-subscriber exception swallowing.
- `RxDispatcher` — foreground/background scheduler pair; `immediate()` uses `queueScheduler` for both.
- `ConstructionStatus` — 5-state lifecycle enum (`Disposed`, `Destructing`, `Destructed`, `Constructing`, `Constructed`).
- `StatusTransitionError` — raised on illegal lifecycle transitions.
- `PropertyChangedMessage`, `ConstructionStatusChangedMessage` — immutable message types.
- `BatchUpdateHandle` — ref-counted batch with `dispose()` / TC39 `[Symbol.dispose]()`.
- `walk(root)`, `find(root, predicate)` — DFS pre-order tree utilities.
- Fluent immutable builders for every public type.
- Dual ESM + CJS output via tsup; TypeScript declarations bundled.
