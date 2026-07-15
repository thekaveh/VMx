use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

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
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    let expected = component.clone();
    let aggregate = vmx::AggregateVm1::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || {
            observed.fetch_add(1, Ordering::SeqCst);
            expected.clone()
        })
        .build()
        .unwrap();

    assert_eq!(aggregate.component_1(), None);
    assert_eq!(calls.load(Ordering::SeqCst), 0);

    aggregate.construct().unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(component.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate.component_1(), Some(component));
}

/// AGG-002 — Arity-2 both components reach Constructed
#[test]
fn arity2_constructs_heterogeneous_components() {
    let first = text("one");
    let second = number("two", 2);
    let first_factory = first.clone();
    let second_factory = second.clone();
    let aggregate = vmx::AggregateVm2::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || first_factory.clone())
        .component_2(move || second_factory.clone())
        .build()
        .unwrap();

    assert_eq!(aggregate.component_1(), None);
    assert_eq!(aggregate.component_2(), None);

    aggregate.construct().unwrap();

    assert_eq!(aggregate.component_1(), Some(first.clone()));
    assert_eq!(aggregate.component_2(), Some(second.clone()));
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
    let (fa, fb, fc, fd, fe) = (a.clone(), b.clone(), c.clone(), d.clone(), e.clone());
    let aggregate = vmx::AggregateVm5::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || fa.clone())
        .component_2(move || fb.clone())
        .component_3(move || fc.clone())
        .component_4(move || fd.clone())
        .component_5(move || fe.clone())
        .build()
        .unwrap();

    aggregate.construct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    assert_eq!(c.status(), ConstructionStatus::Constructed);
    assert_eq!(d.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate.component_5(), Some(e));
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
    assert!(property_names.contains(&"component_1".to_string()));
    assert!(property_names.contains(&"component_2".to_string()));
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
    let (fa, fb, fc, fd, fe, ff) = (
        a.clone(),
        b.clone(),
        c.clone(),
        d.clone(),
        e.clone(),
        f.clone(),
    );
    let aggregate = vmx::AggregateVm6::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || fa.clone())
        .component_2(move || fb.clone())
        .component_3(move || fc.clone())
        .component_4(move || fd.clone())
        .component_5(move || fe.clone())
        .component_6(move || ff.clone())
        .build()
        .unwrap();

    aggregate.construct().unwrap();
    assert_eq!(f.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate.component_6(), Some(f.clone()));

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

    let (a3, b3, c3) = (a.clone(), b.clone(), c.clone());
    let aggregate3 = vmx::AggregateVm3::builder()
        .name("three")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || a3.clone())
        .component_2(move || b3.clone())
        .component_3(move || c3.clone())
        .build()
        .unwrap();
    assert_vm_node(&aggregate3);
    assert_eq!(aggregate3.component_1(), None);
    aggregate3.construct().unwrap();
    assert_eq!(aggregate3.component_1(), Some(a));
    assert_eq!(aggregate3.component_2(), Some(b));
    assert_eq!(aggregate3.component_3(), Some(c));
    aggregate3.destruct().unwrap();
    aggregate3.dispose().unwrap();
    assert_eq!(aggregate3.status(), ConstructionStatus::Disposed);

    let (a4, b4, c4, d4) = (text("a4"), text("b4"), text("c4"), d.clone());
    let (fa4, fb4, fc4, fd4) = (a4.clone(), b4.clone(), c4.clone(), d4.clone());
    let aggregate4 = vmx::AggregateVm4::builder()
        .name("four")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || fa4.clone())
        .component_2(move || fb4.clone())
        .component_3(move || fc4.clone())
        .component_4(move || fd4.clone())
        .build()
        .unwrap();
    assert_vm_node(&aggregate4);
    assert_eq!(aggregate4.component_4(), None);
    aggregate4.construct().unwrap();
    assert_eq!(aggregate4.component_4(), Some(d4));
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
    assert_eq!(aggregate5.component_5(), Some(e));
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
    assert_eq!(aggregate6.component_6(), Some(f));
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
    assert_eq!(aggregate.component_1(), Some(child));
}

