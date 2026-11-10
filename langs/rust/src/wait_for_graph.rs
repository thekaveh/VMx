//! The process-wide wait-for graph for every blocking wait between VMx-owned
//! resources (spec/03 §4.1, ADR-0172).
//!
//! A thread that waits for another thread's resource records its wait before
//! it blocks, so a wait-for cycle across any mix of waits is visible: a message
//! hub `send`, `batch` or `dispose` that waits for the hub's batch owner,
//! drainer or a borrowed scope; a hub drainer with queued messages that waits
//! for a borrowed scope; a foreign `dispose()` that waits for an admitted
//! lifecycle hook; a cross-thread container disposal that waits for a
//! membership transaction; a `FormVm` call that waits for another thread's
//! publication scope on the form; an `ObservableMultiDictionary` mutation
//! that waits for another thread's delivery of the dictionary's changes; a
//! `ValueStream` send or dispose that waits for another thread to deliver its
//! value; and a `DerivedProperty` recompute that waits for another thread's
//! recompute gate. A lifecycle status publication is a hub send, so it records
//! a hub wait. The wait that would close a cycle is refused, and the caller
//! takes its refused-wait result instead of blocking (ADR-0119, ADR-0126,
//! ADR-0153, ADR-0167, ADR-0176, ADR-0208, ADR-0209).
//!
//! Every resource is named by a typed, address-derived [`Resource`] key, so
//! keys of different kinds never collide. A thread has at most one edge. An
//! edge names its resource and either the owner the waiter saw when it began
//! to wait (hub, hook, form and dictionary waits) or no owner, which is then
//! looked up when a cycle is checked (membership waits, #736). Either way an edge stops
//! counting as soon as the owner releases the resource: an owner-named edge
//! is removed by the releasing thread before it wakes the waiters
//! ([`WaitForGraph::release_waiters`]), and a looked-up owner is removed by
//! [`WaitForGraph::release`]. A woken waiter that must still wait records its
//! wait again. So only live cycles count, and a stale edge never makes a wait
//! take its refused-wait result.
//!
//! Callers may hold a hub's, a component's or a container's state lock when
//! they call in. The graph never takes another lock and runs no consumer code,
//! so its lock is always the last one taken.

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};
use std::thread::ThreadId;

use crate::runtime::lock;

/// A resource that a thread can own and another thread can wait for. Each key
/// is the address of the object that guards the resource while it lives.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) enum Resource {
    /// A container's membership transaction control.
    Membership(usize),
    /// A message hub's batch, drain and borrowed scopes.
    MessageHub(usize),
    /// A component's admitted lifecycle hook (its hook lease).
    Hook(usize),
    /// A form's publication scopes (spec/20 §5.5).
    FormPublication(usize),
    /// A multi-key dictionary's change delivery (spec/21 §4.2).
    DictionaryDelivery(usize),
    /// One accepted `ValueStream` value or terminal, which the stream's
    /// drainer delivers (#1298).
    StreamDelivery(usize),
    /// A `DerivedProperty`'s recompute gate (#1463).
    RecomputeGate(usize),
}

#[derive(Clone, Copy)]
struct Edge {
    resource: Resource,
    /// The owner the waiter named, or `None` when the owner is looked up in
    /// `owners` at check time.
    owner: Option<ThreadId>,
}

#[derive(Default)]
struct GraphState {
    owners: HashMap<Resource, ThreadId>,
    waiting_on: HashMap<ThreadId, Edge>,
}

#[derive(Default)]
pub(crate) struct WaitForGraph {
    state: Mutex<GraphState>,
}

/// Returns the graph that every VMx wait records in.
pub(crate) fn waits() -> &'static WaitForGraph {
    static GRAPH: OnceLock<WaitForGraph> = OnceLock::new();
    GRAPH.get_or_init(WaitForGraph::default)
}

impl WaitForGraph {
    /// Records that `thread` holds `resource`, for waits that look the owner
    /// up when a cycle is checked.
    pub(crate) fn acquire(&self, resource: Resource, thread: ThreadId) {
        lock(&self.state).owners.insert(resource, thread);
    }

    /// Records that `resource` has been released.
    pub(crate) fn release(&self, resource: Resource) {
        lock(&self.state).owners.remove(&resource);
    }

    /// Records that `caller` waits for `resource`, whose owner is looked up
    /// when a cycle is checked. Returns `false`, and records nothing, when
    /// that wait would close a cycle.
    pub(crate) fn try_begin_wait(&self, resource: Resource, caller: ThreadId) -> bool {
        let mut state = lock(&self.state);
        if let Some(&owner) = state.owners.get(&resource) {
            if reaches(&state, caller, owner) {
                return false;
            }
        }
        state.waiting_on.insert(
            caller,
            Edge {
                resource,
                owner: None,
            },
        );
        true
    }

