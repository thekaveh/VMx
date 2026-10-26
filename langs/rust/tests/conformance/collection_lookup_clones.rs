//! Regression tests for #765: dictionary lookups and `remove(&item)` compare
//! against a shared snapshot instead of copying every stored key or item, so
//! a call with no concurrent writer clones no stored key or item. A write
//! made while a snapshot is held copies instead, and every displaced key or
//! item still drops with no VMx mutex held.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::RecvTimeoutError;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    KeyedServicedObservableCollection, MessageHub, ObservableDictionary, ObservableMultiDictionary,
    ServicedObservableCollection,
};

const SIZE: u32 = 1_000;

/// A key or item that counts its `Clone` calls on a counter shared by every
/// value of one test, so tests running in parallel do not interfere.
struct Counted {
    id: u32,
    clones: Arc<AtomicUsize>,
}

impl Counted {
    fn new(id: u32, clones: &Arc<AtomicUsize>) -> Self {
        Self {
            id,
            clones: Arc::clone(clones),
        }
    }
}

impl Clone for Counted {
    fn clone(&self) -> Self {
        self.clones.fetch_add(1, Ordering::SeqCst);
        Self {
            id: self.id,
            clones: Arc::clone(&self.clones),
        }
    }
}

impl PartialEq for Counted {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl Eq for Counted {}

impl std::hash::Hash for Counted {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

fn reset(clones: &AtomicUsize) {
    clones.store(0, Ordering::SeqCst);
}

fn count(clones: &AtomicUsize) -> usize {
    clones.load(Ordering::SeqCst)
}

#[test]
fn dictionary_get_insert_and_remove_clone_no_stored_key() {
    let clones = Arc::new(AtomicUsize::new(0));
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    for id in 0..SIZE {
        dictionary.insert(Counted::new(id, &clones), id);
    }
    reset(&clones);

    // `get` and `remove` borrow the argument key; `insert` takes it by value.
    // None of them needs to clone the argument key either.
    assert_eq!(
        dictionary.get(&Counted::new(SIZE - 1, &clones)),
        Some(SIZE - 1)
    );
    assert_eq!(count(&clones), 0, "get cloned stored keys");

    dictionary.insert(Counted::new(SIZE / 2, &clones), 0);
    assert_eq!(
        count(&clones),
        0,
        "insert of a present key cloned stored keys"
    );

    assert_eq!(dictionary.remove(&Counted::new(SIZE / 2, &clones)), Some(0));
    assert_eq!(count(&clones), 0, "remove cloned stored keys");
    assert_eq!(dictionary.keys().len(), SIZE as usize - 1);
}

#[test]
fn multi_dictionary_get_insert_and_remove_clone_no_stored_key() {
    let clones = Arc::new(AtomicUsize::new(0));
    let dictionary = ObservableMultiDictionary::new(1, MessageHub::new());
    for id in 0..SIZE {
        dictionary.insert(Counted::new(id, &clones), Counted::new(id, &clones), id);
    }
    reset(&clones);

    let last = SIZE - 1;
    assert_eq!(
        dictionary.get(&Counted::new(last, &clones), &Counted::new(last, &clones)),
        Some(last)
    );
    assert_eq!(count(&clones), 0, "get cloned stored keys");

    let middle = SIZE / 2;
    dictionary.insert(
        Counted::new(middle, &clones),
        Counted::new(middle, &clones),
        0,
    );
    assert_eq!(
        count(&clones),
        0,
        "insert of a present key cloned stored keys"
    );

    assert_eq!(
        dictionary.remove(
            &Counted::new(middle, &clones),
            &Counted::new(middle, &clones)
        ),
        Some(0)
    );
    assert_eq!(count(&clones), 0, "remove cloned stored keys");
    assert_eq!(dictionary.count(), SIZE as usize - 1);
}

#[test]
fn serviced_collection_remove_clones_no_stored_item() {
    let clones = Arc::new(AtomicUsize::new(0));
    let collection = ServicedObservableCollection::new(1);
    for id in 0..SIZE {
        collection.push(Counted::new(id, &clones));
    }
    reset(&clones);

    assert!(collection.remove(&Counted::new(SIZE - 1, &clones)));
    assert!(collection.remove(&Counted::new(0, &clones)));
    assert!(!collection.remove(&Counted::new(SIZE, &clones)));
    assert_eq!(count(&clones), 0, "remove cloned stored items");
    assert_eq!(collection.len(), SIZE as usize - 2);
}

#[test]
fn keyed_collection_remove_clones_no_stored_item() {
    let clones = Arc::new(AtomicUsize::new(0));
    let collection = KeyedServicedObservableCollection::new(1, |item: &Counted| Ok(item.id));
    for id in 0..SIZE {
        collection.push(Counted::new(id, &clones)).unwrap();
    }
    reset(&clones);

    assert!(collection.remove(&Counted::new(SIZE - 1, &clones)));
    assert!(collection.remove(&Counted::new(0, &clones)));
    assert!(!collection.remove(&Counted::new(SIZE, &clones)));
    assert_eq!(count(&clones), 0, "remove cloned stored items");
    assert_eq!(collection.len(), SIZE as usize - 2);
    assert!(collection.contains_key(&1));
    assert!(!collection.contains_key(&0));
}

/// Runs `body` on a worker and fails if it does not finish in time, so a
/// drop under an internal lock fails the test instead of hanging the suite.
fn within_timeout<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    match rx.recv_timeout(Duration::from_secs(10)) {
        Ok(value) => value,
        Err(RecvTimeoutError::Timeout) => {
            panic!("{what} deadlocked: user code ran under an internal lock")
        }
        Err(RecvTimeoutError::Disconnected) => {
            let message = match worker.join() {
                Ok(()) => "worker exited without a result".to_string(),
                Err(payload) => payload
                    .downcast_ref::<&str>()
                    .map(|text| (*text).to_string())
                    .or_else(|| payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "non-string panic payload".to_string()),
            };
            panic!("{what} worker panicked: {message}")
        }
    }
}

type Hook = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

fn hook() -> Hook {
    Arc::new(Mutex::new(None))
}

thread_local! {
    static IN_HOOK: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// Runs the hook's body unless a hook is already running on this thread, so
/// keys that a hook clones and drops do not re-enter it.
fn call(hook: &Hook) {
    if IN_HOOK.with(|flag| flag.replace(true)) {
        return;
    }
    let body = hook.lock().unwrap().clone();
    if let Some(body) = body {
        body();
    }
    IN_HOOK.with(|flag| flag.set(false));
}

/// Returns a hook body that runs `action` on its first call only.
fn first_call(action: impl Fn() + Send + Sync + 'static) -> Arc<dyn Fn() + Send + Sync> {
    let armed = AtomicBool::new(true);
    Arc::new(move || {
        if armed.swap(false, Ordering::SeqCst) {
            action();
        }
    })
}

/// A key or item whose `eq` and `Drop` call hooks that read or write the
/// owner it lives in.
#[derive(Clone)]
struct Hooked {
    id: u32,
    on_eq: Hook,
    on_drop: Hook,
}

impl Hooked {
    fn new(id: u32, on_eq: &Hook, on_drop: &Hook) -> Self {
        Self {
            id,
            on_eq: Arc::clone(on_eq),
            on_drop: Arc::clone(on_drop),
        }
    }

    /// A value with no hooks, for lookups from inside a hook.
    fn plain(id: u32) -> Self {
        Self::new(id, &hook(), &hook())
    }
}

impl PartialEq for Hooked {
    fn eq(&self, other: &Self) -> bool {
        call(&self.on_eq);
        self.id == other.id
    }
}

impl Eq for Hooked {}

impl std::hash::Hash for Hooked {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

impl Drop for Hooked {
    fn drop(&mut self) {
        call(&self.on_drop);
    }
}

fn disarm(hooks: &[&Hook]) {
    for hook in hooks {
        *hook.lock().unwrap() = None;
    }
}

#[test]
fn dictionary_write_during_a_lookup_drops_the_displaced_keys_unlocked() {
    let (on_eq, on_drop) = (hook(), hook());
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert(Hooked::new(1, &on_eq, &on_drop), "one");
    dictionary.insert(Hooked::new(2, &on_eq, &on_drop), "two");
    // The lookup's first comparison removes key 1 while the lookup holds
    // the key snapshot, so the removal copies; the snapshot then holds the
    // last reference to key 1, whose `Drop` reads the dictionary.
    let writer = dictionary.clone();
    *on_eq.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove(&Hooked::plain(1));
    }));
    let reader = dictionary.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.get(&Hooked::plain(2));
    }));
    let value = within_timeout("ObservableDictionary::get", {
        let dictionary = dictionary.clone();
        move || dictionary.get(&Hooked::plain(2))
    });
    disarm(&[&on_eq, &on_drop]);
    assert_eq!(value, Some("two"));
    let ids: Vec<u32> = dictionary.keys().iter().map(|key| key.id).collect();
    assert_eq!(ids, [2]);
}

