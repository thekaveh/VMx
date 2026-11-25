//! Regression tests for #1925: the collection and pager reads run the item
//! `T::clone` with no owner lock held, so a `Clone` that reads its owner, or
//! waits for another thread to write it, returns instead of deadlocking.
//!
//! Most hooks are armed for their first clone only. The write tests (#1925
//! B1) hold the first clone and then call the owner's `len()` on every later
//! clone, which a writer that held the owner's lock while it copied the items
//! would deadlock on. Every wait is bounded, so a regression fails the test and
//! does not hang the suite.

use super::bounded_wait::within_timeout;
use std::cell::Cell;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use vmx::{
    KeyedServicedObservableCollection, ObservableList, PagedComposition,
    ServicedObservableCollection,
};

/// The bound on every outer wait in this file.
const BOUND: Duration = Duration::from_secs(5);
/// How long a hook waits for the writer thread it started.
const HOOK_BOUND: Duration = Duration::from_secs(2);
/// The bound on the writes that run while a read's clone holds a snapshot.
const WRITE_BOUND: Duration = Duration::from_secs(1);
/// How long a pager removal may take while a read's clone holds the item.
const REMOVE_BOUND: Duration = Duration::from_millis(200);
/// How long a read's clone holds its item in the pager test.
const HOLD: Duration = Duration::from_millis(1000);

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

impl PartialEq for CloneProbing {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
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

/// Returns a hook for a read's clone. Its first call sets `entered` and holds
/// until `writes_done` is set or `HOOK_BOUND` passes. Its later calls read
/// the owner's length, which a writer's copy of the items would deadlock on
/// if the writer held the owner's lock.
fn hold_until_written(
    entered: Arc<AtomicBool>,
    writes_done: Arc<AtomicBool>,
    owner_len: impl Fn() -> usize + Send + Sync + 'static,
) -> Arc<dyn Fn() + Send + Sync> {
    let holding = AtomicBool::new(true);
    Arc::new(move || {
        if holding.swap(false, Ordering::SeqCst) {
            entered.store(true, Ordering::SeqCst);
            let started = Instant::now();
            while !writes_done.load(Ordering::SeqCst) && started.elapsed() < HOOK_BOUND {
                thread::sleep(Duration::from_millis(1));
            }
        } else {
            let _ = owner_len();
        }
    })
}

/// Returns a hook whose first call sets `entered` and sleeps for `hold`.
fn hold_for(entered: Arc<AtomicBool>, hold: Duration) -> Arc<dyn Fn() + Send + Sync> {
    let holding = AtomicBool::new(true);
    Arc::new(move || {
        if holding.swap(false, Ordering::SeqCst) {
            entered.store(true, Ordering::SeqCst);
            thread::sleep(hold);
        }
    })
}

/// Waits, for at most [`BOUND`], until `flag` is set.
fn wait_until(flag: &AtomicBool) {
    let started = Instant::now();
    while !flag.load(Ordering::SeqCst) {
        assert!(started.elapsed() < BOUND, "the read's clone never started");
        thread::sleep(Duration::from_millis(1));
    }
}

/// Runs `read` on a thread whose item clone holds (see
/// [`hold_until_written`]), then runs `write` on another thread once the hold
/// has started. The writes must finish within [`WRITE_BOUND`], while the hold
/// still lasts. Returns the read's result.
fn read_and_write<R: Send + 'static>(
    label: &str,
    entered: Arc<AtomicBool>,
    writes_done: Arc<AtomicBool>,
    read: impl FnOnce() -> R + Send + 'static,
    write: impl FnOnce() + Send + 'static,
) -> R {
    let reader = thread::spawn(read);
    wait_until(&entered);
    let (done, finished) = mpsc::channel();
    thread::spawn(move || {
        write();
        let _ = done.send(());
    });
    let wrote = finished.recv_timeout(WRITE_BOUND).is_ok();
    // Release the hold, so the read finishes even when the writes did not.
    writes_done.store(true, Ordering::SeqCst);
    assert!(
        wrote,
        "{label}: the writes did not finish while a read's clone held a snapshot"
    );
    reader.join().expect("the read panicked")
}

#[test]
fn observable_list_writes_finish_while_a_clone_holds_a_snapshot() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let list = ObservableList::new(1);
    list.push(probing(10, &probe));
    list.push(probing(11, &probe));
    let entered = Arc::new(AtomicBool::new(false));
    let writes_done = Arc::new(AtomicBool::new(false));
    arm(
        &probe,
        hold_until_written(Arc::clone(&entered), Arc::clone(&writes_done), {
            let list = list.clone();
            move || list.len()
        }),
    );
    let reader = list.clone();
    let writer = list.clone();
    let write_probe = Arc::clone(&probe);
    let id = read_and_write(
        "ObservableList",
        entered,
        writes_done,
        move || reader.get(0).map(|item| item.id),
        move || {
            writer.push(probing(20, &write_probe));
            assert!(writer.remove(&probing(11, &write_probe)));
            writer
                .replace(0, probing(12, &write_probe))
                .expect("index 0 is present");
            writer.clear();
        },
    );
    assert_eq!(id, Some(10));
    assert_eq!(list.len(), 0);
}

