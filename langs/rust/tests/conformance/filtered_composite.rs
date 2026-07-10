use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use vmx::{ComponentVm, CompositeVm, FilteredCompositeVm, FilteredCursorPolicy};

fn child(model: i32) -> ComponentVm<i32> {
    ComponentVm::with_model(
        "child",
        model,
        vmx::MessageHub::new(),
        vmx::NullDispatcher::new(),
    )
}

fn source_with(values: &[i32]) -> CompositeVm<ComponentVm<i32>> {
    let source = CompositeVm::new("source");
    for value in values {
        source.add(child(*value)).unwrap();
    }
    source
}

/// COMP-028 — FilteredCompositeVM visible projection
#[test]
fn filtered_visible_projection_preserves_source_order() {
    let source = source_with(&[1, 2, 3, 4]);
    let filtered = FilteredCompositeVm::new(source, |vm: &ComponentVm<i32>| vm.model() % 2 == 0);

    let visible = filtered
        .visible()
        .into_iter()
        .map(|vm| vm.model())
        .collect::<Vec<_>>();

    assert_eq!(visible, vec![2, 4]);
}

/// COMP-029 — FilteredCompositeVM visible count
#[test]
fn filtered_visible_count_matches_projection_length() {
    let source = source_with(&[1, 2, 3]);
    let filtered = FilteredCompositeVm::new(source, |vm: &ComponentVm<i32>| vm.model() >= 2);

    assert_eq!(filtered.visible_count(), 2);
}

/// COMP-030 — FilteredCompositeVM current maps to visible domain
#[test]
fn filtered_current_must_be_visible() {
    let source = source_with(&[1, 2]);
    let visible = source.items()[1].clone();
    let hidden = source.items()[0].clone();
    let filtered = FilteredCompositeVm::new(source, |vm: &ComponentVm<i32>| vm.model() == 2);

    filtered.set_current(Some(visible.clone())).unwrap();

    assert_eq!(filtered.current().unwrap().id(), visible.id());
    assert!(filtered.set_current(Some(hidden)).is_err());
}

/// COMP-031 — predicate change recomputes projection
#[test]
fn predicate_change_recomputes_projection() {
    let source = source_with(&[1, 2, 3]);
    let filtered = FilteredCompositeVm::new(source, |vm: &ComponentVm<i32>| vm.model() == 1);

    filtered.set_predicate(|vm: &ComponentVm<i32>| vm.model() >= 2);

    let visible = filtered
        .visible()
        .into_iter()
        .map(|vm| vm.model())
        .collect::<Vec<_>>();
    assert_eq!(visible, vec![2, 3]);
}

/// COMP-032 — source mutation reconciles projection
#[test]
fn source_mutation_recomputes_projection() {
    let source = source_with(&[1]);
    let filtered =
        FilteredCompositeVm::new(source.clone(), |vm: &ComponentVm<i32>| vm.model() >= 2);

    source.add(child(2)).unwrap();

    assert_eq!(filtered.visible()[0].model(), 2);
}

/// COMP-033 — filtered cursor policies
#[test]
fn cursor_policies_clear_or_snap_to_first() {
    let source = source_with(&[1, 2, 3]);
    let filtered =
        FilteredCompositeVm::new(source.clone(), |vm: &ComponentVm<i32>| vm.model() >= 2);
    filtered
        .set_current(Some(source.items()[1].clone()))
        .unwrap();

    filtered.set_cursor_policy(FilteredCursorPolicy::Clear);
    filtered.set_predicate(|vm: &ComponentVm<i32>| vm.model() == 3);
    assert!(filtered.current().is_none());

    filtered
        .set_current(Some(source.items()[2].clone()))
        .unwrap();
    filtered.set_cursor_policy(FilteredCursorPolicy::SnapToFirst);
    filtered.set_predicate(|vm: &ComponentVm<i32>| vm.model() >= 1);
    filtered
        .set_current(Some(source.items()[2].clone()))
        .unwrap();
    filtered.set_predicate(|vm: &ComponentVm<i32>| vm.model() == 1);
    assert_eq!(filtered.current().unwrap().model(), 1);
}

/// COMP-034 — visible navigation
#[test]
fn visible_navigation_clamps_at_bounds() {
    let source = source_with(&[1, 2, 3]);
    let filtered = FilteredCompositeVm::new(source, |vm: &ComponentVm<i32>| vm.model() >= 1);

    filtered.move_next_visible();
    assert_eq!(filtered.current().unwrap().model(), 1);
    filtered.move_next_visible();
    assert_eq!(filtered.current().unwrap().model(), 2);
    filtered.move_previous_visible();
    assert_eq!(filtered.current().unwrap().model(), 1);
}

/// COMP-035 — filtered view disposal
#[test]
fn disposed_filtered_view_freezes_projection() {
    let source = source_with(&[1, 2]);
    let filtered =
        FilteredCompositeVm::new(source.clone(), |vm: &ComponentVm<i32>| vm.model() >= 1);
    filtered.dispose();

    source.add(child(3)).unwrap();

    assert_eq!(filtered.visible_count(), 2);
}

/// DISP-006 — disposable collection/projection helpers perform terminal work once
#[test]
fn repeated_filtered_view_dispose_keeps_one_frozen_projection() {
    let source = source_with(&[1, 2]);
    let filtered =
        FilteredCompositeVm::new(source.clone(), |vm: &ComponentVm<i32>| vm.model() >= 1);
    filtered.dispose();
    filtered.dispose();

    source.add(child(3)).unwrap();
    filtered.set_predicate(|_: &ComponentVm<i32>| true);

    assert_eq!(filtered.visible_count(), 2);
}

/// COMP-036 — scored filter orders by score with stable ties
#[test]
fn scored_filter_orders_by_descending_score_with_stable_ties() {
    let source = source_with(&[1, 2, 3, 4]);
    let scores = HashMap::from([(1, 5), (2, 7), (3, 7)]);
    let filtered = FilteredCompositeVm::scored(source, move |vm: &ComponentVm<i32>| {
        scores.get(&vm.model()).copied()
    });

    let visible = filtered
        .visible()
        .into_iter()
        .map(|vm| vm.model())
        .collect::<Vec<_>>();

    assert_eq!(visible, vec![2, 3, 1]);
}

/// COMP-037 — scored filter can recompute ordering
#[test]
fn scored_filter_can_recompute_ordering() {
    let source = source_with(&[1, 2]);
    let scores = Arc::new(Mutex::new(HashMap::from([(1, 1), (2, 2)])));
    let scores_inner = scores.clone();
    let filtered = FilteredCompositeVm::scored(source, move |vm: &ComponentVm<i32>| {
        scores_inner.lock().unwrap().get(&vm.model()).copied()
    });

    scores.lock().unwrap().insert(1, 3);
    filtered.refresh_scores();

    assert_eq!(filtered.visible()[0].model(), 1);
}
