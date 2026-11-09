//! COL-066 — a failing local subscriber does not suppress the hub message.
//!
//! The cases cover the serviced and keyed collections and the multi-key
//! dictionary.
//!
//! The change is committed and exactly one hub `CollectionChangedMessage` is
//! sent. Rust local delivery catches a panicking subscriber, so the mutation
//! returns normally (spec/01-concepts.md §1.4, spec/21-collections.md §2.5,
//! ADR-0171, #1051).
//!
//! COL-069 — the panicking subscriber stays attached and a later local
//! subscriber still receives each change (spec/03-messages.md §3.6, ADR-0191,
//! #1311). The cases cover the serviced and keyed collections and the
//! multi-key dictionary.

use std::sync::{Arc, Mutex};

use vmx::{
    CollectionChangeAction, KeyedServicedObservableCollection, Message, MessageHub,
    ObservableMultiDictionary, ServicedObservableCollection,
};

type Order = Arc<Mutex<Vec<&'static str>>>;

/// Records the external hub's collection actions and appends "hub" to `order`.
fn observe_hub(
    hub: &MessageHub,
    order: &Order,
) -> (Arc<Mutex<Vec<CollectionChangeAction>>>, vmx::Subscription) {
    let actions = Arc::new(Mutex::new(Vec::new()));
    let (sink, order) = (actions.clone(), order.clone());
    let subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            sink.lock().unwrap().push(change.action.clone());
            order.lock().unwrap().push("hub");
        }
    });
    (actions, subscription)
}

/// Subscribes a local subscriber that panics on every delivery.
fn fail_locally(local: &MessageHub, order: &Order) -> vmx::Subscription {
    let order = order.clone();
    local.subscribe(move |_| {
        order.lock().unwrap().push("local");
        panic!("local subscriber failed");
    })
}

const LIST_CASES: [(&str, CollectionChangeAction, &[&str]); 6] = [
    ("push", CollectionChangeAction::Add, &["a", "b", "c"]),
    ("remove_at", CollectionChangeAction::Remove, &["b"]),
    ("replace", CollectionChangeAction::Replace, &["z", "b"]),
    ("move_item", CollectionChangeAction::Move, &["b", "a"]),
    ("clear", CollectionChangeAction::Reset, &[]),
    ("replace_all", CollectionChangeAction::Reset, &["x", "y"]),
];

/// COL-066 — the serviced collection sends one hub message despite a failing local subscriber
#[test]
fn serviced_collection_publishes_once_despite_failing_local_subscriber() {
    for (mutation, action, expected) in LIST_CASES {
        let hub = MessageHub::new();
        let list = ServicedObservableCollection::with_hub(1, hub.clone());
        list.push("a");
        list.push("b");
        let order: Order = Arc::new(Mutex::new(Vec::new()));
        let (actions, _hub) = observe_hub(&hub, &order);
        let _local = fail_locally(&list.collection_changed(), &order);

        match mutation {
            "push" => list.push("c"),
            "remove_at" => drop(list.remove_at(0).unwrap()),
            "replace" => drop(list.replace(0, "z").unwrap()),
            "move_item" => list.move_item(0, 1).unwrap(),
            "clear" => list.clear(),
            _ => list.replace_all(["x", "y"]),
        }

        assert_eq!(list.to_vec(), expected, "{mutation}");
        assert_eq!(*actions.lock().unwrap(), vec![action], "{mutation}");
        assert_eq!(*order.lock().unwrap(), vec!["local", "hub"], "{mutation}");
    }
}

/// COL-066 — the keyed collection sends one hub message despite a failing local subscriber
#[test]
fn keyed_collection_publishes_once_despite_failing_local_subscriber() {
    for (mutation, action, expected) in LIST_CASES {
        let hub = MessageHub::new();
        let list =
            KeyedServicedObservableCollection::with_hub(1, hub.clone(), |item: &&str| Ok(*item));
        list.push("a").unwrap();
        list.push("b").unwrap();
        let order: Order = Arc::new(Mutex::new(Vec::new()));
        let (actions, _hub) = observe_hub(&hub, &order);
        let _local = fail_locally(&list.collection_changed(), &order);

        match mutation {
            "push" => list.push("c").unwrap(),
            "remove_at" => drop(list.remove_at(0).unwrap()),
            "replace" => drop(list.replace(0, "z").unwrap()),
            "move_item" => list.move_item(0, 1).unwrap(),
            "clear" => list.clear(),
            _ => list.replace_all(["x", "y"]).unwrap(),
        }

        assert_eq!(list.to_vec(), expected, "{mutation}");
        for item in expected {
            assert_eq!(list.get_by_key(item), Some(*item), "{mutation}");
        }
        assert_eq!(*actions.lock().unwrap(), vec![action], "{mutation}");
        assert_eq!(*order.lock().unwrap(), vec!["local", "hub"], "{mutation}");
    }
}

