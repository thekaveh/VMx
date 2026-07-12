use vmx::{
    CollectionChangeAction, Command, ComponentVm, ConstructionStatus, Message, MessageHub,
    ObservableDictionary, ObservableList, ObservableMultiDictionary, PagedComposition,
    SearchableState, ServicedObservableCollection, TokenPagedComposition, VmxError,
};

fn collection_actions(hub: &MessageHub) -> Vec<CollectionChangeAction> {
    hub.history()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(change.action),
            _ => None,
        })
        .collect()
}

fn count_notifications(hub: &MessageHub) -> usize {
    hub.history()
        .into_iter()
        .filter(|message| {
            matches!(
                message,
                Message::PropertyChanged(change) if change.property_name == "Count"
            )
        })
        .count()
}

fn collection_messages(hub: &MessageHub) -> Vec<vmx::CollectionChangedMessage> {
    hub.history()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(change),
            _ => None,
        })
        .collect()
}

/// COL-001 — ServicedObservableCollection<T> publishes to hub after local event on add
#[test]
fn serviced_collection_add_publishes_to_hub() {
    let external = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(1, external.clone());
    let order = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let local_order = order.clone();
    let external_order = order.clone();
    let _local = list.collection_changed().subscribe(move |_| {
        local_order.lock().unwrap().push("local");
    });
    let _external = external.subscribe(move |_| {
        external_order.lock().unwrap().push("external");
    });

    list.push("a");

    assert_eq!(list.to_vec(), vec!["a"]);
    assert_eq!(*order.lock().unwrap(), vec!["local", "external"]);
    assert_eq!(
        collection_messages(&external),
        vec![vmx::CollectionChangedMessage {
            sender_id: 1,
            property_name: "items".to_string(),
            action: CollectionChangeAction::Add,
            old_index: None,
            new_index: Some(0),
        }]
    );
}

/// COL-002 — ServicedObservableCollection<T> publishes Remove and Replace
#[test]
fn serviced_collection_publishes_remove_and_replace() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(1, hub.clone());
    list.push("a");
    list.replace(0, "b").unwrap();
    assert_eq!(list.remove_at(0).unwrap(), "b");

    assert_eq!(
        collection_messages(&hub),
        vec![
            vmx::CollectionChangedMessage {
                sender_id: 1,
                property_name: "items".to_string(),
                action: CollectionChangeAction::Add,
                old_index: None,
                new_index: Some(0),
            },
            vmx::CollectionChangedMessage {
                sender_id: 1,
                property_name: "items".to_string(),
                action: CollectionChangeAction::Replace,
                old_index: Some(0),
                new_index: Some(0),
            },
            vmx::CollectionChangedMessage {
                sender_id: 1,
                property_name: "items".to_string(),
                action: CollectionChangeAction::Remove,
                old_index: Some(0),
                new_index: None,
            },
        ]
    );
}

/// COL-003 — Null-hub fallback: no hub means no publication, no error
#[test]
fn serviced_collection_null_hub_is_safe() {
    let list = ServicedObservableCollection::new(1);
    let local = list.collection_changed();

    list.push("a");
    list.replace(0, "b").unwrap();
    assert_eq!(list.remove_at(0).unwrap(), "b");

    assert!(list.is_empty());
    assert_eq!(
        collection_actions(&local),
        vec![
            CollectionChangeAction::Add,
            CollectionChangeAction::Replace,
            CollectionChangeAction::Remove,
        ]
    );
}

/// COL-004 — ServicedObservableCollection<T> does not marshal; fires on caller thread
#[test]
fn serviced_collection_hub_delivery_is_synchronous() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(1, hub.clone());
    let caller = std::thread::current().id();
    let observed = std::sync::Arc::new(std::sync::Mutex::new(None));
    let observed_inner = observed.clone();
    let _subscription = hub.subscribe(move |_| {
        *observed_inner.lock().unwrap() = Some(std::thread::current().id());
    });

    list.push("a");

    assert_eq!(*observed.lock().unwrap(), Some(caller));
}

