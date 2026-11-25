//! Regression tests for #1925: the collection and pager reads run the item
//! `T::clone` with no owner lock held, so a `Clone` that reads its owner, or
//! waits for another thread to write it, returns instead of deadlocking.
//!
//! Each hook is armed for its first clone only, so a writer's copy of the
//! items (`cow_mut`) does not re-enter it. Every wait is bounded, so a
//! regression fails the test and does not hang the suite.

use super::bounded_wait::within_timeout;
use std::cell::Cell;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{
    KeyedServicedObservableCollection, ObservableList, PagedComposition,
    ServicedObservableCollection,
};

/// The bound on every outer wait in this file.
const BOUND: Duration = Duration::from_secs(5);
/// How long a hook waits for the writer thread it started.
const HOOK_BOUND: Duration = Duration::from_secs(2);

/// The hook that `Clone` runs. Every value of one test shares it.
type Probe = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

/// A value whose `Clone` runs the probe, which reads or waits on the owner
/// the value lives in.
struct CloneProbing {
    id: u32,
    probe: Probe,
}

impl Clone for CloneProbing {
    fn clone(&self) -> Self {
        let probe = self.probe.lock().unwrap().clone();
        if let Some(probe) = probe {
            probe();
        }
        Self {
            id: self.id,
            probe: Arc::clone(&self.probe),
        }
    }
}

/// Returns a hook that runs `action` on its first call only.
fn first_call(action: impl Fn() + Send + Sync + 'static) -> Arc<dyn Fn() + Send + Sync> {
    let armed = AtomicBool::new(true);
    Arc::new(move || {
        if armed.swap(false, Ordering::SeqCst) {
            action();
        }
    })
}

/// Returns a hook that starts `write` on a new thread and waits for it for at
/// most [`HOOK_BOUND`]. It sets `finished` when the write returns in time.
fn wait_for_write(
    write: impl Fn() + Send + Sync + 'static,
    finished: Arc<AtomicBool>,
) -> Arc<dyn Fn() + Send + Sync> {
    let write: Arc<dyn Fn() + Send + Sync> = Arc::new(write);
    first_call(move || {
        let (done, wait) = mpsc::channel();
        let write = Arc::clone(&write);
        thread::spawn(move || {
            write();
            let _ = done.send(());
        });
        if wait.recv_timeout(HOOK_BOUND).is_ok() {
            finished.store(true, Ordering::SeqCst);
        }
    })
}

fn arm(probe: &Probe, hook: Arc<dyn Fn() + Send + Sync>) {
    *probe.lock().unwrap() = Some(hook);
}

fn probing(id: u32, probe: &Probe) -> CloneProbing {
    CloneProbing {
        id,
        probe: Arc::clone(probe),
    }
}

#[test]
fn observable_list_get_clone_may_read_the_list() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let list = ObservableList::new(1);
    list.push(probing(10, &probe));
    let reader = list.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.len();
        }),
    );
    let id = within_timeout("ObservableList::get", BOUND, {
        let list = list.clone();
        move || list.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
}

#[test]
fn observable_list_get_clone_may_wait_for_a_write() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let list = ObservableList::new(1);
    list.push(probing(10, &probe));
    let finished = Arc::new(AtomicBool::new(false));
    let writer = list.clone();
    let writer_probe = Arc::clone(&probe);
    arm(
        &probe,
        wait_for_write(
            move || writer.push(probing(20, &writer_probe)),
            Arc::clone(&finished),
        ),
    );
    let id = within_timeout("ObservableList::get", BOUND, {
        let list = list.clone();
        move || list.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
    assert!(
        finished.load(Ordering::SeqCst),
        "the write waited for the get"
    );
    assert_eq!(list.len(), 2);
}

#[test]
fn serviced_get_clone_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(probing(10, &probe));
    let reader = collection.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.len();
        }),
    );
    let id = within_timeout("ServicedObservableCollection::get", BOUND, {
        let collection = collection.clone();
        move || collection.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
}

#[test]
fn serviced_get_clone_may_wait_for_a_write() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(probing(10, &probe));
    let finished = Arc::new(AtomicBool::new(false));
    let writer = collection.clone();
    let writer_probe = Arc::clone(&probe);
    arm(
        &probe,
        wait_for_write(
            move || writer.push(probing(20, &writer_probe)),
            Arc::clone(&finished),
        ),
    );
    let id = within_timeout("ServicedObservableCollection::get", BOUND, {
        let collection = collection.clone();
        move || collection.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
    assert!(
        finished.load(Ordering::SeqCst),
        "the write waited for the get"
    );
    assert_eq!(collection.len(), 2);
}

#[test]
fn serviced_to_vec_clone_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(probing(10, &probe));
    collection.push(probing(11, &probe));
    let reader = collection.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.len();
        }),
    );
    let ids = within_timeout("ServicedObservableCollection::to_vec", BOUND, {
        let collection = collection.clone();
        move || -> Vec<u32> { collection.to_vec().iter().map(|item| item.id).collect() }
    });
    assert_eq!(ids, vec![10, 11]);
}

