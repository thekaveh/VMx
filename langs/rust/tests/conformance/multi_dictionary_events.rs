//! `ObservableMultiDictionary` local events, optional hub and live key views
//! (spec/21-collections.md §4.1, §4.2 and §4.6, ADR-0177, ADR-0208, #1257).

use std::sync::{Arc, Mutex};

use vmx::{CollectionChangeAction, Message, MessageHub, ObservableMultiDictionary};

type Dictionary = ObservableMultiDictionary<u32, u32, u32>;
type Change = (CollectionChangeAction, Option<usize>);

fn changes(stream: &MessageHub) -> (Arc<Mutex<Vec<Change>>>, vmx::Subscription) {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let subscription = stream.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            sink.lock()
                .unwrap()
                .push((change.action.clone(), change.new_index));
        }
    });
    (seen, subscription)
}

/// Asserts that each key view lists each distinct key of the entries once.
/// A view keeps the order in which its keys first appeared, which can differ
/// from the entry order after a removal (spec/21 §4.2).
fn assert_views_match_entries(dictionary: &Dictionary) {
    let entries = dictionary.entries();
    let distinct = |keys: Vec<u32>| {
        let mut keys = keys;
        keys.sort_unstable();
        keys.dedup();
        keys
    };
    let sorted = |keys: Vec<u32>| {
        let mut keys = keys;
        keys.sort_unstable();
        keys
    };
    assert_eq!(
        sorted(dictionary.keys1().to_vec()),
        distinct(entries.iter().map(|entry| entry.0).collect()),
        "keys1 for {entries:?}"
    );
    assert_eq!(
        sorted(dictionary.keys2().to_vec()),
        distinct(entries.iter().map(|entry| entry.1).collect()),
        "keys2 for {entries:?}"
    );
}

/// COL-010 — a dictionary without a hub reports each change on its local stream
#[test]
fn dictionary_without_a_hub_reports_changes_locally() {
    let dictionary = Dictionary::new(1);
    let (seen, _local) = changes(&dictionary.collection_changed());

    dictionary.add(1, 1, 10).unwrap();
    dictionary.insert(2, 1, 20);
    dictionary.insert(1, 1, 11);
    assert!(dictionary.add(1, 1, 12).is_err());
    assert_eq!(dictionary.remove(&1, &1), Some(11));
    assert_eq!(dictionary.remove(&1, &1), None);
    dictionary.clear();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            (CollectionChangeAction::Add, Some(0)),
            (CollectionChangeAction::Add, Some(1)),
            // A Replace keeps the entry in place, so its new position is its
            // index (ADR-0193); a Remove has no new position.
            (CollectionChangeAction::Replace, Some(0)),
            (CollectionChangeAction::Remove, None),
            (CollectionChangeAction::Reset, None),
        ]
    );
    assert_eq!(dictionary.count(), 0);
    assert_views_match_entries(&dictionary);
}

/// COL-010 — an Add hub message carries the entry's position when it is sent
#[test]
fn add_hub_position_is_read_when_the_message_is_sent() {
    let hub = MessageHub::new();
    let dictionary = Dictionary::with_hub(1, hub.clone());
    dictionary.add(1, 1, 10).unwrap();
    dictionary.add(2, 2, 20).unwrap();
    // The local subscriber removes entry (1, 1) once (3, 3) is added, so the
    // added entry moves from position 2 to position 1 before the hub message.
    let writer = dictionary.clone();
    let _local = dictionary.collection_changed().subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change)
            if change.action == CollectionChangeAction::Add && change.new_index == Some(2))
        {
            writer.remove(&1, &1);
        }
    });
    let (seen, _hub) = changes(&hub);

    dictionary.add(3, 3, 30).unwrap();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            (CollectionChangeAction::Add, Some(1)),
            (CollectionChangeAction::Remove, None),
        ]
    );
    assert_eq!(dictionary.entries(), vec![(2, 2, 20), (3, 3, 30)]);
    assert_views_match_entries(&dictionary);
}

/// COL-013 — a key-view subscriber that changes the dictionary keeps both views in step
#[test]
fn nested_mutation_from_a_key_view_subscriber_keeps_the_views_in_step() {
    let dictionary = Dictionary::new(1);
    let writer = dictionary.clone();
    let _nested = dictionary.keys1().item_added().subscribe(move |added| {
        if added.item < 3 {
            writer.insert(added.item + 1, added.item, added.item);
            writer.remove(&0, &0);
        }
    });

    dictionary.add(0, 0, 0).unwrap();

    assert_eq!(dictionary.entries(), vec![(1, 0, 0), (2, 1, 1), (3, 2, 2)]);
    assert_views_match_entries(&dictionary);
}

