use std::sync::{Arc, Mutex};

use vmx::SearchableState;

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
    let state = SearchableState::new(vec![1, 2, 3, 4], |item, term| {
        term == "even" && item % 2 == 0
    });
    state.set_search_term("even");

    assert_eq!(state.filtered(), vec![2, 4]);
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
    let state = SearchableState::new(vec!["a", "bbb"], |item, term| item.len() == term.len());
    state.set_search_term("xx");

    assert_eq!(state.filtered(), Vec::<&str>::new());
}
