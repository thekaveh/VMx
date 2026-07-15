use vmx::{ConstructionStatus, Message, MessageHub, NullDispatcher, VmNode, VmxError};

type TextVm = vmx::ComponentVm<&'static str>;
type NumberVm = vmx::ComponentVm<i32>;

fn text(name: &'static str) -> TextVm {
    TextVm::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

fn number(name: &'static str, value: i32) -> NumberVm {
    NumberVm::with_model(name, value, MessageHub::new(), NullDispatcher::new())
}

/// AGG-001 — Arity-1 ComponentN factory invoked on construct
#[test]
fn arity1_constructs_component1() {
    let component = text("one");
    let aggregate = vmx::AggregateVm1::new("aggregate", component.clone());

    aggregate.construct().unwrap();

    assert_eq!(component.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate.component1(), component);
}

/// AGG-002 — Arity-2 both components reach Constructed
#[test]
fn arity2_constructs_heterogeneous_components() {
    let first = text("one");
    let second = number("two", 2);
    let aggregate = vmx::AggregateVm2::new("aggregate", first.clone(), second.clone());

    aggregate.construct().unwrap();

    assert_eq!(aggregate.component1(), first);
    assert_eq!(aggregate.component2(), second);
    assert_eq!(first.status(), ConstructionStatus::Constructed);
    assert_eq!(second.status(), ConstructionStatus::Constructed);
}

/// AGG-003 — Arity-5 all five components reach Constructed before parent
#[test]
fn arity5_constructs_all_components() {
    let a = text("a");
    let b = text("b");
    let c = text("c");
    let d = text("d");
    let e = text("e");
    let aggregate = vmx::AggregateVm5::new(
        "aggregate",
        a.clone(),
        b.clone(),
        c.clone(),
        d.clone(),
        e.clone(),
    );

    aggregate.construct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    assert_eq!(c.status(), ConstructionStatus::Constructed);
    assert_eq!(d.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate.component5(), e);
}

/// AGG-004 — ComponentN property change fires on construct
#[test]
fn component_property_changes_fire_on_construct() {
    let hub = MessageHub::new();
    let aggregate = vmx::AggregateVm2::with_services(
        "aggregate",
        hub.clone(),
        NullDispatcher::new(),
        text("one"),
        number("two", 2),
    );

    aggregate.construct().unwrap();

    let property_names = hub
        .history()
        .into_iter()
        .filter_map(|message| match message {
            Message::PropertyChanged(change) => Some(change.property_name),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert!(property_names.contains(&"component1".to_string()));
    assert!(property_names.contains(&"component2".to_string()));
}

/// AGG-005 — Destruction waits for all children Destructed
#[test]
fn arity2_destructs_all_components() {
    let first = text("one");
    let second = number("two", 2);
    let aggregate = vmx::AggregateVm2::new("aggregate", first.clone(), second.clone());
    aggregate.construct().unwrap();

    aggregate.destruct().unwrap();

    assert_eq!(first.status(), ConstructionStatus::Destructed);
    assert_eq!(second.status(), ConstructionStatus::Destructed);
}

/// AGG-006 — Arity-6 all six components reach Constructed; destruction waits for all
#[test]
fn arity6_constructs_and_destructs_all_components() {
    let a = text("a");
    let b = text("b");
    let c = text("c");
    let d = text("d");
    let e = text("e");
    let f = text("f");
    let aggregate = vmx::AggregateVm6::new(
        "aggregate",
        a.clone(),
        b.clone(),
        c.clone(),
        d.clone(),
        e.clone(),
        f.clone(),
    );

    aggregate.construct().unwrap();
    assert_eq!(f.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate.component6(), f.clone());

    aggregate.destruct().unwrap();
    assert_eq!(a.status(), ConstructionStatus::Destructed);
    assert_eq!(f.status(), ConstructionStatus::Destructed);
}

#[test]
fn arities3_through6_expose_every_slot_and_implement_vm_node() {
    fn assert_vm_node<T: VmNode>(_: &T) {}

    let a = text("a");
    let b = text("b");
    let c = text("c");
    let d = text("d");
    let e = text("e");
    let f = text("f");

    let aggregate3 = vmx::AggregateVm3::new("three", a.clone(), b.clone(), c.clone());
    assert_vm_node(&aggregate3);
    assert_eq!(aggregate3.component1(), a);
    assert_eq!(aggregate3.component2(), b);
    assert_eq!(aggregate3.component3(), c);
    aggregate3.construct().unwrap();
    aggregate3.destruct().unwrap();
    aggregate3.dispose().unwrap();
    assert_eq!(aggregate3.status(), ConstructionStatus::Disposed);

    let aggregate4 = vmx::AggregateVm4::new("four", text("a4"), text("b4"), text("c4"), d.clone());
    assert_vm_node(&aggregate4);
    assert_eq!(aggregate4.component4(), d);
    aggregate4.construct().unwrap();
    aggregate4.destruct().unwrap();
    aggregate4.dispose().unwrap();
    assert_eq!(aggregate4.status(), ConstructionStatus::Disposed);

    let aggregate5 = vmx::AggregateVm5::new(
        "five",
        text("a5"),
        text("b5"),
        text("c5"),
        text("d5"),
        e.clone(),
    );
    assert_vm_node(&aggregate5);
    assert_eq!(aggregate5.component5(), e);
    aggregate5.dispose().unwrap();
    assert_eq!(aggregate5.status(), ConstructionStatus::Disposed);

    let aggregate6 = vmx::AggregateVm6::new(
        "six",
        text("a6"),
        text("b6"),
        text("c6"),
        text("d6"),
        text("e6"),
        f.clone(),
    );
    assert_vm_node(&aggregate6);
    assert_eq!(aggregate6.component6(), f);
    aggregate6.dispose().unwrap();
    assert_eq!(aggregate6.status(), ConstructionStatus::Disposed);
}

#[test]
fn fixed_aggregate_rejects_owned_and_duplicate_components() {
    let child = text("child");
    let old_parent = vmx::CompositeVm::new("old");
    old_parent.add(child.clone()).unwrap();

    assert!(matches!(
        vmx::AggregateVm1::try_new("aggregate", child.clone()),
        Err(VmxError::InconsistentParent)
    ));
    assert_eq!(old_parent.items(), vec![child.clone()]);

    let duplicate = text("duplicate");
    assert!(matches!(
        vmx::AggregateVm2::try_new("aggregate", duplicate.clone(), duplicate),
        Err(VmxError::DuplicateChild)
    ));
}

#[test]
fn fixed_aggregate_component_cannot_transfer_to_mutable_parent() {
    let child = text("child");
    let aggregate = vmx::AggregateVm1::try_new("aggregate", child.clone()).unwrap();
    let destination = vmx::CompositeVm::new("destination");

    assert_eq!(
        destination.add(child.clone()),
        Err(VmxError::InconsistentParent)
    );
    assert!(destination.is_empty());
    assert_eq!(aggregate.component1(), child);
}