#[test]
fn multi_dictionary_write_during_a_lookup_drops_the_displaced_keys_unlocked() {
    let (on_eq, on_drop) = (hook(), hook());
    let dictionary = ObservableMultiDictionary::new(1, MessageHub::new());
    dictionary.insert(Hooked::new(1, &on_eq, &on_drop), 0_u8, "one");
    dictionary.insert(Hooked::new(2, &on_eq, &on_drop), 0_u8, "two");
    let writer = dictionary.clone();
    *on_eq.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove(&Hooked::plain(1), &0);
    }));
    let reader = dictionary.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.count();
    }));
    let value = within_timeout("ObservableMultiDictionary::get", {
        let dictionary = dictionary.clone();
        move || dictionary.get(&Hooked::plain(2), &0)
    });
    disarm(&[&on_eq, &on_drop]);
    assert_eq!(value, Some("two"));
    assert_eq!(dictionary.count(), 1);
}

#[test]
fn serviced_collection_write_during_remove_drops_the_displaced_items_unlocked() {
    let (on_eq, on_drop) = (hook(), hook());
    let collection = ServicedObservableCollection::new(1);
    collection.push(Hooked::new(1, &on_eq, &on_drop));
    collection.push(Hooked::new(2, &on_eq, &on_drop));
    let writer = collection.clone();
    *on_eq.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove_at(0);
    }));
    let reader = collection.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let removed = within_timeout("ServicedObservableCollection::remove", {
        let collection = collection.clone();
        move || collection.remove(&Hooked::plain(2))
    });
    disarm(&[&on_eq, &on_drop]);
    assert!(removed);
    assert!(collection.is_empty());
}

