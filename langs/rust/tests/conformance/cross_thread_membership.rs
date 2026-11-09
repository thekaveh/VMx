//! A membership change never waits for another thread's membership
//! transaction (spec/06 §4.2, spec/07 §1.1, ADR-0187, #1314). While a thread
//! holds a container's transaction, every admission and removal from another
//! thread fails at once with [`VmxError::OwnershipTransactionInProgress`] and
//! changes nothing. Once the transaction ends, the same calls succeed.

use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use vmx::{
    ComponentVm, CompositeVm, GroupVm, Message, MessageHub, ModeledCompositeVm, NullDispatcher,
    Subscription, VmNode, VmxError, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

type Child = ComponentVm<&'static str>;

fn child(name: &'static str, hub: &MessageHub) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

/// Joins `handle`, failing instead of hanging when it does not return in
/// time.
fn join_bounded<T>(handle: JoinHandle<T>, what: &str) -> T {
    let deadline = Instant::now() + BOUND;
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not return at once");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap()
}

/// The container surface these scenarios use, for CompositeVm and GroupVm.
trait Container: Clone + Send + Sync + 'static {
    fn create(name: &str, hub: &MessageHub) -> Self;
    fn id(&self) -> usize;
    fn add(&self, item: Child) -> VmxResult<()>;
    fn insert(&self, index: usize, item: Child) -> VmxResult<()>;
    fn replace(&self, index: usize, item: Child) -> VmxResult<Child>;
    fn remove(&self, item: &Child) -> VmxResult<()>;
    fn remove_at(&self, index: usize) -> VmxResult<Child>;
    fn clear(&self) -> VmxResult<()>;
    fn items(&self) -> Vec<Child>;
    fn construct(&self) -> VmxResult<()>;
    /// The current child's id; a group has no current child.
    fn current_id(&self) -> Option<usize>;
    /// Selects `item` where the container has a current child.
    fn select(&self, item: &Child);
}

impl Container for CompositeVm<Child> {
    fn create(name: &str, hub: &MessageHub) -> Self {
        let vm = CompositeVm::with_services(name, hub.clone(), NullDispatcher::new());
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn id(&self) -> usize {
        VmNode::id(self)
    }
    fn add(&self, item: Child) -> VmxResult<()> {
        CompositeVm::add(self, item)
    }
    fn insert(&self, index: usize, item: Child) -> VmxResult<()> {
        CompositeVm::insert(self, index, item)
    }
    fn replace(&self, index: usize, item: Child) -> VmxResult<Child> {
        CompositeVm::replace(self, index, item)
    }
    fn remove(&self, item: &Child) -> VmxResult<()> {
        CompositeVm::remove(self, item)
    }
    fn remove_at(&self, index: usize) -> VmxResult<Child> {
        CompositeVm::remove_at(self, index)
    }
    fn clear(&self) -> VmxResult<()> {
        CompositeVm::clear(self)
    }
    fn items(&self) -> Vec<Child> {
        CompositeVm::items(self)
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn current_id(&self) -> Option<usize> {
        self.current().map(|current| current.id())
    }
    fn select(&self, item: &Child) {
        self.set_current(Some(item.clone())).unwrap();
    }
}

impl Container for GroupVm<Child> {
    fn create(name: &str, hub: &MessageHub) -> Self {
        let vm = GroupVm::with_services(name, hub.clone(), NullDispatcher::new());
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn id(&self) -> usize {
        VmNode::id(self)
    }
    fn add(&self, item: Child) -> VmxResult<()> {
        GroupVm::add(self, item)
    }
    fn insert(&self, index: usize, item: Child) -> VmxResult<()> {
        GroupVm::insert(self, index, item)
    }
    fn replace(&self, index: usize, item: Child) -> VmxResult<Child> {
        GroupVm::replace(self, index, item)
    }
    fn remove(&self, item: &Child) -> VmxResult<()> {
        GroupVm::remove(self, item)
    }
    fn remove_at(&self, index: usize) -> VmxResult<Child> {
        GroupVm::remove_at(self, index)
    }
    fn clear(&self) -> VmxResult<()> {
        GroupVm::clear(self)
    }
    fn items(&self) -> Vec<Child> {
        GroupVm::items(self)
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn current_id(&self) -> Option<usize> {
        None
    }
    fn select(&self, _item: &Child) {}
}

fn ids(items: &[Child]) -> Vec<usize> {
    items.iter().map(VmNode::id).collect()
}

/// The collection changes `ids` published on `hub`, as (sender, action).
type Changes = Arc<Mutex<Vec<(usize, String)>>>;

fn record_changes(hub: &MessageHub, senders: Vec<usize>) -> (Changes, Subscription) {
    let changes: Changes = Arc::default();
    let sink = Arc::clone(&changes);
    let subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            if senders.contains(&change.sender_id) {
                sink.lock()
                    .unwrap()
                    .push((change.sender_id, format!("{:?}", change.action)));
            }
        }
    });
    (changes, subscription)
}

/// Every membership change on `p` fails at once while another thread holds
/// its transaction inside an add's construct hook, and succeeds after it.
fn membership_change_fails_at_once<C: Container>() {
    let hub = MessageHub::new();
    let p = C::create("p", &hub);
    let q = C::create("q", &hub);
    let first = child("first", &hub);
    let second = child("second", &hub);
    p.add(first.clone()).unwrap();
    p.add(second.clone()).unwrap();
    p.construct().unwrap();
    q.construct().unwrap();
    p.select(&first);
    // A population that would take `first` out of `p`.
    let modeled = {
        let first = first.clone();
        ModeledCompositeVm::new(
            "modeled",
            hub.clone(),
            NullDispatcher::new(),
            || vec![()],
            move |()| first.clone(),
        )
    };
    let (changes, _changes) = record_changes(&hub, vec![p.id(), q.id()]);

    // Thread A opens p's transaction: its add constructs `held`, whose hook
    // reports entry and blocks until the test releases it.
    let held = child("held", &hub);
    let (entered_tx, entered) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    held.on_construct(move || {
        let _ = entered_tx.send(());
        let _ = release_rx.recv_timeout(BOUND);
        Ok(())
    });
    let owner = {
        let p = p.clone();
        let held = held.clone();
        thread::spawn(move || p.add(held))
    };
    entered
        .recv_timeout(BOUND)
        .expect("the add runs its construct hook");

    let members = ids(&p.items());
    let current = p.current_id();
    let recorded = changes.lock().unwrap().len();

    // Thread B: every call returns at once with the in-progress error.
    let refused = {
        let p = p.clone();
        let q = q.clone();
        let first = first.clone();
        let hub = hub.clone();
        thread::spawn(move || {
            vec![
                ("add", p.add(child("added", &hub))),
                ("insert", p.insert(0, child("inserted", &hub))),
                (
                    "replace",
                    p.replace(0, child("replacing", &hub)).map(|_| ()),
                ),
                ("population", modeled.construct()),
                ("transfer", q.add(first.clone())),
                ("remove", p.remove(&first)),
                ("remove_at", p.remove_at(0).map(|_| ())),
                ("clear", p.clear()),
            ]
        })
    };
    let refused = join_bounded(refused, "a membership change during the transaction");
    for (call, result) in &refused {
        assert_eq!(
            *result,
            Err(VmxError::OwnershipTransactionInProgress),
            "{call} fails at once"
        );
    }
    assert_eq!(ids(&p.items()), members, "the membership of p is unchanged");
    assert!(
        q.items().is_empty(),
        "the transfer destination is unchanged"
    );
    assert_eq!(first.parent_id(), Some(p.id()));
    assert_eq!(second.parent_id(), Some(p.id()));
    assert_eq!(p.current_id(), current);
    assert_eq!(
        changes.lock().unwrap().len(),
        recorded,
        "no collection change"
    );

    release.send(()).unwrap();
    assert_eq!(join_bounded(owner, "the held add"), Ok(()));

    // The transaction has ended: the same calls succeed.
    let added = child("added", &hub);
    assert_eq!(p.add(added.clone()), Ok(()));
    assert_eq!(p.insert(0, child("inserted", &hub)), Ok(()));
    assert!(p.replace(0, child("replacing", &hub)).is_ok());
    assert_eq!(q.add(second.clone()), Ok(()), "the transfer out succeeds");
    assert_eq!(second.parent_id(), Some(q.id()));
    assert_eq!(p.remove(&added), Ok(()));
    assert!(p.remove_at(0).is_ok());
    let modeled_population = ModeledCompositeVm::new(
        "population",
        hub.clone(),
        NullDispatcher::new(),
        || vec![()],
        {
            let first = first.clone();
            move |()| first.clone()
        },
    );
    assert_eq!(
        modeled_population.construct(),
        Ok(()),
        "the population succeeds"
    );
    assert_eq!(ids(&modeled_population.items()), vec![first.id()]);
    assert!(!ids(&p.items()).contains(&first.id()));
    assert_eq!(p.clear(), Ok(()));
    assert!(p.items().is_empty());
}

/// COMP-048 — while another thread holds a composite's membership
/// transaction, add, insert, replace, population, transfer out, remove,
/// remove_at and clear fail at once and change nothing; after it ends, they
/// succeed.
#[test]
fn composite_membership_change_fails_at_once_during_another_threads_transaction() {
    membership_change_fails_at_once::<CompositeVm<Child>>();
}

/// GRP-016 — while another thread holds a group's membership transaction,
/// add, insert, replace, population, transfer out, remove, remove_at and
/// clear fail at once and change nothing; after it ends, they succeed.
#[test]
fn group_membership_change_fails_at_once_during_another_threads_transaction() {
    membership_change_fails_at_once::<GroupVm<Child>>();
}
