//! `PagedComposition` property notifications and composite source
//! observation (spec/21-collections.md §5.2 and §5.5, ADR-0208, #1269).
//!
//! The names and their order follow Swift, in snake_case. A call that leaves
//! the state unchanged publishes nothing. `set_source`, `push` and a
//! removing `remove_at` publish `page_count`, then `current_page_index` when
//! the index clamps, then `items`.

use std::sync::{Arc, Mutex};

use vmx::{
    ComponentVm, CompositeVm, Message, MessageHub, NullDispatcher, PagedComposition, Subscription,
};

type Names = Arc<Mutex<Vec<String>>>;

/// Records the property names that `sender` publishes on `hub`.
fn names(hub: &MessageHub, sender: usize) -> (Names, Subscription) {
    let names: Names = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&names);
    let subscription = hub.subscribe(move |message| {
        if let Message::PropertyChanged(change) = message {
            if change.sender_id == sender {
                sink.lock().unwrap().push(change.property_name.clone());
            }
        }
    });
    (names, subscription)
}

fn take(names: &Names) -> Vec<String> {
    std::mem::take(&mut *names.lock().unwrap())
}

const SIZE_CHANGE: [&str; 5] = [
    "page_size",
    "is_paging_enabled",
    "page_count",
    "current_page_index",
    "items",
];
const MOVE: [&str; 2] = ["current_page_index", "items"];
const SOURCE: [&str; 2] = ["page_count", "items"];
const CLAMPED_SOURCE: [&str; 3] = ["page_count", "current_page_index", "items"];

/// COL-016 — a new page size publishes every paging property; the same size publishes nothing
#[test]
fn page_size_change_publishes_every_paging_property() {
    let pages = PagedComposition::new((1..=6).collect::<Vec<_>>(), 2);
    let (seen, _subscription) = names(&pages.hub(), pages.id());

    pages.set_page_size(2);
    assert!(take(&seen).is_empty());

    pages.move_to_last_page();
    take(&seen);
    pages.set_page_size(3);
    assert_eq!(take(&seen), SIZE_CHANGE);
    assert_eq!(pages.current_page_index(), 1, "clamped from 2");

    pages.set_page_size(0);
    assert_eq!(take(&seen), SIZE_CHANGE);
    assert!(!pages.is_paging_enabled());
}

/// COL-018 — navigation publishes the index and items only when the index changes
#[test]
fn navigation_publishes_only_an_index_change() {
    let pages = PagedComposition::new((1..=6).collect::<Vec<_>>(), 2);
    let (seen, _subscription) = names(&pages.hub(), pages.id());

    pages.move_to_first_page();
    pages.move_to_previous_page();
    pages.previous_page();
    pages.set_current_page_index(0);
    assert!(take(&seen).is_empty(), "the index stayed at 0");

    pages.move_to_next_page();
    assert_eq!(take(&seen), MOVE);
    pages.next_page();
    assert_eq!(take(&seen), MOVE);
    pages.move_to_next_page();
    pages.move_to_last_page();
    pages.set_current_page_index(99);
    assert!(take(&seen).is_empty(), "the index stayed at the last page");

    pages.move_to_previous_page();
    assert_eq!(take(&seen), MOVE);
    pages.set_current_page_index(0);
    assert_eq!(take(&seen), MOVE);
    pages.move_to_last_page();
    assert_eq!(take(&seen), MOVE);
    pages.move_to_first_page();
    assert_eq!(take(&seen), MOVE);
    assert_eq!(pages.current_page(), vec![1, 2]);
}

/// COL-017 — source changes publish the page count, a clamped index, and the items
#[test]
fn source_changes_publish_count_clamp_and_items() {
    let hub = MessageHub::new();
    let pages = PagedComposition::with_hub((1..=4).collect::<Vec<_>>(), 2, hub.clone());
    let (seen, _subscription) = names(&hub, pages.id());

    pages.push(5);
    assert_eq!(take(&seen), SOURCE);

    pages.move_to_last_page();
    take(&seen);
    assert_eq!(pages.remove_at(4), Some(5));
    assert_eq!(take(&seen), CLAMPED_SOURCE);
    assert_eq!(pages.current_page_index(), 1);

    assert_eq!(pages.remove_at(9), None);
    assert!(take(&seen).is_empty(), "a missing index changes nothing");

    pages.set_source(vec![1, 2, 3, 4, 5, 6]);
    assert_eq!(take(&seen), SOURCE);
    pages.set_source(vec![1]);
    assert_eq!(take(&seen), CLAMPED_SOURCE);
    assert_eq!(pages.page_count(), 1);
    assert_eq!(pages.current_page(), vec![1]);
}

type Child = ComponentVm<&'static str>;

fn child(hub: &MessageHub, name: &'static str) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

/// COL-031 — a pager over a composite follows its children and stops after dispose
#[test]
fn pager_follows_a_composite_source_until_disposed() {
    let hub = MessageHub::new();
    let source: CompositeVm<Child> =
        CompositeVm::with_services("notes", hub.clone(), NullDispatcher::new());
    let [a, b, c, d] = ["a", "b", "c", "d"].map(|name| child(&hub, name));
    source.add(a.clone()).unwrap();
    let pages = PagedComposition::from_composite(&source, 2);
    let (seen, _subscription) = names(&pages.hub(), pages.id());
    assert_eq!(pages.current_page(), vec![a.clone()]);

    source.add(b.clone()).unwrap();
    source.add(c.clone()).unwrap();
    assert_eq!(take(&seen), [SOURCE, SOURCE].concat());
    assert_eq!(pages.page_count(), 2);
    assert_eq!(pages.current_page(), vec![a.clone(), b.clone()]);

    pages.move_to_last_page();
    take(&seen);
    assert_eq!(pages.current_page(), vec![c.clone()]);
    source.remove(&c).unwrap();
    assert_eq!(take(&seen), CLAMPED_SOURCE);
    assert_eq!(pages.page_count(), 1);
    assert_eq!(pages.current_page(), vec![a.clone(), b.clone()]);

    source.insert(0, d.clone()).unwrap();
    assert_eq!(take(&seen), SOURCE);
    assert_eq!(pages.current_page(), vec![d.clone(), a.clone()]);

    pages.dispose();
    pages.dispose();
    source.clear().unwrap();
    pages.set_page_size(1);
    pages.push(c);
    assert!(take(&seen).is_empty(), "nothing is published after dispose");
    assert_eq!(
        pages.page_count(),
        4,
        "the pager no longer follows the composite"
    );
}

/// COL-031 — the pager stays usable after its composite source is dropped
#[test]
fn pager_outlives_its_composite_source() {
    let hub = MessageHub::new();
    let source: CompositeVm<Child> =
        CompositeVm::with_services("notes", hub.clone(), NullDispatcher::new());
    source.add(child(&hub, "a")).unwrap();
    let pages = PagedComposition::from_composite(&source, 2);
    drop(source);

    assert_eq!(pages.page_count(), 1);
    pages.push(child(&hub, "b"));
    pages.push(child(&hub, "c"));
    assert_eq!(pages.page_count(), 2);
}