/// COL-048 — serviced value removal targets the first duplicate
#[test]
fn serviced_collection_value_removal_targets_first_duplicate() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(7, hub.clone());
    list.replace_all(["a", "b", "a"]);
    let local = list.collection_changed();
    let before = collection_messages(&hub).len();
    let local_before = collection_messages(&local).len();

    assert!(list.remove(&"a"));
    assert_eq!(list.to_vec(), vec!["b", "a"]);
    assert!(!list.remove(&"missing"));

    let messages = collection_messages(&hub);
    assert_eq!(messages.len(), before + 1);
    assert_eq!(collection_messages(&local).len(), local_before + 1);
    assert_eq!(
        messages.last().unwrap().action,
        CollectionChangeAction::Remove
    );
    assert_eq!(messages.last().unwrap().old_index, Some(0));
    assert_eq!(messages.last().unwrap().new_index, None);
}

/// COL-049 — serviced indexed removal rejects invalid bounds atomically
#[test]
fn serviced_collection_indexed_removal_is_strict_and_atomic() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(8, hub.clone());
    list.replace_all(["a", "b", "c"]);
    let local = list.collection_changed();
    let before = collection_messages(&hub).len();
    let local_before = collection_messages(&local).len();

    assert_eq!(list.remove_at(1).unwrap(), "b");
    assert_eq!(list.to_vec(), vec!["a", "c"]);
    assert_eq!(
        list.remove_at(2),
        Err(VmxError::InvalidArgument("index out of range".to_string()))
    );
    assert_eq!(list.to_vec(), vec!["a", "c"]);

    let messages = collection_messages(&hub);
    assert_eq!(messages.len(), before + 1);
    assert_eq!(collection_messages(&local).len(), local_before + 1);
    assert_eq!(messages.last().unwrap().old_index, Some(1));
    assert_eq!(messages.last().unwrap().new_index, None);
}

/// COL-050 — serviced replacement emits even for equal values and is atomic on error
#[test]
fn serviced_collection_replacement_is_explicit_and_atomic() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(9, hub.clone());
    list.replace_all(["a", "b"]);
    let local = list.collection_changed();
    let before = collection_messages(&hub).len();
    let local_before = collection_messages(&local).len();

    assert_eq!(list.replace(1, "c").unwrap(), "b");
    assert_eq!(list.replace(1, "c").unwrap(), "c");
    assert_eq!(
        list.replace(2, "d"),
        Err(VmxError::InvalidArgument("index out of range".to_string()))
    );
    assert_eq!(list.to_vec(), vec!["a", "c"]);

    let changes = &collection_messages(&hub)[before..];
    assert_eq!(changes.len(), 2);
    assert_eq!(collection_messages(&local).len(), local_before + 2);
    assert!(changes.iter().all(|message| {
        message.action == CollectionChangeAction::Replace
            && message.old_index == Some(1)
            && message.new_index == Some(1)
    }));
}

/// COL-051 — serviced whole-list replacement snapshots and emits one Reset
#[test]
fn serviced_collection_replace_all_is_snapshot_atomic() {
    struct PanicAfterOne(bool);

    impl Iterator for PanicAfterOne {
        type Item = i32;

        fn next(&mut self) -> Option<Self::Item> {
            if self.0 {
                panic!("snapshot failure");
            }
            self.0 = true;
            Some(99)
        }
    }

    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(10, hub.clone());
    list.replace_all([1, 2]);
    let local = list.collection_changed();
    let before_identical = collection_messages(&hub).len();
    let local_before_identical = collection_messages(&local).len();
    list.replace_all(&list);
    assert_eq!(list.to_vec(), vec![1, 2]);
    assert_eq!(collection_messages(&hub).len(), before_identical + 1);
    assert_eq!(
        collection_messages(&local).len(),
        local_before_identical + 1
    );
    let reset = collection_messages(&hub).pop().unwrap();
    assert_eq!(reset.action, CollectionChangeAction::Reset);
    assert_eq!(reset.old_index, None);
    assert_eq!(reset.new_index, None);

    let before_panic = collection_messages(&hub).len();
    let local_before_panic = collection_messages(&local).len();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        list.replace_all(PanicAfterOne(false));
    }));
    assert!(result.is_err());
    assert_eq!(list.to_vec(), vec![1, 2]);
    assert_eq!(collection_messages(&hub).len(), before_panic);
    assert_eq!(collection_messages(&local).len(), local_before_panic);

    let empty = ServicedObservableCollection::<i32>::new(11);
    empty.replace_all(std::iter::empty());
    assert!(empty.collection_changed().history().is_empty());
}