#[test]
fn keyed_collection_write_during_remove_drops_the_displaced_items_unlocked() {
    let (on_eq, on_drop) = (hook(), hook());
    let collection = KeyedServicedObservableCollection::new(1, |item: &Hooked| Ok(item.id));
    collection.push(Hooked::new(1, &on_eq, &on_drop)).unwrap();
    collection.push(Hooked::new(2, &on_eq, &on_drop)).unwrap();
    let writer = collection.clone();
    *on_eq.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove_at(0);
    }));
    let reader = collection.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let removed = within_timeout("KeyedServicedObservableCollection::remove", {
        let collection = collection.clone();
        move || collection.remove(&Hooked::plain(2))
    });
    disarm(&[&on_eq, &on_drop]);
    assert!(removed);
    assert!(collection.is_empty());
}

/// Lookups on other threads release their key snapshots at any time, so a
/// write may find its displaced snapshot holding the last reference to a
/// key. That key must still drop with no lock held.
#[test]
fn dictionary_keys_drop_unlocked_under_concurrent_lookups() {
    let on_drop = hook();
    let dictionary: ObservableDictionary<Hooked, u32> =
        ObservableDictionary::new(1, MessageHub::new());
    let reader = dictionary.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.get(&Hooked::plain(0));
    }));
    let stop = Arc::new(AtomicBool::new(false));
    let readers: Vec<_> = (0..3)
        .map(|_| {
            let dictionary = dictionary.clone();
            let stop = Arc::clone(&stop);
            std::thread::spawn(move || {
                while !stop.load(Ordering::SeqCst) {
                    let _ = dictionary.get(&Hooked::plain(1));
                }
            })
        })
        .collect();
    let on_eq = hook();
    within_timeout("ObservableDictionary writes under concurrent lookups", {
        let dictionary = dictionary.clone();
        let on_drop = Arc::clone(&on_drop);
        move || {
            for round in 0..2_000 {
                dictionary.insert(Hooked::new(round, &on_eq, &on_drop), round);
                let _ = dictionary.remove(&Hooked::plain(round));
            }
        }
    });
    stop.store(true, Ordering::SeqCst);
    for reader in readers {
        reader.join().unwrap();
    }
    disarm(&[&on_drop]);
    assert!(dictionary.keys().is_empty());
}

#[test]
fn dictionary_insert_of_a_present_key_drops_the_argument_key_unlocked() {
    let (on_eq, on_drop) = (hook(), hook());
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert(Hooked::new(1, &on_eq, &on_drop), "one");
    let reader = dictionary.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.get(&Hooked::plain(1));
    }));
    within_timeout("ObservableDictionary::insert", {
        let dictionary = dictionary.clone();
        let (on_eq, on_drop) = (Arc::clone(&on_eq), Arc::clone(&on_drop));
        move || dictionary.insert(Hooked::new(1, &on_eq, &on_drop), "uno")
    });
    disarm(&[&on_eq, &on_drop]);
    assert_eq!(dictionary.get(&Hooked::plain(1)), Some("uno"));
}

#[test]
fn multi_dictionary_insert_of_a_present_key_drops_the_argument_keys_unlocked() {
    let (on_eq, on_drop) = (hook(), hook());
    let dictionary = ObservableMultiDictionary::new(1, MessageHub::new());
    dictionary.insert(Hooked::new(1, &on_eq, &on_drop), 0_u8, "one");
    let reader = dictionary.clone();
    *on_drop.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.count();
    }));
    within_timeout("ObservableMultiDictionary::insert", {
        let dictionary = dictionary.clone();
        let (on_eq, on_drop) = (Arc::clone(&on_eq), Arc::clone(&on_drop));
        move || dictionary.insert(Hooked::new(1, &on_eq, &on_drop), 0, "uno")
    });
    disarm(&[&on_eq, &on_drop]);
    assert_eq!(dictionary.get(&Hooked::plain(1), &0), Some("uno"));
}

/// #765 — the shared snapshot keeps these collections `Send` and `Sync` for
/// `Sync` items and keys, such as view-models and `String` keys.
#[test]
fn collections_stay_send_and_sync_for_sync_items_and_keys() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<vmx::ServicedObservableCollection<String>>();
    assert_send_sync::<vmx::KeyedServicedObservableCollection<String, String>>();
    assert_send_sync::<vmx::ObservableDictionary<String, u32>>();
    assert_send_sync::<vmx::ObservableMultiDictionary<String, u32, u32>>();
    assert_send_sync::<vmx::ServicedObservableCollection<vmx::ComponentVm<u32>>>();
}