#[test]
fn keyed_get_clone_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection: KeyedServicedObservableCollection<u32, CloneProbing> =
        KeyedServicedObservableCollection::new(1, |item: &CloneProbing| Ok(item.id));
    collection
        .push(probing(10, &probe))
        .expect("a fresh key is accepted");
    let reader = collection.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.len();
        }),
    );
    let id = within_timeout("KeyedServicedObservableCollection::get", BOUND, {
        let collection = collection.clone();
        move || collection.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
}

#[test]
fn keyed_get_clone_may_wait_for_a_write() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection: KeyedServicedObservableCollection<u32, CloneProbing> =
        KeyedServicedObservableCollection::new(1, |item: &CloneProbing| Ok(item.id));
    collection
        .push(probing(10, &probe))
        .expect("a fresh key is accepted");
    let finished = Arc::new(AtomicBool::new(false));
    let writer = collection.clone();
    let writer_probe = Arc::clone(&probe);
    arm(
        &probe,
        wait_for_write(
            move || {
                let _ = writer.push(probing(20, &writer_probe));
            },
            Arc::clone(&finished),
        ),
    );
    let id = within_timeout("KeyedServicedObservableCollection::get", BOUND, {
        let collection = collection.clone();
        move || collection.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
    assert!(
        finished.load(Ordering::SeqCst),
        "the write waited for the get"
    );
    assert_eq!(collection.len(), 2);
}

#[test]
fn keyed_to_vec_clone_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection: KeyedServicedObservableCollection<u32, CloneProbing> =
        KeyedServicedObservableCollection::new(1, |item: &CloneProbing| Ok(item.id));
    collection
        .push(probing(10, &probe))
        .expect("a fresh key is accepted");
    collection
        .push(probing(11, &probe))
        .expect("a fresh key is accepted");
    let reader = collection.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.len();
        }),
    );
    let ids = within_timeout("KeyedServicedObservableCollection::to_vec", BOUND, {
        let collection = collection.clone();
        move || -> Vec<u32> { collection.to_vec().iter().map(|item| item.id).collect() }
    });
    assert_eq!(ids, vec![10, 11]);
}

#[test]
fn paged_current_page_clone_may_read_the_pager() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pager = PagedComposition::new(vec![probing(10, &probe), probing(11, &probe)], 1);
    let reader = pager.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.page_count();
        }),
    );
    let ids = within_timeout("PagedComposition::current_page", BOUND, {
        let pager = pager.clone();
        move || -> Vec<u32> { pager.current_page().iter().map(|item| item.id).collect() }
    });
    assert_eq!(ids, vec![10]);
}

#[test]
fn paged_pass_through_current_page_clone_may_read_the_pager() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pager = PagedComposition::new(vec![probing(10, &probe), probing(11, &probe)], 0);
    let reader = pager.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.page_count();
        }),
    );
    let ids = within_timeout("PagedComposition::current_page", BOUND, {
        let pager = pager.clone();
        move || -> Vec<u32> { pager.current_page().iter().map(|item| item.id).collect() }
    });
    assert_eq!(ids, vec![10, 11]);
}

#[test]
fn paged_current_page_clone_may_wait_for_a_write() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pager = PagedComposition::new(vec![probing(10, &probe)], 1);
    let finished = Arc::new(AtomicBool::new(false));
    let writer = pager.clone();
    let writer_probe = Arc::clone(&probe);
    arm(
        &probe,
        wait_for_write(
            move || writer.push(probing(20, &writer_probe)),
            Arc::clone(&finished),
        ),
    );
    let ids = within_timeout("PagedComposition::current_page", BOUND, {
        let pager = pager.clone();
        move || -> Vec<u32> { pager.current_page().iter().map(|item| item.id).collect() }
    });
    assert_eq!(ids, vec![10]);
    assert!(
        finished.load(Ordering::SeqCst),
        "the write waited for the page read"
    );
    assert_eq!(pager.page_count(), 2);
}

/// The collection and pager handles keep their auto traits for a `Send` item
/// that is not `Sync` (#1925).
#[test]
fn pager_stays_send_and_sync_for_a_send_item() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<PagedComposition<Cell<u32>>>();
}