/// COL-052 — serviced move preserves identity and precise positions
#[test]
fn serviced_collection_move_preserves_identity_and_positions() {
    let a = std::sync::Arc::new("a");
    let b = std::sync::Arc::new("b");
    let c = std::sync::Arc::new("c");
    let hub = MessageHub::new();
    let forward = ServicedObservableCollection::with_hub(12, hub.clone());
    forward.replace_all([a.clone(), b.clone(), c.clone()]);
    let before = collection_messages(&hub).len();
    forward.move_item(0, 2).unwrap();
    assert_eq!(forward.to_vec(), vec![b.clone(), c.clone(), a.clone()]);
    assert!(std::sync::Arc::ptr_eq(&forward.get(2).unwrap(), &a));
    let forward_message = &collection_messages(&hub)[before];
    assert_eq!(forward_message.action, CollectionChangeAction::Move);
    assert_eq!(forward_message.old_index, Some(0));
    assert_eq!(forward_message.new_index, Some(2));

    let backward = ServicedObservableCollection::new(13);
    backward.replace_all([a.clone(), b.clone(), c.clone()]);
    backward.move_item(2, 0).unwrap();
    assert_eq!(backward.to_vec(), vec![c, a, b]);
}

/// COL-053 — serviced move same-index and invalid bounds are no-ops
#[test]
fn serviced_collection_move_noops_and_bounds_are_strict() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(14, hub.clone());
    list.replace_all(["a", "b", "c"]);
    let local = list.collection_changed();
    let before = collection_messages(&hub).len();
    let local_before = collection_messages(&local).len();

    list.move_item(1, 1).unwrap();
    assert_eq!(
        list.move_item(3, 0),
        Err(VmxError::InvalidArgument(
            "move index out of range".to_string()
        ))
    );
    assert_eq!(
        list.move_item(0, 3),
        Err(VmxError::InvalidArgument(
            "move index out of range".to_string()
        ))
    );
    assert_eq!(list.to_vec(), vec!["a", "b", "c"]);
    assert_eq!(collection_messages(&hub).len(), before);
    assert_eq!(collection_messages(&local).len(), local_before);
}

/// COL-054 — serviced delivery is local-before-hub with final-state visibility
#[test]
fn serviced_collection_delivery_orders_every_mutation_after_state_change() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(15, hub.clone());
    let observations = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let local_observations = observations.clone();
    let local_list = list.clone();
    let external_observations = observations.clone();
    let external_list = list.clone();
    let _panicking = list.collection_changed().subscribe(|_| panic!("isolated"));
    let _local = list.collection_changed().subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            local_observations
                .lock()
                .unwrap()
                .push(("local", change.clone(), local_list.to_vec()));
        }
    });
    let _external = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            external_observations.lock().unwrap().push((
                "external",
                change.clone(),
                external_list.to_vec(),
            ));
        }
    });

    list.push(1);
    list.push(2);
    assert!(list.remove(&1));
    list.replace(0, 3).unwrap();
    list.replace_all([4, 5]);
    list.move_item(0, 1).unwrap();
    list.clear();

    let observations = observations.lock().unwrap();
    assert_eq!(observations.len(), 14);
    for pair in observations.chunks_exact(2) {
        assert_eq!(pair[0].0, "local");
        assert_eq!(pair[1].0, "external");
        assert_eq!(pair[0].1, pair[1].1);
        assert_eq!(pair[0].2, pair[1].2);
    }
    assert_eq!(observations.last().unwrap().2, Vec::<i32>::new());
    assert!(list
        .collection_changed()
        .history()
        .iter()
        .all(|message| matches!(message, Message::CollectionChanged(_))));
}