/// COL-066 — the multi-key dictionary sends one hub message despite a failing local subscriber
#[test]
fn dictionary_publishes_once_despite_failing_local_subscriber() {
    type Mutation = fn(&ObservableMultiDictionary<&'static str, i32, &'static str>);
    let cases: [(&str, Mutation, CollectionChangeAction, usize); 5] = [
        (
            "add",
            |d| d.add("c", 3, "three").unwrap(),
            CollectionChangeAction::Add,
            3,
        ),
        (
            "insert",
            |d| d.insert("c", 3, "three"),
            CollectionChangeAction::Add,
            3,
        ),
        (
            "replace",
            |d| d.insert("a", 1, "uno"),
            CollectionChangeAction::Replace,
            2,
        ),
        (
            "remove",
            |d| assert_eq!(d.remove(&"a", &1), Some("one")),
            CollectionChangeAction::Remove,
            1,
        ),
        ("clear", |d| d.clear(), CollectionChangeAction::Reset, 0),
    ];
    for (mutation, act, action, count) in cases {
        let hub = MessageHub::new();
        let dictionary = ObservableMultiDictionary::with_hub(1, hub.clone());
        dictionary.add("a", 1, "one").unwrap();
        dictionary.add("b", 2, "two").unwrap();
        let order: Order = Arc::new(Mutex::new(Vec::new()));
        let (actions, _hub) = observe_hub(&hub, &order);
        let _local = fail_locally(&dictionary.collection_changed(), &order);

        act(&dictionary);

        assert_eq!(dictionary.count(), count, "{mutation}");
        assert_eq!(*actions.lock().unwrap(), vec![action], "{mutation}");
        assert_eq!(*order.lock().unwrap(), vec!["local", "hub"], "{mutation}");
    }
}

/// Subscribes A (panics on every delivery) then B on `local`; returns the
/// per-subscriber change counts and keeps both subscriptions alive.
fn record_two(local: &MessageHub) -> (Arc<Mutex<[usize; 2]>>, [vmx::Subscription; 2]) {
    let seen = Arc::new(Mutex::new([0_usize; 2]));
    let (a_seen, b_seen) = (seen.clone(), seen.clone());
    let a = local.subscribe(move |_| {
        a_seen.lock().unwrap()[0] += 1;
        panic!("local subscriber A failed");
    });
    let b = local.subscribe(move |_| b_seen.lock().unwrap()[1] += 1);
    (seen, [a, b])
}

/// COL-069 — a failing local subscriber does not stop the later local subscribers (serviced)
#[test]
fn serviced_collection_failing_local_subscriber_does_not_stop_later_subscriber() {
    let hub = MessageHub::new();
    let list = ServicedObservableCollection::with_hub(1, hub.clone());
    let order: Order = Arc::new(Mutex::new(Vec::new()));
    let (actions, _hub) = observe_hub(&hub, &order);
    let (seen, _local) = record_two(&list.collection_changed());

    list.push("a");
    list.push("b");

    assert_eq!(list.to_vec(), vec!["a", "b"]);
    assert_eq!(*seen.lock().unwrap(), [2, 2]);
    assert_eq!(
        *actions.lock().unwrap(),
        vec![CollectionChangeAction::Add, CollectionChangeAction::Add]
    );
}

/// COL-069 — a failing local subscriber does not stop the later local subscribers (keyed)
#[test]
fn keyed_collection_failing_local_subscriber_does_not_stop_later_subscriber() {
    let hub = MessageHub::new();
    let list = KeyedServicedObservableCollection::with_hub(1, hub.clone(), |item: &&str| Ok(*item));
    let order: Order = Arc::new(Mutex::new(Vec::new()));
    let (actions, _hub) = observe_hub(&hub, &order);
    let (seen, _local) = record_two(&list.collection_changed());

    list.push("a").unwrap();
    list.push("b").unwrap();

    assert_eq!(list.to_vec(), vec!["a", "b"]);
    assert_eq!(*seen.lock().unwrap(), [2, 2]);
    assert_eq!(
        *actions.lock().unwrap(),
        vec![CollectionChangeAction::Add, CollectionChangeAction::Add]
    );
}

/// COL-069 — a failing local subscriber does not stop the later local subscribers (dictionary)
#[test]
fn dictionary_failing_local_subscriber_does_not_stop_later_subscriber() {
    let hub = MessageHub::new();
    let dictionary = ObservableMultiDictionary::with_hub(1, hub.clone());
    let order: Order = Arc::new(Mutex::new(Vec::new()));
    let (actions, _hub) = observe_hub(&hub, &order);
    let (seen, _local) = record_two(&dictionary.collection_changed());

    dictionary.add("a", 1, "one").unwrap();
    dictionary.add("b", 2, "two").unwrap();

    assert_eq!(dictionary.count(), 2);
    assert_eq!(*seen.lock().unwrap(), [2, 2]);
    assert_eq!(
        *actions.lock().unwrap(),
        vec![CollectionChangeAction::Add, CollectionChangeAction::Add]
    );
}
