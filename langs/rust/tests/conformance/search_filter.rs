use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{Message, MessageHub, SearchableState};

fn contains(item: &&'static str, term: &str) -> bool {
    term.is_empty() || item.to_lowercase().contains(&term.to_lowercase())
}

/// COMP-014 — SearchableState defaults to empty search term
#[test]
fn searchable_state_defaults_to_empty_term() {
    let state = SearchableState::new(vec!["alpha", "beta"], contains);

    assert_eq!(state.search_term(), "");
    assert_eq!(state.filtered(), vec!["alpha", "beta"]);
}

/// COMP-015 — Setting SearchTerm triggers a debounced recompute
#[test]
fn setting_search_term_triggers_recompute_notification() {
    let state = SearchableState::new(vec!["alpha", "beta"], contains);
    let hits = Arc::new(Mutex::new(0));
    let seen = hits.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        *seen.lock().unwrap() += 1;
    });

    state.set_search_term("alp");

    assert_eq!(*hits.lock().unwrap(), 1);
    assert_eq!(state.filtered(), vec!["alpha"]);
}

/// COMP-016 — search() forces immediate recompute, bypassing debounce
#[test]
fn search_returns_current_filtered_projection() {
    let state = SearchableState::new(vec!["alpha", "beta"], contains);
    state.set_search_term("bet");

    assert_eq!(state.search(), vec!["beta"]);
}

/// COMP-017 — Predicate is user-supplied
#[test]
fn predicate_is_user_supplied() {
    let state = SearchableState::new(vec!["a", "bb", "ccc"], |item: &&'static str, term| {
        item.len() > term.len()
    });
    state.set_search_term("bb");

    assert_eq!(state.search(), vec!["ccc"]);
    assert_eq!(state.filtered(), vec!["ccc"]);
}

/// COMP-018 — Filtered recomputes when Items source changes
#[test]
fn filtered_reads_live_items_provider() {
    let items = Arc::new(Mutex::new(vec!["alpha"]));
    let source = items.clone();
    let state = SearchableState::from_items(move || source.lock().unwrap().clone(), contains);
    state.set_search_term("a");

    items.lock().unwrap().push("gamma");

    assert_eq!(state.filtered(), vec!["alpha", "gamma"]);
}

/// GRP-007 — SearchableState defaults to empty search term (group context)
#[test]
fn group_context_defaults_to_empty_term() {
    let state = SearchableState::new(vec!["one"], contains);

    assert_eq!(state.search_term(), "");
}

/// GRP-008 — Setting SearchTerm triggers debounced recompute (group context)
#[test]
fn group_context_search_term_filters() {
    let state = SearchableState::new(vec!["one", "two"], contains);
    state.set_search_term("tw");

    assert_eq!(state.filtered(), vec!["two"]);
}

/// GRP-009 — search() forces immediate recompute (group context)
#[test]
fn group_context_search_forces_immediate_projection() {
    let state = SearchableState::new(vec!["one", "two"], contains);
    state.set_search_term("on");

    assert_eq!(state.search(), vec!["one"]);
}

/// GRP-010 — Predicate is user-supplied (group context)
#[test]
fn group_context_predicate_is_user_supplied() {
    // Prefix match on the term's reversal: no substring filter would select
    // "cba" for "abc" while rejecting "abc" itself.
    let custom = |item: &&'static str, term: &str| {
        let reversed = term.chars().rev().collect::<String>();
        !term.is_empty() && item.starts_with(&reversed)
    };
    let items = vec!["abc", "cba", "cbazz", "xabc"];
    let state = SearchableState::new(items.clone(), custom);
    state.set_search_term("abc");

    let searched = state.search();
    let substring = items
        .iter()
        .copied()
        .filter(|item| contains(item, "abc"))
        .collect::<Vec<_>>();

    assert_eq!(searched, vec!["cba", "cbazz"]);
    assert_eq!(state.filtered(), vec!["cba", "cbazz"]);
    assert_ne!(
        searched, substring,
        "the custom rule must not equal a substring filter"
    );
}

fn pulse(hub: &MessageHub) {
    hub.send(Message::Custom {
        sender_id: 0,
        sender_name: "source".to_string(),
        name: "source_changed".to_string(),
    });
}

