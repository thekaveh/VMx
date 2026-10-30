//! The process-wide wait-for graph for container membership waits.
//!
//! A thread that waits for another thread's container membership transaction
//! records its wait before it blocks, so a wait-for cycle is visible. The wait
//! that would close a cycle is refused, and the caller records deferred intent
//! instead of waiting (ADR-0153, ADR-0167). Rust message-hub waits are not
//! recorded here.
//!
//! A wait names its resource, a container's transaction control. The owner of
//! the resource is looked up when a cycle is checked, so an edge stops counting
//! as soon as the resource is released, even before the waiter wakes (#736).
//! Callers may hold a container's transaction state lock when they call in.
//! The graph never takes another lock, so its lock is always the last one
//! taken.

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};
use std::thread::ThreadId;

use crate::runtime::lock;

#[derive(Default)]
struct GraphState {
    owners: HashMap<usize, ThreadId>,
    waiting_on: HashMap<ThreadId, usize>,
}

#[derive(Default)]
pub(crate) struct WaitForGraph {
    state: Mutex<GraphState>,
}

/// Returns the graph that every container membership wait records in.
pub(crate) fn waits() -> &'static WaitForGraph {
    static GRAPH: OnceLock<WaitForGraph> = OnceLock::new();
    GRAPH.get_or_init(WaitForGraph::default)
}

impl WaitForGraph {
    /// Records that `thread` holds `resource`.
    pub(crate) fn acquire(&self, resource: usize, thread: ThreadId) {
        lock(&self.state).owners.insert(resource, thread);
    }

    /// Records that `resource` has been released.
    pub(crate) fn release(&self, resource: usize) {
        lock(&self.state).owners.remove(&resource);
    }

    /// Records that `caller` waits for `resource`. Returns `false`, and
    /// records nothing, when that wait would close a cycle.
    pub(crate) fn try_begin_wait(&self, resource: usize, caller: ThreadId) -> bool {
        let mut state = lock(&self.state);
        if let Some(&owner) = state.owners.get(&resource) {
            if reaches(&state, caller, owner) {
                return false;
            }
        }
        state.waiting_on.insert(caller, resource);
        true
    }

    /// Removes the wait that `caller` recorded.
    pub(crate) fn end_wait(&self, caller: ThreadId) {
        lock(&self.state).waiting_on.remove(&caller);
    }

    fn is_waiting(&self, thread: ThreadId) -> bool {
        lock(&self.state).waiting_on.contains_key(&thread)
    }

    #[cfg(test)]
    fn owner_of(&self, resource: usize) -> Option<ThreadId> {
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
        let Some(owner) = state
            .waiting_on
            .get(&cursor)
            .and_then(|resource| state.owners.get(resource))
        else {
            return false;
        };
        cursor = *owner;
    }
    true
}

/// Test-only seam: reports whether `thread` waits for another thread's
/// container membership transaction. Production code never calls it.
#[doc(hidden)]
pub fn container_wait_registered_for_testing(thread: ThreadId) -> bool {
    waits().is_waiting(thread)
}

#[cfg(test)]
mod tests {
    use super::{waits, WaitForGraph};
    use crate::runtime::{begin_membership_transaction, MembershipTransactionControl};
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;
    use std::thread::{self, ThreadId};
    use std::time::{Duration, Instant};

    fn threads(count: usize) -> Vec<ThreadId> {
        (0..count)
            .map(|_| thread::spawn(|| thread::current().id()).join().unwrap())
            .collect()
    }

    #[test]
    fn a_wait_that_closes_a_cycle_is_refused() {
        let graph = WaitForGraph::default();
        let t = threads(2);
        graph.acquire(1, t[0]);
        graph.acquire(2, t[1]);

        assert!(graph.try_begin_wait(2, t[0]));
        assert!(!graph.try_begin_wait(1, t[1]));
        assert!(!graph.is_waiting(t[1]));
    }

    #[test]
    fn a_cycle_through_a_third_thread_is_refused() {
        let graph = WaitForGraph::default();
        let t = threads(3);
        graph.acquire(1, t[0]);
        graph.acquire(2, t[1]);
        graph.acquire(3, t[2]);

        assert!(graph.try_begin_wait(2, t[0]));
        assert!(graph.try_begin_wait(3, t[1]));
        assert!(!graph.try_begin_wait(1, t[2]));
    }

    #[test]
    fn a_released_resource_no_longer_closes_a_cycle() {
        // The owner is looked up when the cycle is checked, so a stale wait
        // on a released resource does not count (#736).
        let graph = WaitForGraph::default();
        let t = threads(2);
        graph.acquire(1, t[0]);
        graph.acquire(2, t[1]);
        assert!(graph.try_begin_wait(2, t[0]));
        graph.release(2);

        assert!(graph.try_begin_wait(1, t[1]));
    }

    #[test]
    fn an_ended_wait_no_longer_closes_a_cycle() {
        let graph = WaitForGraph::default();
        let t = threads(2);
        graph.acquire(1, t[0]);
        graph.acquire(2, t[1]);
        assert!(graph.try_begin_wait(2, t[0]));
        graph.end_wait(t[0]);

        assert!(!graph.is_waiting(t[0]));
        assert!(graph.try_begin_wait(1, t[1]));
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
                            std::hint::spin_loop();
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

        assert!(graph.try_begin_wait(7, t[0]));
        assert!(graph.is_waiting(t[0]));
    }
}
