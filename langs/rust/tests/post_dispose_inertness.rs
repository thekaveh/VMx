//! Composite and group membership and selection after disposal, as the
//! disposal contract's Rust exception states (#1319). Paging calls on a
//! disposed `PagedComposition` are inert (ADR-0214, ADR-0254).

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use vmx::{ComponentVm, CompositeVm, GroupVm, Message, MessageHub, PagedComposition, VmxError};

type Child = ComponentVm<()>;

fn disposed_composite() -> (CompositeVm<Child>, Child, Child) {
    let composite = CompositeVm::new("p");
    let a = Child::new("a");
    let b = Child::new("b");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.construct().unwrap();
    composite.set_current(Some(a.clone())).unwrap();
    composite.dispose().unwrap();
    (composite, a, b)
}

#[test]
fn disposed_composite_refuses_add_remove_and_every_selection() {
    let (composite, a, b) = disposed_composite();

    assert!(matches!(
        composite.add(Child::new("x")),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(composite.remove(&b), Err(VmxError::Disposed)));
    assert!(matches!(
        composite.set_current(Some(b.clone())),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(
        composite.set_current(None),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(
        composite.set_current(Some(a.clone())),
        Err(VmxError::Disposed)
    ));
    assert_eq!(composite.len(), 2);
    assert!(composite.current() == Some(a));
}

#[test]
fn disposed_composite_clear_refuses_and_makes_no_change() {
    let (composite, a, _) = disposed_composite();

    assert!(matches!(composite.clear(), Err(VmxError::Disposed)));

    assert_eq!(composite.len(), 2);
    assert!(composite.current() == Some(a));
}

#[test]
fn disposed_group_refuses_add_remove_and_clear() {
    let group = GroupVm::new("g");
    let a = Child::new("a");
    group.add(a.clone()).unwrap();
    group.construct().unwrap();
    group.dispose().unwrap();

    assert!(matches!(
        group.add(Child::new("x")),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(group.remove(&a), Err(VmxError::Disposed)));
    assert!(matches!(group.clear(), Err(VmxError::Disposed)));
    assert_eq!(group.len(), 1);
}

#[test]
fn disposed_composite_refuses_insert_remove_at_replace_and_move() {
    let (composite, a, b) = disposed_composite();

    assert!(matches!(
        composite.insert(0, Child::new("x")),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(composite.remove_at(1), Err(VmxError::Disposed)));
    assert!(matches!(
        composite.replace(1, Child::new("y")),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(composite.move_item(0, 1), Err(VmxError::Disposed)));
    assert_eq!(composite.len(), 2);
    assert!(composite.get(0) == Some(a.clone()));
    assert!(composite.get(1) == Some(b));
    assert!(composite.current() == Some(a));
}

#[test]
fn disposed_group_refuses_insert_remove_at_replace_and_move() {
    let group = GroupVm::new("g");
    let a = Child::new("a");
    let b = Child::new("b");
    group.add(a.clone()).unwrap();
    group.add(b.clone()).unwrap();
    group.construct().unwrap();
    group.dispose().unwrap();

    assert!(matches!(
        group.insert(0, Child::new("x")),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(group.remove_at(1), Err(VmxError::Disposed)));
    assert!(matches!(
        group.replace(1, Child::new("y")),
        Err(VmxError::Disposed)
    ));
    assert!(matches!(group.move_item(0, 1), Err(VmxError::Disposed)));
    assert_eq!(group.len(), 2);
    assert!(group.get(0) == Some(a));
    assert!(group.get(1) == Some(b));
}

/// The page size, page index, page count and current page of a pager.
fn pager_state(pages: &PagedComposition<i32>) -> (usize, usize, usize, Vec<i32>) {
    (
        pages.page_size(),
        pages.current_page_index(),
        pages.page_count(),
        pages.current_page(),
    )
}

#[test]
fn disposed_pager_paging_calls_change_no_state_and_publish_nothing() {
    let hub = MessageHub::new();
    let pages = PagedComposition::with_hub(vec![1, 2, 3, 4, 5], 2, hub.clone());
    pages.next_page();
    let frozen = pager_state(&pages);
    assert_eq!(frozen, (2, 1, 3, vec![3, 4]));

    let published = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&published);
    let _subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(_)) {
            count.fetch_add(1, Ordering::SeqCst);
        }
    });

    pages.dispose();
    pages.set_page_size(3);
    assert_eq!(pager_state(&pages), frozen, "set_page_size");
    pages.set_current_page_index(0);
    assert_eq!(pager_state(&pages), frozen, "set_current_page_index");
    pages.next_page();
    assert_eq!(pager_state(&pages), frozen, "next_page");
    pages.set_source(vec![9]);
    assert_eq!(pager_state(&pages), frozen, "set_source");
    pages.push(10);
    assert_eq!(pager_state(&pages), frozen, "push");
    assert_eq!(pages.remove_at(0), None, "remove_at");
    assert_eq!(pager_state(&pages), frozen, "remove_at state");

    // The source fills its pages exactly, so one push would add a page. The
    // page count then shows whether the disposed push changed the source.
    let full = PagedComposition::with_hub(vec![1, 2, 3, 4], 2, hub.clone());
    let full_frozen = pager_state(&full);
    assert_eq!(full_frozen, (2, 0, 2, vec![1, 2]));
    full.dispose();
    full.push(5);
    assert_eq!(pager_state(&full), full_frozen, "push adds a page");

    assert_eq!(published.load(Ordering::SeqCst), 0, "nothing is published");
}
