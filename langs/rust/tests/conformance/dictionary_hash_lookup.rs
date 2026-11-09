//! Regression tests for #1296: the dictionaries find a key through a hash
//! index, so a build of n distinct keys makes O(n) key comparisons, not
//! n(n−1)/2. User `hash` and `eq` still run with no VMx mutex held.

use super::bounded_wait::within_timeout;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use vmx::{MessageHub, ObservableDictionary, ObservableMultiDictionary};

const SIZE: u32 = 1_000;

/// The bound on every wait in this file.
const BOUND: Duration = Duration::from_secs(5);

/// A key that counts its `eq` calls on a counter shared by every key of one
/// test, so tests running in parallel do not interfere.
#[derive(Clone)]
struct Counting {
    id: u32,
    comparisons: Arc<AtomicUsize>,
}

impl Counting {
    fn new(id: u32, comparisons: &Arc<AtomicUsize>) -> Self {
        Self {
            id,
            comparisons: Arc::clone(comparisons),
        }
    }
}

impl PartialEq for Counting {
    fn eq(&self, other: &Self) -> bool {
        self.comparisons.fetch_add(1, Ordering::SeqCst);
        self.id == other.id
    }
}

impl Eq for Counting {}

impl std::hash::Hash for Counting {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

fn take(comparisons: &AtomicUsize) -> usize {
    comparisons.swap(0, Ordering::SeqCst)
}

/// #1296 — a build, a lookup, an update and a removal make few comparisons
#[test]
fn dictionary_operations_make_constant_comparisons() {
    let comparisons = Arc::new(AtomicUsize::new(0));
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    for id in 0..SIZE {
        dictionary.insert(Counting::new(id, &comparisons), id);
    }
    let build = take(&comparisons);
    assert!(build <= 2 * SIZE as usize, "build made {build} comparisons");

    let middle = Counting::new(SIZE / 2, &comparisons);
    assert_eq!(dictionary.get(&middle), Some(SIZE / 2));
    let get = take(&comparisons);
    assert!(get <= 2, "get made {get} comparisons");

    dictionary.insert(middle.clone(), 0);
    let update = take(&comparisons);
    assert!(
        update <= 2,
        "insert of a present key made {update} comparisons"
    );

    assert_eq!(dictionary.remove(&middle), Some(0));
    let remove = take(&comparisons);
    assert!(remove <= 2, "remove made {remove} comparisons");

    assert_eq!(dictionary.keys().len(), SIZE as usize - 1);
    assert_eq!(dictionary.get(&middle), None);
    let later = Counting::new(SIZE - 1, &comparisons);
    assert_eq!(dictionary.get(&later), Some(SIZE - 1), "positions shifted");
}

/// #1296 — a multi-key build with `insert` or `add` makes O(n) comparisons
#[test]
fn multi_dictionary_builds_make_linear_comparisons() {
    type Build = fn(&ObservableMultiDictionary<Counting, Counting, u32>, Counting, Counting, u32);
    let builds: [(&str, Build); 2] = [
        ("insert", |d, key1, key2, value| d.insert(key1, key2, value)),
        ("add", |d, key1, key2, value| {
            d.add(key1, key2, value).unwrap()
        }),
    ];
    for (name, build) in builds {
        let comparisons = Arc::new(AtomicUsize::new(0));
        let dictionary = ObservableMultiDictionary::new(1);
        for id in 0..SIZE {
            // Pairs share first keys in tens and second keys in hundreds, so
            // the key views reuse keys as well as add them.
            let key1 = Counting::new(id / 10, &comparisons);
            let key2 = Counting::new(id % 100, &comparisons);
            build(&dictionary, key1, key2, id);
        }
        let made = take(&comparisons);
        assert!(
            made <= 4 * SIZE as usize,
            "{name} build made {made} comparisons"
        );
        assert_eq!(dictionary.count(), SIZE as usize, "{name}");
        assert_eq!(dictionary.keys1().len(), (SIZE / 10) as usize, "{name}");
        assert_eq!(dictionary.keys2().len(), 100, "{name}");
        let (key1, key2) = (
            Counting::new(42, &comparisons),
            Counting::new(23, &comparisons),
        );
        assert_eq!(dictionary.get(&key1, &key2), Some(423), "{name}");
    }
}

type Probe = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

/// A key whose `hash` and `eq` both call `probe`, which reads the dictionary
/// that holds the key.
#[derive(Clone)]
struct Reading {
    id: u32,
    probe: Probe,
}

impl Reading {
    fn call(&self) {
        let probe = self.probe.lock().unwrap().clone();
        if let Some(probe) = probe {
            probe();
        }
    }
}

impl PartialEq for Reading {
    fn eq(&self, other: &Self) -> bool {
        self.call();
        self.id == other.id
    }
}

impl Eq for Reading {}

impl std::hash::Hash for Reading {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.call();
        self.id.hash(state);
    }
}

/// #1296 — `hash` and `eq` may read the dictionary during its operations
#[test]
fn dictionary_hash_and_eq_may_read_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let key = |id| Reading {
        id,
        probe: Arc::clone(&probe),
    };
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert(key(1), "one");
    let reader = dictionary.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.keys();
    }));
    let (value, removed) = within_timeout("ObservableDictionary", BOUND, {
        let dictionary = dictionary.clone();
        let (one, two) = (key(1), key(2));
        move || {
            dictionary.insert(one.clone(), "uno");
            dictionary.insert(two.clone(), "two");
            (dictionary.get(&one), dictionary.remove(&two))
        }
    });
    *probe.lock().unwrap() = None;
    assert_eq!(value, Some("uno"));
    assert_eq!(removed, Some("two"));
    assert_eq!(dictionary.keys().len(), 1);
}

/// #1296 — `hash` and `eq` may read the multi-key dictionary during its operations
#[test]
fn multi_dictionary_hash_and_eq_may_read_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let key = |id| Reading {
        id,
        probe: Arc::clone(&probe),
    };
    let dictionary = ObservableMultiDictionary::with_hub(1, MessageHub::new());
    dictionary.insert(key(1), key(1), "one");
    let reader = dictionary.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = (
            reader.count(),
            reader.entries().len(),
            reader.keys1().to_vec(),
        );
    }));
    let (value, removed) = within_timeout("ObservableMultiDictionary", BOUND, {
        let dictionary = dictionary.clone();
        let (one, two) = (key(1), key(2));
        move || {
            dictionary.insert(one.clone(), one.clone(), "uno");
            dictionary.add(two.clone(), one.clone(), "two").unwrap();
            (dictionary.get(&one, &one), dictionary.remove(&two, &one))
        }
    });
    *probe.lock().unwrap() = None;
    assert_eq!(value, Some("uno"));
    assert_eq!(removed, Some("two"));
    assert_eq!(dictionary.count(), 1);
    assert_eq!(dictionary.keys1().len(), 1);
}
