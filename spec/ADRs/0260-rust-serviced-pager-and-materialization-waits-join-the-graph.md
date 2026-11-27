# ADR 0260 — Rust serviced, token pager and materialization waits join the wait-for graph

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec version:** 3.30.0 (chapter 03 §4.1; chapter 21 §2.5, §2.13)
- **Extends:** [ADR-0172](0172-one-wait-for-graph-per-flavor.md). Related:
  [ADR-0119](0119-cycle-aware-cross-hub-coordination.md),
  [ADR-0208](0208-rust-collection-local-events-and-paging-notifications.md),
  [ADR-0209](0209-rust-stream-and-recompute-waits-join-the-wait-for-graph.md),
  #1923.

## 1. Context

ADR-0172 requires every blocking wait between VMx-owned resources in a threaded
flavor to record an edge in one wait-for graph, and to take a refused-wait
result when the edge would close a cycle. Three Rust waits still blocked on a
plain condition variable, or on a thread join, with no edge.

- **Serviced delivery.** `ServicedCollectionAdmission::acquire` waited for the
  thread that drains a serviced collection's changes. `ServicedObservableCollection`
  and `KeyedServicedObservableCollection` both use it. Thread A drains the
  collection's changes to hub H. Thread B drains H, and its subscriber mutates
  the collection. A waits for B's batch on H, with an edge. B waits for A's
  drain with no edge. Neither returned.
- **Token pager.** `TokenPagerLifecycle::begin_commit` waited for the commit
  owner, and `request_dispose` waited for the commit owner or for the disposal.
  `load_next` and `refresh` reached the same commit through
  `AsyncRelayCommand::execute_and_join`, which joins a worker thread with a
  plain `JoinHandle::join`. Thread A holds the commit and publishes on H. B
  drains H, and its subscriber calls `load_next`, `load_more` or `dispose`. The
  wait chain A, B, worker, A was open at the join.
- **Children materialization.** `HierarchicalVm::materialize_children` waited for
  the factory thread. A subscriber on a hub that the factory's thread sends to
  called `try_children`, and the cycle was open for the same reason.

ADR-0208 and ADR-0209 gave the same treatment to the dictionary delivery,
stream and recompute waits. Chapter 03 §4.1 had no row for these three.

## 2. Decision

Each wait below joins the graph. Its resource is the object that guards it, as
`Resource` keys in `langs/rust/src/wait_for_graph.rs` require. Its owner is the
thread that holds that resource. A refused wait returns the result that the row
names. A wait that closes no cycle still blocks.

1. **Serviced delivery wait.** A mutation whose admission waits for another
   thread's drain records an edge. The resource is the collection's delivery,
   and the owner is the draining thread. Every mutation commits under the
   collection's state lock and queues its change in that same critical section,
   with the revision bump. The queue order is therefore the commit order. The
   drain ends through one release that removes the waiting edges before it wakes
   the waiters (chapter 03 §4.1 rule 4). The shared drain functions serve both
   serviced types.
   - **Refused result.** The mutation commits and queues its change, and it
     returns without delivering. The draining thread delivers the change, in
     commit order, to the local stream and then the hub. If the draining thread
     has already released the drain with the change still queued, the refused
     mutation takes the drain and delivers the queue before it returns.
1. **Pager commit wait.** `begin_commit` records an edge for the commit owner.
   - **Refused result.** `begin_commit` returns `None`. The caller discards the
     page or refreshed items that it loaded, and nothing is stored or published.
     The outermost commit's end releases the waiting edges.
1. **Pager dispose waits.** `request_dispose` records an edge in both of its
   waits: the first request's wait for the commit owner, and a later request's
   wait for the disposal, whose owner is the commit owner. The invariant is that
   `dispose_requested` and not `disposed` imply an active commit owner, because
   `finish_commit` sets `disposed` in the same critical section that clears the
   owner.
   - **Refused result of the first request.** The request stands as it stands on
     the same-thread path: `dispose_requested` and `cancel_active` are set, and
     the call returns. The commit stops publishing, and its finish sets
     `disposed`.
   - **Refused result of a later request.** The call returns. Disposal completes
     when the owner's commit ends.