// Reentrant regression for COL-054: nested changes wait for both outer deliveries.
#[test]
fn serviced_collection_reentrant_delivery_keeps_local_external_pairs_ordered() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(18, hub.clone());
    let observations = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));

    let local_observations = observations.clone();
    let local_list = list.clone();
    let _local_recorder = list.collection_changed().subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            local_observations.lock().unwrap().push((
                "local",
                change.new_index,
                local_list.to_vec(),
            ));
        }
    });

    let nested_once = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let nested_guard = nested_once.clone();
    let nested_list = list.clone();
    let _reentrant = list.collection_changed().subscribe(move |message| {
        if matches!(
            message,
            Message::CollectionChanged(vmx::CollectionChangedMessage {
                action: CollectionChangeAction::Add,
                new_index: Some(0),
                ..
            })
        ) && !nested_guard.swap(true, std::sync::atomic::Ordering::SeqCst)
        {
            nested_list.push("nested");
        }
    });

    let external_observations = observations.clone();
    let external_list = list.clone();
    let _external = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            external_observations.lock().unwrap().push((
                "external",
                change.new_index,
                external_list.to_vec(),
            ));
        }
    });

    list.push("outer");

    assert_eq!(list.to_vec(), vec!["outer", "nested"]);
    assert_eq!(
        *observations.lock().unwrap(),
        vec![
            ("local", Some(0), vec!["outer"]),
            ("external", Some(0), vec!["outer", "nested"]),
            ("local", Some(1), vec!["outer", "nested"]),
            ("external", Some(1), vec!["outer", "nested"]),
        ]
    );
}

// Concurrency companion for COL-004/COL-054: foreign publishers wait and drain themselves.
#[test]
fn serviced_collection_foreign_publisher_waits_and_delivers_on_caller_thread() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(19, hub.clone());
    let gate = std::sync::Arc::new((
        std::sync::Mutex::new((false, false)),
        std::sync::Condvar::new(),
    ));
    let local_gate = gate.clone();
    let _blocking_local = list.collection_changed().subscribe(move |message| {
        if matches!(
            message,
            Message::CollectionChanged(vmx::CollectionChangedMessage {
                action: CollectionChangeAction::Add,
                new_index: Some(0),
                ..
            })
        ) {
            let (state, ready) = &*local_gate;
            let mut state = state.lock().unwrap();
            state.0 = true;
            ready.notify_all();
            while !state.1 {
                state = ready.wait(state).unwrap();
            }
        }
    });

    let foreign_observed = std::sync::Arc::new(std::sync::Mutex::new(None));
    let observed = foreign_observed.clone();
    let _external = hub.subscribe(move |message| {
        if matches!(
            message,
            Message::CollectionChanged(vmx::CollectionChangedMessage {
                action: CollectionChangeAction::Add,
                new_index: Some(1),
                ..
            })
        ) {
            *observed.lock().unwrap() = Some(std::thread::current().id());
        }
    });

    let outer_list = list.clone();
    let outer = std::thread::spawn(move || outer_list.push("outer"));
    {
        let (state, ready) = &*gate;
        let mut state = state.lock().unwrap();
        while !state.0 {
            state = ready.wait(state).unwrap();
        }
    }

    let (done_tx, done_rx) = std::sync::mpsc::channel();
    let foreign_list = list.clone();
    let foreign = std::thread::spawn(move || {
        let caller = std::thread::current().id();
        foreign_list.push("foreign");
        done_tx.send(caller).unwrap();
    });

    for _ in 0..100_000 {
        if list.len() == 2 {
            break;
        }
        std::thread::yield_now();
    }
    assert_eq!(list.len(), 2, "foreign mutation did not reach publication");
    assert!(matches!(
        done_rx.try_recv(),
        Err(std::sync::mpsc::TryRecvError::Empty)
    ));

    {
        let (state, ready) = &*gate;
        let mut state = state.lock().unwrap();
        state.1 = true;
        ready.notify_all();
    }
    outer.join().unwrap();
    let foreign_caller = done_rx.recv().unwrap();
    foreign.join().unwrap();

    assert_eq!(*foreign_observed.lock().unwrap(), Some(foreign_caller));
    assert_eq!(
        collection_messages(&hub)
            .into_iter()
            .map(|message| message.new_index)
            .collect::<Vec<_>>(),
        vec![Some(0), Some(1)]
    );
}

// Debug-path companion for COL-054: an unwinding hub drain cannot strand the coordinator.
#[cfg(debug_assertions)]
#[test]
fn serviced_collection_delivery_recovers_after_debug_hub_unwind() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(20, hub.clone());
    let cycling_hub = hub.clone();
    let cycle = hub.subscribe(move |_| {
        cycling_hub.send(Message::Custom {
            sender_id: 20,
            name: "cycle".to_string(),
        });
    });

    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        list.push("first");
    }));
    assert!(result.is_err());

    drop(cycle);
    list.push("second");

    assert_eq!(list.to_vec(), vec!["first", "second"]);
    let last_change = collection_messages(&hub).pop().unwrap();
    assert_eq!(last_change.action, CollectionChangeAction::Add);
    assert_eq!(last_change.new_index, Some(1));
}