/// SRCH-001 — source signal refreshes an unchanged search term
#[test]
fn source_signal_refreshes_unchanged_term() {
    let items = Arc::new(Mutex::new(vec!["one"]));
    let source = items.clone();
    let source_changes = MessageHub::new();
    let state = SearchableState::from_items_with_changes(
        move || source.lock().unwrap().clone(),
        contains,
        source_changes.clone(),
    );
    let snapshots = Arc::new(Mutex::new(Vec::new()));
    let seen = snapshots.clone();
    let observed = state.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.lock().unwrap().push(observed.filtered());
    });

    items.lock().unwrap().push("two");
    pulse(&source_changes);

    assert_eq!(snapshots.lock().unwrap().as_slice(), &[vec!["one", "two"]]);
}

/// SRCH-002 — remove, replace, reset, and reorder read the latest source
#[test]
fn source_mutations_read_latest_ordered_snapshot() {
    let items = Arc::new(Mutex::new(vec!["a", "b", "c"]));
    let source = items.clone();
    let source_changes = MessageHub::new();
    let state = SearchableState::from_items_with_changes(
        move || source.lock().unwrap().clone(),
        contains,
        source_changes.clone(),
    );
    let snapshots = Arc::new(Mutex::new(Vec::new()));
    let seen = snapshots.clone();
    let observed = state.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.lock().unwrap().push(observed.filtered());
    });

    items.lock().unwrap().remove(1);
    pulse(&source_changes);
    assert_eq!(snapshots.lock().unwrap().last(), Some(&vec!["a", "c"]));

    items.lock().unwrap()[1] = "replacement";
    pulse(&source_changes);
    assert_eq!(
        snapshots.lock().unwrap().last(),
        Some(&vec!["a", "replacement"])
    );

    *items.lock().unwrap() = vec!["reset-1", "reset-2", "reset-3"];
    pulse(&source_changes);
    assert_eq!(
        snapshots.lock().unwrap().last(),
        Some(&vec!["reset-1", "reset-2", "reset-3"])
    );

    items.lock().unwrap().reverse();
    pulse(&source_changes);
    assert_eq!(
        snapshots.lock().unwrap().last(),
        Some(&vec!["reset-3", "reset-2", "reset-1"])
    );
}

/// SRCH-003 — source pulses preserve equality and upstream coalescing
#[test]
fn source_pulses_preserve_equality_and_upstream_coalescing() {
    let items = Arc::new(Mutex::new(vec!["same"]));
    let source = items.clone();
    let source_changes = MessageHub::new();
    let state = SearchableState::from_items_with_changes(
        move || source.lock().unwrap().clone(),
        contains,
        source_changes.clone(),
    );
    let hits = Arc::new(AtomicUsize::new(0));
    let seen = hits.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.fetch_add(1, Ordering::SeqCst);
    });

    pulse(&source_changes);
    pulse(&source_changes);
    assert_eq!(hits.load(Ordering::SeqCst), 2);

    items
        .lock()
        .unwrap()
        .extend_from_slice(&["batched-1", "batched-2"]);
    pulse(&source_changes);
    assert_eq!(hits.load(Ordering::SeqCst), 3);
    assert_eq!(state.filtered(), vec!["same", "batched-1", "batched-2"]);
}

/// SRCH-004 — source and established synchronous term notifications are independent
#[test]
fn source_and_term_notifications_remain_independent() {
    let items = Arc::new(Mutex::new(vec!["alpha", "beta"]));
    let source = items.clone();
    let source_changes = MessageHub::new();
    let state = SearchableState::from_items_with_changes(
        move || source.lock().unwrap().clone(),
        contains,
        source_changes.clone(),
    );
    let snapshots = Arc::new(Mutex::new(Vec::new()));
    let seen = snapshots.clone();
    let observed = state.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.lock().unwrap().push(observed.filtered());
    });

    state.set_search_term("alp");
    items.lock().unwrap().push("alpine");
    pulse(&source_changes);

    assert_eq!(snapshots.lock().unwrap().len(), 2);
    assert_eq!(state.filtered(), vec!["alpha", "alpine"]);
}

/// SRCH-005 — source disposal is isolated from explicit search
#[test]
fn source_disposal_is_isolated_from_manual_search() {
    let items = Arc::new(Mutex::new(vec!["one"]));
    let source = items.clone();
    let source_changes = MessageHub::new();
    let state = SearchableState::from_items_with_changes(
        move || source.lock().unwrap().clone(),
        contains,
        source_changes.clone(),
    );
    let hits = Arc::new(AtomicUsize::new(0));
    let seen = hits.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.fetch_add(1, Ordering::SeqCst);
    });

    source_changes.dispose();
    items.lock().unwrap().push("two");

    assert_eq!(state.search(), vec!["one", "two"]);
    assert_eq!(hits.load(Ordering::SeqCst), 1);
}