/// COL-013 — writers on several threads keep both views in step with the entries
#[test]
fn concurrent_writers_keep_the_views_in_step() {
    let dictionary = Dictionary::new(1);
    let writers: Vec<_> = (0..4)
        .map(|thread| {
            let dictionary = dictionary.clone();
            std::thread::spawn(move || {
                for round in 0..200 {
                    let key = (round % 17, thread);
                    dictionary.insert(key.0, key.1, round);
                    if round % 3 == 0 {
                        dictionary.remove(&((round + 5) % 17), &thread);
                    }
                }
            })
        })
        .collect();
    for writer in writers {
        writer.join().unwrap();
    }

    assert_views_match_entries(&dictionary);
}

/// COL-013 — a key view keeps the order in which its keys first appeared
#[test]
fn key_views_keep_first_appearance_order_after_a_removal() {
    let dictionary = Dictionary::new(1);
    dictionary.add(1, 10, 0).unwrap();
    dictionary.add(2, 10, 0).unwrap();
    dictionary.add(1, 20, 0).unwrap();

    assert_eq!(dictionary.remove(&1, &10), Some(0));

    // Key 1 still has an entry, so it keeps its place before key 2.
    assert_eq!(dictionary.entries(), vec![(2, 10, 0), (1, 20, 0)]);
    assert_eq!(dictionary.keys1().to_vec(), vec![1, 2]);
    assert_eq!(dictionary.keys2().to_vec(), vec![10, 20]);

    // A key that disappears and comes back goes to the end of its view.
    assert_eq!(dictionary.remove(&2, &10), Some(0));
    dictionary.add(3, 10, 0).unwrap();
    assert_eq!(dictionary.keys1().to_vec(), vec![1, 3]);
    assert_eq!(dictionary.keys2().to_vec(), vec![20, 10]);
}

/// A one-shot hook that a comparison runs.
type Hook = Arc<Mutex<Option<Box<dyn FnMut() + Send>>>>;

/// A first key whose `eq` runs a hook, so a test can change the dictionary
/// from a comparison and then panic.
#[derive(Clone)]
struct Hooked {
    id: u32,
    hook: Hook,
}

impl PartialEq for Hooked {
    fn eq(&self, other: &Self) -> bool {
        let hook = self.hook.lock().unwrap().take();
        if let Some(mut hook) = hook {
            hook();
        }
        self.id == other.id
    }
}

impl Eq for Hooked {}

impl std::hash::Hash for Hooked {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

/// COL-013 — a comparison that changes the dictionary and then panics leaves the views in step
#[test]
fn panicking_comparison_after_a_nested_mutation_keeps_the_views_in_step() {
    let hook: Hook = Arc::new(Mutex::new(None));
    let key = |id| Hooked {
        id,
        hook: Arc::clone(&hook),
    };
    let dictionary = ObservableMultiDictionary::new(1);
    dictionary.add(key(1), 1, "one").unwrap();
    dictionary.add(key(2), 2, "two").unwrap();
    let (seen, _local) = changes(&dictionary.collection_changed());
    let writer = dictionary.clone();
    let doomed = key(2);
    *hook.lock().unwrap() = Some(Box::new(move || {
        writer.remove(&doomed, &2);
        panic!("comparison failed");
    }) as Box<dyn FnMut() + Send>);

    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        dictionary.insert(key(1), 1, "uno");
    }));

    assert!(result.is_err());
    assert!(
        seen.lock().unwrap().is_empty(),
        "the unwinding thread sent nothing"
    );
    let ids = |keys: Vec<Hooked>| keys.iter().map(|key| key.id).collect::<Vec<_>>();
    assert_eq!(ids(dictionary.keys1().to_vec()), vec![1]);
    assert_eq!(dictionary.keys2().to_vec(), vec![1]);
    // The dictionary still admits writers, and the views follow them.
    dictionary.add(key(3), 3, "three").unwrap();
    assert_eq!(ids(dictionary.keys1().to_vec()), vec![1, 3]);
    assert_eq!(seen.lock().unwrap().len(), 1);
}