/// COL-055 — serviced clear and all mutations preserve caller ownership
#[test]
fn serviced_collection_clear_and_mutations_preserve_caller_ownership() {
    #[derive(Clone, Debug, PartialEq, Eq)]
    struct Probe(std::sync::Arc<()>);

    let first = Probe(std::sync::Arc::new(()));
    let second = Probe(std::sync::Arc::new(()));
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(16, hub.clone());
    list.clear();
    assert!(list.collection_changed().history().is_empty());
    assert!(hub.history().is_empty());

    list.push(first.clone());
    list.push(second.clone());
    assert!(list.remove(&first));
    let removed = list.remove_at(0).unwrap();
    list.push(removed.clone());
    let replaced = list.replace(0, first.clone()).unwrap();
    list.replace_all([replaced.clone(), first.clone()]);
    list.move_item(0, 1).unwrap();
    list.clear();

    assert!(list.is_empty());
    assert!(std::sync::Arc::strong_count(&first.0) >= 1);
    assert!(std::sync::Arc::strong_count(&second.0) >= 1);
    assert_eq!(
        collection_actions(&list.collection_changed()).last(),
        Some(&CollectionChangeAction::Reset)
    );

    #[derive(Clone)]
    struct NonEquatable(std::sync::Arc<()>);

    let one = NonEquatable(std::sync::Arc::new(()));
    let two = NonEquatable(std::sync::Arc::new(()));
    let non_equatable = ServicedObservableCollection::new(17);
    non_equatable.push(one.clone());
    let old = non_equatable.replace(0, two.clone()).unwrap();
    assert!(std::sync::Arc::ptr_eq(&old.0, &one.0));
    non_equatable.replace_all([one.clone(), two.clone()]);
    non_equatable.move_item(0, 1).unwrap();
    let removed = non_equatable.remove_at(1).unwrap();
    assert!(std::sync::Arc::ptr_eq(&removed.0, &one.0));
    non_equatable.clear();
}

/// COL-005 — ObservableList<T> ItemAdded payload shape
#[test]
fn observable_list_add_emits_add() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());

    list.push("a");

    assert_eq!(list.to_vec(), vec!["a"]);
    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

/// COL-006 — ObservableList<T> ItemRemoved payload shape
#[test]
fn observable_list_remove_emits_remove() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());
    list.push("a");

    assert_eq!(list.remove_at(0), Some("a"));

    assert!(collection_actions(&hub).contains(&CollectionChangeAction::Remove));
}

/// COL-007 — ObservableList<T> ItemReplaced payload shape
#[test]
fn observable_list_replace_emits_replace_without_count_change() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());
    list.push("a");

    let old = list.replace(0, "b").unwrap();

    assert_eq!(old, "a");
    assert_eq!(list.to_vec(), vec!["b"]);
    assert!(collection_actions(&hub).contains(&CollectionChangeAction::Replace));
}

/// COL-008 — ObservableList<T> Count / PropertyChanged ordering after add
#[test]
fn observable_list_add_emits_count_notification_after_collection_change() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());

    list.push("a");

    let history = hub.history();
    assert!(matches!(history[0], Message::CollectionChanged(_)));
    assert!(matches!(history[1], Message::PropertyChanged(_)));
}

/// COL-009 — ObservableList<T> batch suppression
#[test]
fn observable_list_batch_emits_single_reset() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());

    list.batch_update(|| {
        list.push("a");
        list.push("b");
    });

    assert_eq!(
        collection_actions(&hub),
        vec![CollectionChangeAction::Reset]
    );
    assert_eq!(count_notifications(&hub), 1);
}

/// COL-010 — ObservableDictionary insert and retrieve
#[test]
fn observable_dictionary_insert_and_get() {
    let dictionary = ObservableDictionary::new(1, MessageHub::new());

    dictionary.insert("a", 1);

    assert_eq!(dictionary.get(&"a"), Some(1));
}