    /// Records that `caller` waits for `owner`'s hold on `resource`. Returns
    /// `false`, and records nothing, when that wait would close a cycle. The
    /// owner removes the edge with [`Self::release_waiters`] before it wakes
    /// the waiter.
    pub(crate) fn try_begin_wait_for(
        &self,
        resource: Resource,
        owner: ThreadId,
        caller: ThreadId,
    ) -> bool {
        let mut state = lock(&self.state);
        if reaches(&state, caller, owner) {
            return false;
        }
        state.waiting_on.insert(
            caller,
            Edge {
                resource,
                owner: Some(owner),
            },
        );
        true
    }

    /// Removes the waits on `resource` that name an owner not in `holders`.
    /// The thread that releases its hold on `resource` calls this before it
    /// wakes the waiters, so no edge names a released owner (spec/03 §4.1
    /// rule 4).
    pub(crate) fn release_waiters(&self, resource: Resource, holders: &[ThreadId]) {
        lock(&self.state).waiting_on.retain(|_, edge| {
            edge.resource != resource || edge.owner.is_none_or(|owner| holders.contains(&owner))
        });
    }

    /// Removes the wait that `caller` recorded, if any remains.
    pub(crate) fn end_wait(&self, caller: ThreadId) {
        lock(&self.state).waiting_on.remove(&caller);
    }

    #[cfg(any(test, feature = "test-seams"))]
    fn is_waiting(&self, thread: ThreadId) -> bool {
        lock(&self.state).waiting_on.contains_key(&thread)
    }

    #[cfg(any(test, feature = "test-seams"))]
    fn is_waiting_for_membership(&self, thread: ThreadId) -> bool {
        lock(&self.state)
            .waiting_on
            .get(&thread)
            .is_some_and(|edge| matches!(edge.resource, Resource::Membership(_)))
    }

    #[cfg(test)]
    fn owner_of(&self, resource: Resource) -> Option<ThreadId> {
        lock(&self.state).owners.get(&resource).copied()
    }
}

/// Reports whether the chain of waits from `start` reaches `target`.
fn reaches(state: &GraphState, target: ThreadId, start: ThreadId) -> bool {
    let mut visited = HashSet::new();
    let mut cursor = start;
    while cursor != target {
        if !visited.insert(cursor) {
            return false;
        }
        let Some(owner) = state.waiting_on.get(&cursor).and_then(|edge| {
            edge.owner
                .or_else(|| state.owners.get(&edge.resource).copied())
        }) else {
            return false;
        };
        cursor = owner;
    }
    true
}

/// Test-only seam: reports whether `thread` waits for another thread's
/// container membership transaction. Production code never calls it.
/// Only the non-default `test-seams` feature exports it.
#[cfg(feature = "test-seams")]
#[doc(hidden)]
pub fn container_wait_registered_for_testing(thread: ThreadId) -> bool {
    waits().is_waiting_for_membership(thread)
}

/// Test-only seam: reports whether `thread` has recorded any wait in the
/// wait-for graph: a message hub, lifecycle hook, container membership, form
/// publication, dictionary delivery, stream delivery or recompute gate wait.
/// Production code never calls it. Only the non-default `test-seams`
/// feature exports it.
#[cfg(any(test, feature = "test-seams"))]
#[doc(hidden)]
pub fn wait_registered_for_testing(thread: ThreadId) -> bool {
    waits().is_waiting(thread)
}

#[cfg(test)]
mod tests {
    use super::{waits, Resource, WaitForGraph};
    use crate::runtime::{begin_membership_transaction, MembershipTransactionControl};
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;
    use std::thread::{self, ThreadId};
    use std::time::{Duration, Instant};

    fn m(key: usize) -> Resource {
        Resource::Membership(key)
    }

    fn threads(count: usize) -> Vec<ThreadId> {
        (0..count)
            .map(|_| thread::spawn(|| thread::current().id()).join().unwrap())
            .collect()
    }

    #[test]
    fn a_wait_that_closes_a_cycle_is_refused() {
        let graph = WaitForGraph::default();
        let t = threads(2);
        graph.acquire(m(1), t[0]);
        graph.acquire(m(2), t[1]);

        assert!(graph.try_begin_wait(m(2), t[0]));
        assert!(!graph.try_begin_wait(m(1), t[1]));
        assert!(!graph.is_waiting(t[1]));
    }

    #[test]
    fn a_cycle_through_a_third_thread_is_refused() {
        let graph = WaitForGraph::default();
        let t = threads(3);
        graph.acquire(m(1), t[0]);
        graph.acquire(m(2), t[1]);
        graph.acquire(m(3), t[2]);

        assert!(graph.try_begin_wait(m(2), t[0]));
        assert!(graph.try_begin_wait(m(3), t[1]));
        assert!(!graph.try_begin_wait(m(1), t[2]));
    }

    #[test]
    fn a_released_resource_no_longer_closes_a_cycle() {
        // The owner is looked up when the cycle is checked, so a stale wait
        // on a released resource does not count (#736).
        let graph = WaitForGraph::default();
        let t = threads(2);
        graph.acquire(m(1), t[0]);
        graph.acquire(m(2), t[1]);
        assert!(graph.try_begin_wait(m(2), t[0]));
        graph.release(m(2));

        assert!(graph.try_begin_wait(m(1), t[1]));
    }