#[test]
fn builders_require_every_field_and_remain_independent_when_cloned() {
    let first = text("first");
    let second = number("second", 2);
    let first_factory = first.clone();
    let second_factory = second.clone();
    let base = vmx::AggregateVm2::<TextVm, NumberVm>::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new());
    let missing_second = base.clone().component_1(move || first_factory.clone());

    assert!(matches!(
        missing_second.clone().build(),
        Err(VmxError::BuilderValidation(message)) if message == "component_2 is required"
    ));
    assert!(matches!(
        base.build(),
        Err(VmxError::BuilderValidation(message)) if message == "component_1 is required"
    ));

    let aggregate = missing_second
        .component_2(move || second_factory.clone())
        .build()
        .unwrap();
    assert_eq!(aggregate.name(), "aggregate");
    assert_eq!(aggregate.hint(), Some(String::new()));
}

#[test]
fn reconstruct_reinvokes_factories_and_disposes_replaced_slots() {
    type GeneratedVm = vmx::ComponentVm<usize>;

    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    let aggregate = vmx::AggregateVm1::<GeneratedVm>::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || {
            let generation = observed.fetch_add(1, Ordering::SeqCst) + 1;
            GeneratedVm::with_model(
                "generated",
                generation,
                MessageHub::new(),
                NullDispatcher::new(),
            )
        })
        .build()
        .unwrap();

    aggregate.construct().unwrap();
    let first = aggregate.component_1().unwrap();
    assert_eq!(first.model(), 1);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(aggregate.status(), ConstructionStatus::Constructed);
    aggregate.construct().unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(aggregate.component_1().unwrap().id(), first.id());

    aggregate.reconstruct().unwrap();
    let second = aggregate.component_1().unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_ne!(first.id(), second.id());
    assert_eq!(first.status(), ConstructionStatus::Disposed);
    assert_eq!(second.model(), 2);
    assert_eq!(second.status(), ConstructionStatus::Constructed);
    assert!(aggregate.is_constructed());

    aggregate.dispose().unwrap();
    assert_eq!(aggregate.construct(), Err(VmxError::Disposed));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn failed_reconstruction_preserves_all_previous_slots_and_parent_links() {
    let first = text("first");
    let second = text("second");
    let replacement = text("replacement");
    let foreign = text("foreign");
    let foreign_parent = vmx::CompositeVm::new("foreign-parent");
    foreign_parent.add(foreign.clone()).unwrap();

    let first_calls = Arc::new(AtomicUsize::new(0));
    let second_calls = Arc::new(AtomicUsize::new(0));
    let observed_first = Arc::clone(&first_calls);
    let observed_second = Arc::clone(&second_calls);
    let original_first = first.clone();
    let original_second = second.clone();
    let next_first = replacement.clone();
    let invalid_second = foreign.clone();
    let aggregate = vmx::AggregateVm2::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || {
            if observed_first.fetch_add(1, Ordering::SeqCst) == 0 {
                original_first.clone()
            } else {
                next_first.clone()
            }
        })
        .component_2(move || {
            if observed_second.fetch_add(1, Ordering::SeqCst) == 0 {
                original_second.clone()
            } else {
                invalid_second.clone()
            }
        })
        .build()
        .unwrap();
    aggregate.construct().unwrap();

    assert_eq!(aggregate.reconstruct(), Err(VmxError::InconsistentParent));

    assert_eq!(aggregate.component_1(), Some(first.clone()));
    assert_eq!(aggregate.component_2(), Some(second.clone()));
    assert_eq!(first.parent_id(), Some(aggregate.id()));
    assert_eq!(second.parent_id(), Some(aggregate.id()));
    assert_eq!(replacement.parent_id(), None);
    assert_eq!(foreign.parent_id(), Some(foreign_parent.id()));
}
