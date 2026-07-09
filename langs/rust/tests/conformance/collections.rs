use vmx::{
    CollectionChangeAction, Command, ComponentVm, ConstructionStatus, Message, MessageHub,
    ObservableDictionary, ObservableList, ObservableMultiDictionary, PagedComposition,
    SearchableState, TokenPagedComposition,
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

/// COL-001 — ServicedObservableCollection<T> publishes to hub after local event on add
#[test]
fn serviced_collection_add_publishes_to_hub() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());

    list.push("a");

    assert_eq!(list.to_vec(), vec!["a"]);
    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

/// COL-002 — ServicedObservableCollection<T> publishes Remove/Replace/Reset
#[test]
fn serviced_collection_publishes_remove_replace_reset() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());
    list.push("a");
    list.replace(0, "b").unwrap();
    list.remove_at(0);
    list.push("c");
    list.clear();

    assert_eq!(
        collection_actions(&hub),
        vec![
            CollectionChangeAction::Add,
            CollectionChangeAction::Replace,
            CollectionChangeAction::Remove,
            CollectionChangeAction::Add,
            CollectionChangeAction::Reset,
        ]
    );
}

/// COL-003 — Null-hub fallback: no hub means no publication, no error
#[test]
fn serviced_collection_null_hub_is_safe() {
    let list = ObservableList::new(1, vmx::NullMessageHub::hub());

    list.push("a");
    list.replace(0, "b").unwrap();
    list.remove_at(0);

    assert!(list.is_empty());
}

/// COL-004 — ServicedObservableCollection<T> does not marshal; fires on caller thread
#[test]
fn serviced_collection_hub_delivery_is_synchronous() {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());
    let caller = std::thread::current().id();
    let observed = std::sync::Arc::new(std::sync::Mutex::new(None));
    let observed_inner = observed.clone();
    let _subscription = hub.subscribe(move |_| {
        *observed_inner.lock().unwrap() = Some(std::thread::current().id());
    });

    list.push("a");

    assert_eq!(*observed.lock().unwrap(), Some(caller));
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