/// COL-011 — ObservableDictionary remove
#[test]
fn observable_dictionary_remove() {
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert("a", 1);

    assert_eq!(dictionary.remove(&"a"), Some(1));
    assert_eq!(dictionary.get(&"a"), None);
}

/// COL-012 — ObservableDictionary replace
#[test]
fn observable_dictionary_replace_existing_key() {
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert("a", 1);
    dictionary.insert("a", 2);

    assert_eq!(dictionary.get(&"a"), Some(2));
}

/// COL-013 — ObservableDictionary distinct-key observable views stay in sync
#[test]
fn observable_multi_dictionary_distinct_key_views_stay_in_sync() {
    let dictionary = ObservableMultiDictionary::new(1, MessageHub::new());

    dictionary.insert("a", 1, "x");
    dictionary.insert("a", 2, "y");
    dictionary.remove(&"a", &1);

    assert_eq!(dictionary.keys1(), vec!["a"]);
    assert_eq!(dictionary.keys2(), vec![2]);
    assert_eq!(dictionary.count(), 1);
}

/// COL-014 — ObservableDictionary enumeration order is insertion order
#[test]
fn observable_dictionary_keys_are_in_insertion_order() {
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert("b", 2);
    dictionary.insert("a", 1);

    assert_eq!(dictionary.keys(), vec!["b", "a"]);
}

/// COL-015 — ObservableDictionary clear empties keys views
#[test]
fn observable_dictionary_clear_empties_keys() {
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert("a", 1);

    dictionary.clear();

    assert!(dictionary.keys().is_empty());
}

/// COL-016 — PagedComposition<TVM> clamps CurrentPageIndex when source shrinks
#[test]
fn paged_composition_clamps_when_source_shrinks() {
    let pages = PagedComposition::new(vec![1, 2, 3, 4, 5], 2);
    pages.next_page();
    pages.next_page();

    pages.set_source(vec![1]);

    assert_eq!(pages.current_page_index(), 0);
}

/// COL-017 — PagedComposition<TVM> PageCount derivation under add and remove
#[test]
fn paged_composition_page_count_tracks_add_remove() {
    let pages = PagedComposition::new(vec![1, 2], 2);
    assert_eq!(pages.page_count(), 1);

    pages.push(3);
    assert_eq!(pages.page_count(), 2);
    pages.remove_at(2);
    assert_eq!(pages.page_count(), 1);
}

/// COL-018 — PagedComposition<TVM> navigation no-ops at bounds
#[test]
fn paged_composition_navigation_clamps_at_bounds() {
    let pages = PagedComposition::new(vec![1, 2], 1);

    pages.previous_page();
    assert_eq!(pages.current_page_index(), 0);
    pages.next_page();
    pages.next_page();
    assert_eq!(pages.current_page_index(), 1);
}

/// COL-019 — PagedComposition<TVM> PageSize == 0 passes through all items
#[test]
fn page_size_zero_returns_all_items() {
    let pages = PagedComposition::new(vec![1, 2, 3], 0);

    assert_eq!(pages.current_page(), vec![1, 2, 3]);
}

/// COL-020 — PagedComposition<TVM> empty-source behavior
#[test]
fn paged_composition_empty_source_has_zero_pages() {
    let pages = PagedComposition::<i32>::new(Vec::new(), 2);

    assert_eq!(pages.page_count(), 0);
    assert!(pages.current_page().is_empty());
}

/// COL-021 — PagedComposition<TVM> composition with SearchableState<T>
#[test]
fn paged_composition_composes_with_searchable_state() {
    let search = SearchableState::new(vec!["alpha", "beta", "alpine"], |item, term| {
        item.contains(term)
    });
    search.set_search_term("alp");
    let pages = PagedComposition::new(search.filtered(), 1);

    assert_eq!(pages.page_count(), 2);
    assert_eq!(pages.current_page(), vec!["alpha"]);
}

/// COL-022 — ObservableDictionary hub publication
#[test]
fn observable_dictionary_publishes_to_hub() {
    let hub = MessageHub::new();
    let dictionary = ObservableDictionary::new(1, hub.clone());

    dictionary.insert("a", 1);

    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

/// COL-023 — ObservableList batch-end Count notification
#[test]
fn observable_list_batch_end_count_notification() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());

    list.batch_update(|| list.push("a"));

    assert_eq!(count_notifications(&hub), 1);
}