    #[test]
    fn an_ended_wait_no_longer_closes_a_cycle() {
        let graph = WaitForGraph::default();
        let t = threads(2);
        graph.acquire(m(1), t[0]);
        graph.acquire(m(2), t[1]);
        assert!(graph.try_begin_wait(m(2), t[0]));
        graph.end_wait(t[0]);

        assert!(!graph.is_waiting(t[0]));
        assert!(graph.try_begin_wait(m(1), t[1]));
    }

    #[test]
    fn a_finishing_transaction_never_releases_the_next_owner() {
        // A transaction that begins as soon as another finishes keeps its owner
        // record (#1058 review). Before the fix, a finishing transaction let a
        // new one begin before it released its own record, so it released the
        // new owner's record (and `begin` asserted in debug builds).
        const TRANSACTIONS: usize = 20_000;
        const STALL_BOUND: Duration = Duration::from_secs(30);
        let active = Arc::new(AtomicBool::new(false));
        let control = Arc::new(MembershipTransactionControl::new());
        let workers: Vec<_> = (0..8)
            .map(|_| {
                let (active, control) = (active.clone(), control.clone());
                thread::spawn(move || {
                    let current = thread::current().id();
                    let mut lost = 0;
                    let mut finished = 0;
                    let mut stalled_since = None;
                    while finished < TRANSACTIONS {
                        let Ok(transaction) = begin_membership_transaction(&active, &control)
                        else {
                            // A worker that panicked inside a transaction
                            // leaves it active; fail instead of spinning.
                            let since = *stalled_since.get_or_insert_with(Instant::now);
                            assert!(since.elapsed() < STALL_BOUND, "no transaction can begin");
                            thread::yield_now();
                            continue;
                        };
                        stalled_since = None;
                        if waits().owner_of(control.resource()) != Some(current) {
                            lost += 1;
                        }
                        transaction.finish().unwrap();
                        finished += 1;
                    }
                    lost
                })
            })
            .collect();
        let lost: usize = workers
            .into_iter()
            .map(|worker| worker.join().expect("a worker panicked"))
            .sum();

        assert_eq!(lost, 0, "owner records lost");
    }

    #[test]
    fn a_wait_on_an_unowned_resource_is_recorded() {
        let graph = WaitForGraph::default();
        let t = threads(1);

        assert!(graph.try_begin_wait(m(7), t[0]));
        assert!(graph.is_waiting(t[0]));
    }

    #[test]
    fn a_hub_wait_and_a_membership_wait_close_one_cycle_in_either_order() {
        // #1158: hub, hook and membership waits share one graph, so a cycle
        // that mixes them is refused whichever wait closes it.
        for hub_first in [true, false] {
            for named in [Resource::MessageHub(10), Resource::Hook(11)] {
                let graph = WaitForGraph::default();
                let t = threads(2);
                graph.acquire(m(1), t[0]);
                if hub_first {
                    assert!(graph.try_begin_wait_for(named, t[1], t[0]));
                    assert!(!graph.try_begin_wait(m(1), t[1]));
                    assert!(!graph.is_waiting(t[1]));
                } else {
                    assert!(graph.try_begin_wait(m(1), t[1]));
                    assert!(!graph.try_begin_wait_for(named, t[1], t[0]));
                    assert!(!graph.is_waiting(t[0]));
                }
            }
        }
    }

    #[test]
    fn released_waiters_drop_only_edges_to_former_owners() {
        let graph = WaitForGraph::default();
        let t = threads(4);
        let hub = Resource::MessageHub(10);
        assert!(graph.try_begin_wait_for(hub, t[1], t[0]));
        assert!(graph.try_begin_wait_for(hub, t[2], t[3]));
        assert!(graph.try_begin_wait_for(Resource::Hook(10), t[1], t[2]));

        // t[1] released the hub, and t[2] still holds it.
        graph.release_waiters(hub, &[t[2]]);

        assert!(!graph.is_waiting(t[0]));
        assert!(graph.is_waiting(t[3]));
        // A wait on another resource with the same address is kept.
        assert!(graph.is_waiting(t[2]));
    }

    #[test]
    fn a_released_named_owner_no_longer_closes_a_cycle() {
        // #1180, #1183: the releasing owner removes the edge before the
        // waiter wakes, so a check in that window sees no cycle.
        let graph = WaitForGraph::default();
        let t = threads(2);
        let hub = Resource::MessageHub(10);
        assert!(graph.try_begin_wait_for(hub, t[1], t[0]));
        graph.release_waiters(hub, &[]);

        assert!(graph.try_begin_wait_for(Resource::Hook(11), t[0], t[1]));
    }

    #[test]
    fn a_membership_wait_is_not_reported_for_a_hub_wait() {
        let graph = WaitForGraph::default();
        let t = threads(2);
        assert!(graph.try_begin_wait_for(Resource::MessageHub(10), t[1], t[0]));

        assert!(graph.is_waiting(t[0]));
        assert!(!graph.is_waiting_for_membership(t[0]));
    }
}
