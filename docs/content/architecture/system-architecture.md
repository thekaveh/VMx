# 5.2. System Architecture

The system map shows how spec, builders, lifecycle, services, messaging, and
host-application code fit together. It is the fastest way to see what VMx owns
and what stays in your app.

<img src="../../assets/diagrams/system-architecture.svg" alt="VMx System Architecture" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/system-architecture.html">Open standalone diagram</a>
  &middot;
  <a href="../../assets/diagrams/system-architecture.png">PNG</a>
</p>

The important boundary is that UI frameworks stay outside the VMx core. The
framework provides lifecycle, hierarchy, commands, services, and helpers; your
host app supplies models, view bindings, and platform-specific rendering.

## 5.2.1. Layers

Each flavor implements the same conceptual stack:

- **Spec** — `spec/` is the source of truth: markdown chapters, ADRs, JSON
  fixtures, and the conformance catalog, with the version pinned in
  `spec/VERSION`.
- **Application code** — your host app instantiates VMs through builders.
- **Forwarding decorators** *(optional)* — `ForwardingComponentVM` and
  `ForwardingCompositeVM` wrap an inner VM for instrumentation, selective
  override, or composition.
- **Viewmodel hierarchy** — `ComponentVM<M>`, `CompositeVM<VM>`,
  `GroupVM<VM>`, `AggregateVM1..6`.
- **Commands** — `RelayCommand` and `RelayCommand<T>` with `execute`,
  `canExecute`, reactive trigger observables, and imperative re-evaluation
  notifications.
- **Messages and collection events** — `PropertyChangedMessage`,
  `ConstructionStatusChangedMessage`, `CollectionChangedEvent` with
  `BatchUpdate()`, atomic `Move`, and `AutoConstructOnAdd` options.
- **Tree utilities** — `walk(root)`, `walk_expanded(root)`, and
  `find(root, predicate)` over any VM hierarchy.
- **Services** — `MessageHub` (hot-stream pub/sub) and `RxDispatcher` (paired
  foreground / background schedulers).
- **Lifecycle state machine** — orchestrates every VM; transitions are enforced
  by a fixture-backed validator (`spec/fixtures/lifecycle-transitions.json`).
- **Builders** — immutable fluent setters that return new instances and
  validate required fields on `build()`.