/// COL-024 — TokenPagedComposition<TVM,TToken> initial state
#[test]
fn token_paged_initial_state_is_empty_and_loadable() {
    let pages = TokenPagedComposition::<i32, usize>::with_loader(None, |_| (vec![1], Some(1)));

    assert!(pages.items().is_empty());
    assert_eq!(pages.current_token(), None);
    assert!(pages.has_more());
    assert!(pages.load_more_command().can_execute());
}

/// COL-025 — token load-more appends items and advances token
#[test]
fn token_load_more_appends_and_passes_next_token() {
    let seen_tokens = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let seen = seen_tokens.clone();
    let pages = TokenPagedComposition::with_loader(None, move |token| {
        seen.lock().unwrap().push(token);
        match token {
            None => (vec![1, 2], Some(7)),
            Some(7) => (vec![3], None),
            _ => (Vec::new(), None),
        }
    });

    pages.load_next();
    assert_eq!(pages.items(), vec![1, 2]);
    assert_eq!(pages.current_token(), Some(7));

    pages.load_next();
    assert_eq!(pages.items(), vec![1, 2, 3]);
    assert_eq!(*seen_tokens.lock().unwrap(), vec![None, Some(7)]);
}

/// COL-026 — terminal token disables load-more
#[test]
fn token_terminal_token_disables_load_more() {
    let pages = TokenPagedComposition::<i32, usize>::with_loader(None, |_| (vec![1], None));

    pages.load_next();

    assert!(!pages.has_more());
    assert!(!pages.load_more_command().can_execute());
}

/// COL-027 — refresh refetches from the initial token
#[test]
fn token_refresh_refetches_from_initial_token() {
    let seen_tokens = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let seen = seen_tokens.clone();
    let pages = TokenPagedComposition::with_loader(None, move |token| {
        seen.lock().unwrap().push(token);
        match seen.lock().unwrap().len() {
            1 => (vec![1], Some(9)),
            _ => (vec![5], Some(3)),
        }
    });

    pages.load_next();
    pages.refresh();

    assert_eq!(pages.items(), vec![5]);
    assert_eq!(pages.current_token(), Some(3));
    assert_eq!(*seen_tokens.lock().unwrap(), vec![None, None]);
}

/// COL-028 — refresh dedup suppresses redundant mutation
#[test]
fn token_refresh_dedup_suppresses_redundant_reset() {
    let hub = MessageHub::new();
    let pages = TokenPagedComposition::with_loader_and_hub(None, |_| (vec![1, 2], Some(1)), hub);

    pages.load_next();
    pages.refresh();

    assert_eq!(
        collection_actions(&pages.hub()),
        vec![CollectionChangeAction::Reset]
    );
}

/// COL-029 — token-paged collection changes use reset semantics
#[test]
fn token_load_uses_reset_collection_event() {
    let pages = TokenPagedComposition::<i32, usize>::with_loader(None, |_| (vec![1], Some(1)));

    pages.load_next();

    assert_eq!(
        collection_actions(&pages.hub()),
        vec![CollectionChangeAction::Reset]
    );
}

/// COL-030 — token-paged auto-construct-on-add
#[test]
fn token_auto_construct_constructs_before_reset_event() {
    let child = ComponentVm::with_model("child", "model", MessageHub::new(), vmx::NullDispatcher);
    let observed_status = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let observed = observed_status.clone();
    let pages = TokenPagedComposition::<ComponentVm<&str>, usize>::with_auto_construct_loader(
        None,
        move |_| (vec![child.clone()], None),
    );
    let pages_for_observer = pages.clone();

    let _subscription = pages.hub().subscribe(move |_| {
        observed
            .lock()
            .unwrap()
            .push(pages_for_observer.items()[0].status());
    });

    pages.load_next();

    assert_eq!(
        *observed_status.lock().unwrap(),
        vec![ConstructionStatus::Constructed]
    );
}

/// COL-031 — PagedComposition<TVM> observes composite collection changes
#[test]
fn paged_composition_can_recompute_after_source_collection_changes() {
    let pages = PagedComposition::new(vec![1, 2], 2);
    pages.push(3);

    assert_eq!(pages.page_count(), 2);
    assert_eq!(pages.current_page(), vec![1, 2]);
}
