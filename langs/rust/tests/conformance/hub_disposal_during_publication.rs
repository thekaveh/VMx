//! A container whose disposal is requested during a change sends no hub
//! message for it (spec/01 §1.4, spec/06 §4/§4.2/§4.3, spec/07 §1,
//! ADR-0190).

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{
    CollectionChangeAction, ConstructionStatus, Message, MessageHub, MessageRecorder,
    NullDispatcher, ObservableMembershipSource, VmCollection, VmNode,
};

type Child = vmx::ComponentVm<&'static str>;
type Composite = vmx::CompositeVm<Child>;
type Group = vmx::GroupVm<Child>;

fn child(hub: &MessageHub, name: &'static str) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

/// The collection changes and `Count` messages `sender` sent on the hub.
fn hub_changes(recorder: &MessageRecorder, sender: usize) -> Vec<String> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) if change.sender_id == sender => {
                Some(format!("{:?}", change.action))
            }
            Message::PropertyChanged(change)
                if change.sender_id == sender && change.property_name == "Count" =>
            {
                Some("Count".to_string())
            }
            _ => None,
        })
        .collect()
}

/// COMP-049 — a transfer whose old composite disposes itself from
/// `on_current_changed(None)` sends only the new composite's `Add`.
#[test]
fn transfer_from_a_self_disposing_old_composite_sends_only_the_new_add() {
    let hub = MessageHub::new();
    let x = child(&hub, "x");
    let old = Composite::with_services("old", hub.clone(), NullDispatcher::new());
    let new = Composite::with_services("new", hub.clone(), NullDispatcher::new());
    old.add(x.clone()).unwrap();
    old.construct().unwrap();
    old.set_current(Some(x.clone())).unwrap();
    let old_from_callback = old.clone();
    old.on_current_changed(move |current| {
        if current.is_none() {
            old_from_callback.dispose().unwrap();
        }
    });
    let local_events = Arc::new(AtomicUsize::new(0));
    let local_sink = Arc::clone(&local_events);
    let _local = old.subscribe_membership(move || {
        local_sink.fetch_add(1, Ordering::SeqCst);
    });
    let recorder = hub.record(1024);

    new.add(x.clone()).unwrap();

    assert_eq!(hub_changes(&recorder, old.id()), Vec::<String>::new());
    assert_eq!(
        hub_changes(&recorder, new.id()),
        vec![
            format!("{:?}", CollectionChangeAction::Add),
            "Count".to_string()
        ]
    );
    assert_eq!(old.status(), ConstructionStatus::Disposed);
    assert_eq!(local_events.load(Ordering::SeqCst), 1, "old's local Remove");
    assert_eq!(new.items(), vec![x.clone()]);
}

/// Runs `mutate` on `container` with a local subscriber that disposes the
/// container, and checks that the local event arrives and the hub receives
/// nothing from the container.
fn local_subscriber_disposal_suppresses_hub<C>(
    hub: &MessageHub,
    container: C,
    mutate: impl FnOnce(&C),
) where
    C: VmCollection<Child> + ObservableMembershipSource<Child> + VmNode,
{
    let disposer = container.clone();
    let local_events = Arc::new(Mutex::new(0usize));
    let local_sink = Arc::clone(&local_events);
    let _local = container.subscribe_membership(move || {
        *local_sink.lock().unwrap() += 1;
        disposer.dispose().unwrap();
    });
    let recorder = hub.record(1024);

    mutate(&container);

    assert_eq!(*local_events.lock().unwrap(), 1, "local event delivered");
    assert_eq!(hub_changes(&recorder, container.id()), Vec::<String>::new());
    assert_eq!(container.status(), ConstructionStatus::Disposed);
}

/// COMP-049 — a composite `add` whose local subscriber disposes the
/// composite sends no hub message.
#[test]
fn composite_add_with_disposing_local_subscriber_sends_nothing() {
    let hub = MessageHub::new();
    let p = Composite::with_services("p", hub.clone(), NullDispatcher::new());
    let c = child(&hub, "c");
    local_subscriber_disposal_suppresses_hub(&hub, p, |p| p.add(c).unwrap());
}

/// COMP-049 — a composite `move_item` whose local subscriber disposes the
/// composite sends no hub message.
#[test]
fn composite_move_with_disposing_local_subscriber_sends_nothing() {
    let hub = MessageHub::new();
    let p = Composite::with_services("p", hub.clone(), NullDispatcher::new());
    p.add(child(&hub, "first")).unwrap();
    p.add(child(&hub, "second")).unwrap();
    local_subscriber_disposal_suppresses_hub(&hub, p, |p| p.move_item(0, 1).unwrap());
}

/// COMP-049 — a group `add` whose local subscriber disposes the group sends
/// no hub message.
#[test]
fn group_add_with_disposing_local_subscriber_sends_nothing() {
    let hub = MessageHub::new();
    let p = Group::with_services("p", hub.clone(), NullDispatcher::new());
    let c = child(&hub, "c");
    local_subscriber_disposal_suppresses_hub(&hub, p, |p| p.add(c).unwrap());
}

/// COMP-049 — a group `move_item` whose local subscriber disposes the group
/// sends no hub message.
#[test]
fn group_move_with_disposing_local_subscriber_sends_nothing() {
    let hub = MessageHub::new();
    let p = Group::with_services("p", hub.clone(), NullDispatcher::new());
    p.add(child(&hub, "first")).unwrap();
    p.add(child(&hub, "second")).unwrap();
    local_subscriber_disposal_suppresses_hub(&hub, p, |p| p.move_item(0, 1).unwrap());
}