#[test]
fn serviced_writes_finish_while_a_clone_holds_a_snapshot() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(probing(10, &probe));
    collection.push(probing(11, &probe));
    let entered = Arc::new(AtomicBool::new(false));
    let writes_done = Arc::new(AtomicBool::new(false));
    arm(
        &probe,
        hold_until_written(Arc::clone(&entered), Arc::clone(&writes_done), {
            let collection = collection.clone();
            move || collection.len()
        }),
    );
    let reader = collection.clone();
    let writer = collection.clone();
    let write_probe = Arc::clone(&probe);
    let id = read_and_write(
        "ServicedObservableCollection",
        entered,
        writes_done,
        move || reader.get(0).map(|item| item.id),
        move || {
            writer.push(probing(20, &write_probe));
            assert!(writer.remove(&probing(11, &write_probe)));
            writer
                .replace(0, probing(12, &write_probe))
                .expect("index 0 is present");
            writer.clear();
        },
    );
    assert_eq!(id, Some(10));
    assert_eq!(collection.len(), 0);
}

#[test]
fn keyed_writes_finish_while_a_clone_holds_a_snapshot() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection: KeyedServicedObservableCollection<u32, CloneProbing> =
        KeyedServicedObservableCollection::new(1, |item: &CloneProbing| Ok(item.id));
    collection
        .push(probing(10, &probe))
        .expect("a fresh key is accepted");
    collection
        .push(probing(11, &probe))
        .expect("a fresh key is accepted");
    let entered = Arc::new(AtomicBool::new(false));
    let writes_done = Arc::new(AtomicBool::new(false));
    arm(
        &probe,
        hold_until_written(Arc::clone(&entered), Arc::clone(&writes_done), {
            let collection = collection.clone();
            move || collection.len()
        }),
    );
    let reader = collection.clone();
    let writer = collection.clone();
    let write_probe = Arc::clone(&probe);
    let id = read_and_write(
        "KeyedServicedObservableCollection",
        entered,
        writes_done,
        move || reader.get(0).map(|item| item.id),
        move || {
            writer
                .push(probing(20, &write_probe))
                .expect("a fresh key is accepted");
            assert!(writer.remove(&probing(11, &write_probe)));
            writer
                .replace(0, probing(12, &write_probe))
                .expect("a fresh key is accepted");
            writer.clear();
        },
    );
    assert_eq!(id, Some(10));
    assert_eq!(collection.len(), 0);
}

/// `ObservableList::get` with a clone that reads the same item again through the
/// list returns: the collections keep no per-item lock (#1925).
#[test]
fn observable_list_clone_may_read_the_same_item() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let list = ObservableList::new(1);
    list.push(probing(10, &probe));
    let reader = list.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = reader.get(0);
        }),
    );
    let id = within_timeout("ObservableList::get", BOUND, {
        let list = list.clone();
        move || list.get(0).map(|item| item.id)
    });
    assert_eq!(id, Some(10));
}

/// Open item of #1925 (B2). A read's clone holds the item for `HOLD`, and
/// `remove_at` waits for that clone, because the pager keeps one lock per
/// item. That lock keeps the pager `Sync` for a `Send` item, which the
/// `Arc`-per-item shape would drop. The test fails on this branch. Run with
/// `--ignored` to see it.
#[test]
#[ignore = "open item of #1925 (B2): remove_at waits for a clone of the same item"]
fn paged_remove_at_does_not_wait_for_a_clone_of_the_item() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pager = PagedComposition::new(vec![probing(10, &probe), probing(11, &probe)], 1);
    let entered = Arc::new(AtomicBool::new(false));
    arm(&probe, hold_for(Arc::clone(&entered), HOLD));
    let reader = pager.clone();
    let read = thread::spawn(move || {
        reader
            .current_page()
            .iter()
            .map(|item| item.id)
            .collect::<Vec<u32>>()
    });
    wait_until(&entered);
    let remover = pager.clone();
    let (removed, elapsed) = within_timeout("PagedComposition::remove_at", BOUND, move || {
        let started = Instant::now();
        let removed = remover.remove_at(0).map(|item| item.id);
        (removed, started.elapsed())
    });
    assert_eq!(removed, Some(10));
    assert!(
        elapsed < REMOVE_BOUND,
        "remove_at waited {elapsed:?} for a clone of the item it removed"
    );
    assert_eq!(read.join().expect("the read panicked"), vec![10]);
    assert_eq!(pager.page_count(), 1);
}

/// Residual of #1925 (B3): a clone that removes its own item from its own
/// pager, on the same thread, waits for that item's lock, which the clone
/// holds. The call never returns, so this test fails on this branch. Run with
/// `--ignored` to see it.
#[test]
#[ignore = "known residual of #1925: a clone cannot remove its own item from its own pager"]
fn paged_clone_that_removes_its_own_item_returns() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pager = PagedComposition::new(vec![probing(10, &probe), probing(11, &probe)], 1);
    let remover = pager.clone();
    arm(
        &probe,
        first_call(move || {
            let _ = remover.remove_at(0);
        }),
    );
    let ids = within_timeout("PagedComposition::current_page", BOUND, {
        let pager = pager.clone();
        move || -> Vec<u32> { pager.current_page().iter().map(|item| item.id).collect() }
    });
    assert_eq!(ids, vec![10]);
}

/// The collection and pager handles keep their auto traits for a `Send` item
/// that is not `Sync` (#1925).
#[test]
fn pager_stays_send_and_sync_for_a_send_item() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<PagedComposition<Cell<u32>>>();
}
