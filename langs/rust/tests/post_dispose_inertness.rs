//! Composite and group membership and selection after disposal, as the
//! disposal contract's Rust exception states (#1319).

use vmx::{ComponentVm, CompositeVm, GroupVm, VmxError};

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