/// SRCH-006 — disposal cancels source observation once without owning the source
#[test]
fn dispose_cancels_source_observation_without_owning_source() {
    let source_changes = MessageHub::new();
    let state =
        SearchableState::from_items_with_changes(|| vec!["one"], contains, source_changes.clone());
    let filtered_hits = Arc::new(AtomicUsize::new(0));
    let seen = filtered_hits.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.fetch_add(1, Ordering::SeqCst);
    });

    state.dispose();
    state.dispose();
    pulse(&source_changes);
    assert_eq!(filtered_hits.load(Ordering::SeqCst), 0);

    let independent_hits = Arc::new(AtomicUsize::new(0));
    let independent_seen = independent_hits.clone();
    let _independent = source_changes.subscribe(move |_| {
        independent_seen.fetch_add(1, Ordering::SeqCst);
    });
    pulse(&source_changes);
    assert_eq!(independent_hits.load(Ordering::SeqCst), 1);
}

#[test]
fn disposed_searchable_state_reads_an_empty_term() {
    let state = SearchableState::new(vec!["alpha"], contains);
    state.set_search_term("alp");
    assert_eq!(state.search_term(), "alp");

    state.dispose();
    state.set_search_term("changed");

    assert_eq!(state.search_term(), "");
}

#[test]
fn search_after_disposal_is_inert_without_calling_user_code() {
    let provider_calls = Arc::new(AtomicUsize::new(0));
    let predicate_calls = Arc::new(AtomicUsize::new(0));
    let state = SearchableState::from_items(
        {
            let provider_calls = provider_calls.clone();
            move || {
                provider_calls.fetch_add(1, Ordering::SeqCst);
                vec!["alpha"]
            }
        },
        {
            let predicate_calls = predicate_calls.clone();
            move |_item, _term| {
                predicate_calls.fetch_add(1, Ordering::SeqCst);
                true
            }
        },
    );
    state.dispose();

    assert!(state.search().is_empty());
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(predicate_calls.load(Ordering::SeqCst), 0);
}

/// A search item backed by a real VM whose dispose hook increments
/// `dispose_count`, so ownership assertions observe actual disposal.
#[derive(Clone)]
struct OwnedSearchItem {
    value: &'static str,
    vm: vmx::ComponentVm,
    dispose_count: Arc<AtomicUsize>,
}

impl OwnedSearchItem {
    fn new(value: &'static str) -> Self {
        let dispose_count = Arc::new(AtomicUsize::new(0));
        let vm = vmx::ComponentVm::new(value);
        let hook_count = dispose_count.clone();
        vm.on_dispose(move || {
            hook_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        });
        Self {
            value,
            vm,
            dispose_count,
        }
    }
}

/// SRCH-007 — omitting the signal preserves explicit refresh and item ownership
#[test]
fn omitted_signal_preserves_explicit_refresh_and_item_ownership() {
    let first = OwnedSearchItem::new("one");
    let second = OwnedSearchItem::new("two");
    let items = Arc::new(Mutex::new(vec![first.clone()]));
    let source = items.clone();
    let state =
        SearchableState::from_items(move || source.lock().unwrap().clone(), |_item, _term| true);
    let hits = Arc::new(AtomicUsize::new(0));
    let seen = hits.clone();
    let _subscription = state.filtered_changed().subscribe(move |_| {
        seen.fetch_add(1, Ordering::SeqCst);
    });

    items.lock().unwrap().push(second.clone());
    assert_eq!(hits.load(Ordering::SeqCst), 0);

    assert_eq!(
        state
            .search()
            .into_iter()
            .map(|item| item.value)
            .collect::<Vec<_>>(),
        vec!["one", "two"]
    );
    state.dispose();
    drop(state);

    // The helper owns neither the supplier collection nor its items.
    assert_eq!(items.lock().unwrap().len(), 2);
    for item in [&first, &second] {
        assert_eq!(item.dispose_count.load(Ordering::SeqCst), 0);
        assert_ne!(item.vm.status(), vmx::ConstructionStatus::Disposed);
    }
    // Control: the counter is wired to real disposal.
    first.vm.dispose().unwrap();
    assert_eq!(first.dispose_count.load(Ordering::SeqCst), 1);
}