1. **Pager command join.** `load_next` and `refresh` from a thread that is not
   the commit owner join their worker through `execute_and_join`. The joiner
   records an edge that names the worker, with the command's execution as the
   resource. The joiner removes that edge when the join returns. A worker has
   no wait left when it ends, so an edge that names a finished worker never
   closes a cycle.
   - **Refused result.** The call returns `Ok(Ok(()))` without joining, and the
     worker runs on. Its commit then waits under rule 2, so the page can be
     committed after the call returns, or discarded.
   - The option that makes a drainer's call not join was rejected. It would stop
     blocking a wait that closes no cycle.
1. **Children materialization wait.** `materialize_children` records an edge for
   the factory thread, which owns the node's materialization. The owner releases
   the edges at the commit and at `finish_children_materialization`, when the
   epoch matches.
   - **Refused result.** The call returns
     `InvalidArgument("structural operation overlaps active children materialization")`,
     the error that `reject_structural_reentry` returns for an overlap. `try_children`
     returns it, and `children` panics with it. The `children` rustdoc now lists that panic.
1. **Resources.** `Resource` gains four variants: `ServicedDelivery`,
   `PagerLifecycle`, `CommandExecution` and `ChildrenMaterialization`. Chapter 03
   §4.1 gains one row for each wait, and rules 2 and 4 name the new instances
   and releases. Chapter 21 §2.5 notes the Rust exception. Chapter 21 §2.13 states
   the serviced rule, as §4.2 does for the dictionary.
1. **Scope.** The waits are Rust-only, as in ADR-0209, so no conformance ID is
   added. The public surface is unchanged. `spec/VERSION` stays 3.30.0, and
   `langs/rust` stays at 0.37.0, which is unreleased. The CHANGELOG records the
   fix under that version.

### 2.1. Choices made under the owner's delegation

- Decided under the owner's 2026-11-07 delegation: the pager join records an
  edge (rule 4) rather than skipping the join. The issue named both options.
  Only the edge keeps the join blocking when it closes no cycle.
- Decided under the owner's 2026-11-07 delegation: a refused serviced mutation
  queues its change and returns, which is the dictionary's rule (ADR-0208). A
  refused pager commit is discarded, because the pager has no queue for loaded
  pages, and a second queue would also need its own ordering with the cursor.

## 3. Consequences

- The three cycles from §1 complete. Each of the three waits still blocks when
  no cycle closes, and the tests cover both cases.
- A refused result is asynchronous. A serviced change can be published on the
  draining thread after its mutation returns. A refused pager commit publishes
  nothing, so its loaded page is lost. A `load_next` or `refresh` can return
  before its page is stored. A `children()` call made from a drainer's
  subscriber can panic, where it would otherwise have hung.
- If a drainer's subscriber panics, the drain clears its queue (#1065). A change
  that a refused mutation queued is then discarded too. The change stays in the
  collection's state without a notification, as a nested change does after such
  a panic. This is a known limit, and it is no worse than before.
- The serviced mutators now queue their changes under the state lock. Their
  delivery code is shared by the two serviced types. Pull request #1954 removes
  duplicate code in the same files and may need a rebase.

## 4. Rejected alternatives

- **Deliver a refused serviced change synchronously, skipping the queue.** That
  breaks commit order, so the indices that subscribers see would no longer
  describe the collection's state.
- **Queue a refused pager commit.** The pager has no queue for loaded pages, and
  a queued page would need its own ordering with the cursor and the operation
  generation.
- **Fire-and-forget `load_next` and `refresh` for every drainer.** That stops
  blocking a wait that closes no cycle, which chapter 03 §4.1 forbids.
- **Record only the worker's own wait, without an edge for the join.** Thread B's
  join is invisible, so the cycle A, B, worker, A stays open (rule 4).
