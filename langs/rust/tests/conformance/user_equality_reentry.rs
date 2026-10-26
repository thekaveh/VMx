//! Regression tests: user `PartialEq` and `Drop` code never runs while a VMx
//! mutex is held, so an `eq` or `drop` that reads its owner returns instead of
//! deadlocking; a retry path taken when `eq` mutates its owner leaves the
//! correct final state; and deterministic notification clocks saturate
//! instead of overflowing.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::RecvTimeoutError;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    ComponentVm, ConfirmationVm, ConstructionStatus, DiscriminatorVm,
    KeyedServicedObservableCollection, Message, MessageHub, NotificationHub, NotificationReaction,
    NotificationType, NotificationVm, NullDispatcher, ObservableDictionary, ObservableList,
    ObservableMultiDictionary, ServicedObservableCollection, TokenPagedComposition, VmNode,
};

/// Runs `body` on a worker and fails if it does not finish in time, so a
/// deadlock regression fails the test instead of hanging the suite. A worker
/// panic is reported as a panic, with its message, not as a deadlock.
fn within_timeout<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(value) => value,
        Err(RecvTimeoutError::Timeout) => {
            panic!("{what} deadlocked: user code ran under an internal lock")
        }
        Err(RecvTimeoutError::Disconnected) => {
            let message = match worker.join() {
                Ok(()) => "worker exited without a result".to_string(),
                Err(payload) => payload
                    .downcast_ref::<&str>()
                    .map(|text| (*text).to_string())
                    .or_else(|| payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "non-string panic payload".to_string()),
            };
            panic!("{what} worker panicked: {message}")
        }
    }
}

type Probe = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

/// A value whose `eq` calls `probe`, which reads the owner it lives in.
#[derive(Clone)]
struct Probing {
    id: u32,
    probe: Probe,
}

impl Probing {
    fn new(id: u32, probe: &Probe) -> Self {
        Self {
            id,
            probe: Arc::clone(probe),
        }
    }
}

impl PartialEq for Probing {
    fn eq(&self, other: &Self) -> bool {
        let probe = self.probe.lock().unwrap().clone();
        if let Some(probe) = probe {
            probe();
        }
        self.id == other.id
    }
}

impl Eq for Probing {}

impl std::hash::Hash for Probing {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

#[test]
fn component_set_model_eq_may_read_the_component() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let vm = ComponentVm::with_model(
        "probing",
        Probing::new(1, &probe),
        MessageHub::new(),
        NullDispatcher::new(),
    );
    let reader = vm.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.model();
    }));
    let (equal, changed) = within_timeout("ComponentVm::set_model", {
        let vm = vm.clone();
        let probe = Arc::clone(&probe);
        move || {
            vm.set_model(Probing::new(1, &probe));
            let equal = vm.model().id;
            vm.set_model(Probing::new(2, &probe));
            (equal, vm.model().id)
        }
    });
    assert_eq!(equal, 1);
    assert_eq!(changed, 2);
    *probe.lock().unwrap() = None;
}

#[test]
fn serviced_collection_remove_eq_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(Probing::new(1, &probe));
    collection.push(Probing::new(2, &probe));
    let reader = collection.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let removed = within_timeout("ServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(2, &probe))
    });
    assert!(removed);
    assert_eq!(
        collection
            .to_vec()
            .iter()
            .map(|item| item.id)
            .collect::<Vec<_>>(),
        [1]
    );
    *probe.lock().unwrap() = None;
}

#[test]
fn serviced_collection_remove_rescans_after_eq_mutates_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(Probing::new(1, &probe));
    collection.push(Probing::new(2, &probe));
    let writer = collection.clone();
    let once = Arc::new(Mutex::new(true));
    *probe.lock().unwrap() = Some(Arc::new(move || {
        if std::mem::take(&mut *once.lock().unwrap()) {
            // Shifts the target, so the index found on the copy is stale.
            let _ = writer.remove_at(0);
        }
    }));
    let removed = within_timeout("ServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(2, &probe))
    });
    assert!(removed);
    assert!(collection.is_empty());
    *probe.lock().unwrap() = None;
}

#[test]
fn keyed_collection_remove_eq_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = KeyedServicedObservableCollection::new(1, |item: &Probing| Ok(item.id));
    collection.push(Probing::new(1, &probe)).unwrap();
    collection.push(Probing::new(2, &probe)).unwrap();
    let reader = collection.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let removed = within_timeout("KeyedServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(1, &probe))
    });
    assert!(removed);
    assert_eq!(collection.len(), 1);
    *probe.lock().unwrap() = None;
}

#[test]
fn dictionary_eq_may_read_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert(Probing::new(1, &probe), "one");
    let reader = dictionary.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.keys();
    }));
    let (value, removed) = within_timeout("ObservableDictionary", {
        let dictionary = dictionary.clone();
        let probe = Arc::clone(&probe);
        move || {
            dictionary.insert(Probing::new(1, &probe), "uno");
            let value = dictionary.get(&Probing::new(1, &probe));
            (value, dictionary.remove(&Probing::new(1, &probe)))
        }
    });
    assert_eq!(value, Some("uno"));
    assert_eq!(removed, Some("uno"));
    assert!(dictionary.keys().is_empty());
    *probe.lock().unwrap() = None;
}

#[test]
fn discriminator_eq_may_read_the_discriminator() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let discriminator = DiscriminatorVm::new(Probing::new(1, &probe));
    let reader = discriminator.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.active_key();
    }));
    let active = within_timeout("DiscriminatorVm::set_active_key", {
        let discriminator = discriminator.clone();
        let probe = Arc::clone(&probe);
        move || {
            discriminator.set_active_key(Probing::new(2, &probe));
            discriminator.is_active(&Probing::new(2, &probe))
        }
    });
    assert!(active);
    *probe.lock().unwrap() = None;
}

#[test]
fn token_paged_refresh_eq_may_read_the_pager() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pages_probe = Arc::clone(&probe);
    let pager = TokenPagedComposition::with_loader(None, move |token: Option<u8>| match token {
        None => (vec![Probing::new(1, &pages_probe)], Some(1)),
        Some(_) => (vec![Probing::new(2, &pages_probe)], None),
    });
    pager.load_next();
    pager.load_next();
    let reader = pager.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.items();
    }));
    let ids = within_timeout("TokenPagedComposition::refresh", {
        let pager = pager.clone();
        move || {
            pager.refresh();
            pager.items().iter().map(|item| item.id).collect::<Vec<_>>()
        }
    });
    // The refreshed page matches the loaded prefix, so the tail is kept.
    assert_eq!(ids, [1, 2]);
    *probe.lock().unwrap() = None;
}

#[test]
fn notification_clock_saturates_instead_of_overflowing() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);

    vm.advance_by_ms(1);
    vm.advance_by_ms(u64::MAX);

    assert_eq!(vm.remaining_time_ms(), 0);
    assert!(vm.is_resolved());
    assert_eq!(hub.reaction(notification.id), NotificationReaction::Approve);
}

#[test]
fn confirmation_clock_saturates_instead_of_overflowing() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Confirmation, "confirm?");
    let vm = ConfirmationVm::with_hub(notification, hub);

    vm.advance_by_ms(1);
    vm.advance_by_ms(u64::MAX);

    assert_eq!(vm.remaining_time_ms(), 0);
    assert_eq!(vm.opacity(), 0.0);
    assert!(!vm.is_resolved(), "an expired confirmation stays pending");
}

/// Returns a probe body that runs `action` on its first call only, so the
/// action's own comparisons do not re-enter it.
fn first_call(action: impl Fn() + Send + Sync + 'static) -> Arc<dyn Fn() + Send + Sync> {
    let armed = AtomicBool::new(true);
    Arc::new(move || {
        if armed.swap(false, Ordering::SeqCst) {
            action();
        }
    })
}

/// A value whose `Drop` calls `hook`, which reads the owner it lives in.
#[derive(Clone)]
struct DropProbing {
    id: u32,
    hook: Probe,
}

impl DropProbing {
    fn new(id: u32, hook: &Probe) -> Self {
        Self {
            id,
            hook: Arc::clone(hook),
        }
    }
}

impl PartialEq for DropProbing {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl Drop for DropProbing {
    fn drop(&mut self) {
        let hook = self.hook.lock().unwrap().clone();
        if let Some(hook) = hook {
            hook();
        }
    }
}

#[test]
fn discriminator_clear_modals_drop_may_read_the_discriminator() {
    let hook: Probe = Arc::new(Mutex::new(None));
    let discriminator = DiscriminatorVm::new(DropProbing::new(0, &hook));
    discriminator.modal_open(DropProbing::new(1, &hook));
    discriminator.modal_open(DropProbing::new(2, &hook));
    let reader = discriminator.clone();
    *hook.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.modal_depth();
    }));
    let (depth, active) = within_timeout("DiscriminatorVm::clear_modals", {
        let discriminator = discriminator.clone();
        move || {
            discriminator.clear_modals();
            (discriminator.modal_depth(), discriminator.active_key().id)
        }
    });
    *hook.lock().unwrap() = None;
    assert_eq!((depth, active), (0, 2));
}

#[test]
fn discriminator_dispose_drop_may_read_the_discriminator() {
    let hook: Probe = Arc::new(Mutex::new(None));
    let discriminator = DiscriminatorVm::new(DropProbing::new(0, &hook));
    discriminator.modal_open(DropProbing::new(1, &hook));
    let reader = discriminator.clone();
    *hook.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.modal_depth();
    }));
    let depth = within_timeout("DiscriminatorVm::dispose", {
        let discriminator = discriminator.clone();
        move || {
            discriminator.dispose();
            discriminator.modal_depth()
        }
    });
    *hook.lock().unwrap() = None;
    assert_eq!(depth, 0);
}

fn serviced_change_count(
    collection: &ServicedObservableCollection<DropProbing>,
) -> Arc<Mutex<usize>> {
    let resets = Arc::new(Mutex::new(0));
    let sink = Arc::clone(&resets);
    let subscription = collection.collection_changed().subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(_)) {
            *sink.lock().unwrap() += 1;
        }
    });
    std::mem::forget(subscription);
    resets
}

#[test]
fn serviced_collection_clear_and_replace_all_drop_may_read_the_collection() {
    let hook: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(DropProbing::new(1, &hook));
    collection.push(DropProbing::new(2, &hook));
    let changes = serviced_change_count(&collection);
    let reader = collection.clone();
    *hook.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let lengths = within_timeout("ServicedObservableCollection::clear/replace_all", {
        let collection = collection.clone();
        let hook = Arc::clone(&hook);
        move || {
            collection.replace_all([DropProbing::new(3, &hook)]);
            let replaced = collection.len();
            collection.clear();
            (replaced, collection.len())
        }
    });
    *hook.lock().unwrap() = None;
    assert_eq!(lengths, (1, 0));
    assert_eq!(*changes.lock().unwrap(), 2);
}

#[test]
fn keyed_collection_clear_replace_all_and_upsert_drop_may_read_the_collection() {
    let hook: Probe = Arc::new(Mutex::new(None));
    let collection = KeyedServicedObservableCollection::new(1, |item: &DropProbing| Ok(item.id));
    collection.push(DropProbing::new(1, &hook)).unwrap();
    collection.push(DropProbing::new(2, &hook)).unwrap();
    let reader = collection.clone();
    *hook.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let lengths = within_timeout("KeyedServicedObservableCollection::clear/replace_all", {
        let collection = collection.clone();
        let hook = Arc::clone(&hook);
        move || {
            let added = collection.upsert(DropProbing::new(2, &hook)).unwrap();
            collection
                .replace_all([DropProbing::new(3, &hook)])
                .unwrap();
            let replaced = collection.len();
            collection.clear();
            (added, replaced, collection.len())
        }
    });
    *hook.lock().unwrap() = None;
    assert_eq!(lengths, (false, 1, 0));
}

#[test]
fn observable_list_clear_and_replace_all_drop_may_read_the_list() {
    let hook: Probe = Arc::new(Mutex::new(None));
    let list = ObservableList::new(1, MessageHub::new());
    list.push(DropProbing::new(1, &hook));
    let reader = list.clone();
    *hook.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let lengths = within_timeout("ObservableList::clear/replace_all", {
        let list = list.clone();
        let hook = Arc::clone(&hook);
        move || {
            list.replace_all([DropProbing::new(2, &hook)]);
            let replaced = list.len();
            list.clear();
            (replaced, list.len())
        }
    });
    *hook.lock().unwrap() = None;
    assert_eq!(lengths, (1, 0));
}

#[test]
fn keyed_collection_remove_rescans_after_eq_mutates_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = KeyedServicedObservableCollection::new(1, |item: &Probing| Ok(item.id));
    collection.push(Probing::new(1, &probe)).unwrap();
    collection.push(Probing::new(2, &probe)).unwrap();
    let writer = collection.clone();
    // Shifts the target, so the index found on the copy is stale.
    *probe.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove_at(0);
    }));
    let removed = within_timeout("KeyedServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(2, &probe))
    });
    *probe.lock().unwrap() = None;
    assert!(removed);
    assert!(collection.is_empty());
}

/// A dictionary holding keys 1 and 2 whose next comparison removes key 1,
/// which makes the index found for key 2 on the copy stale.
fn shifting_dictionary(probe: &Probe) -> ObservableDictionary<Probing, &'static str> {
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert(Probing::new(1, probe), "one");
    dictionary.insert(Probing::new(2, probe), "two");
    let writer = dictionary.clone();
    let doomed = Probing::new(1, probe);
    *probe.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove(&doomed);
    }));
    dictionary
}

fn dictionary_ids(dictionary: &ObservableDictionary<Probing, &'static str>) -> Vec<u32> {
    dictionary.keys().iter().map(|key| key.id).collect()
}

#[test]
fn dictionary_insert_retries_after_eq_mutates_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let dictionary = shifting_dictionary(&probe);
    within_timeout("ObservableDictionary::insert", {
        let dictionary = dictionary.clone();
        let probe = Arc::clone(&probe);
        move || dictionary.insert(Probing::new(2, &probe), "deux")
    });
    *probe.lock().unwrap() = None;
    assert_eq!(dictionary_ids(&dictionary), [2]);
    assert_eq!(dictionary.get(&Probing::new(2, &probe)), Some("deux"));
}

#[test]
fn dictionary_get_retries_after_eq_mutates_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let dictionary = shifting_dictionary(&probe);
    let value = within_timeout("ObservableDictionary::get", {
        let dictionary = dictionary.clone();
        let probe = Arc::clone(&probe);
        move || dictionary.get(&Probing::new(2, &probe))
    });
    *probe.lock().unwrap() = None;
    assert_eq!(value, Some("two"));
    assert_eq!(dictionary_ids(&dictionary), [2]);
}

/// The multi-key analogue of [`shifting_dictionary`].
fn shifting_multi_dictionary(
    probe: &Probe,
) -> ObservableMultiDictionary<Probing, u8, &'static str> {
    let dictionary = ObservableMultiDictionary::new(1, MessageHub::new());
    dictionary.insert(Probing::new(1, probe), 0, "one");
    dictionary.insert(Probing::new(2, probe), 0, "two");
    let writer = dictionary.clone();
    let doomed = Probing::new(1, probe);
    *probe.lock().unwrap() = Some(first_call(move || {
        let _ = writer.remove(&doomed, &0);
    }));
    dictionary
}

#[test]
fn multi_dictionary_insert_retries_after_eq_mutates_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let dictionary = shifting_multi_dictionary(&probe);
    within_timeout("ObservableMultiDictionary::insert", {
        let dictionary = dictionary.clone();
        let probe = Arc::clone(&probe);
        move || dictionary.insert(Probing::new(2, &probe), 0, "deux")
    });
    *probe.lock().unwrap() = None;
    assert_eq!(dictionary.count(), 1);
    assert_eq!(dictionary.get(&Probing::new(2, &probe), &0), Some("deux"));
}

#[test]
fn multi_dictionary_get_retries_after_eq_mutates_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let dictionary = shifting_multi_dictionary(&probe);
    let value = within_timeout("ObservableMultiDictionary::get", {
        let dictionary = dictionary.clone();
        let probe = Arc::clone(&probe);
        move || dictionary.get(&Probing::new(2, &probe), &0)
    });
    *probe.lock().unwrap() = None;
    assert_eq!(value, Some("two"));
    assert_eq!(dictionary.count(), 1);
}

#[test]
fn component_set_model_rechecks_after_eq_installs_the_same_model() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model(
        "probing",
        Probing::new(1, &probe),
        hub.clone(),
        NullDispatcher::new(),
    );
    let changes = Arc::new(Mutex::new(0));
    let _subscription = hub.subscribe({
        let changes = Arc::clone(&changes);
        move |message| {
            if matches!(message, Message::PropertyChanged(change) if change.property_name == "model")
            {
                *changes.lock().unwrap() += 1;
            }
        }
    });
    let writer = vm.clone();
    let same = Probing::new(2, &probe);
    // Installs the incoming model first, so the outer assignment is equal.
    *probe.lock().unwrap() = Some(first_call(move || writer.set_model(same.clone())));
    let id = within_timeout("ComponentVm::set_model", {
        let vm = vm.clone();
        let probe = Arc::clone(&probe);
        move || {
            vm.set_model(Probing::new(2, &probe));
            vm.model().id
        }
    });
    *probe.lock().unwrap() = None;
    assert_eq!(id, 2);
    assert_eq!(
        *changes.lock().unwrap(),
        1,
        "the equal outer assignment is inert"
    );
}

#[test]
fn discriminator_set_active_key_rechecks_after_eq_installs_the_same_key() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let discriminator = DiscriminatorVm::new(Probing::new(1, &probe));
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _subscription = discriminator.active_key_changes().subscribe({
        let seen = Arc::clone(&seen);
        move |key: Probing| seen.lock().unwrap().push(key.id)
    });
    let writer = discriminator.clone();
    let same = Probing::new(2, &probe);
    // Activates the incoming key first, so the outer assignment is equal.
    *probe.lock().unwrap() = Some(first_call(move || writer.set_active_key(same.clone())));
    let active = within_timeout("DiscriminatorVm::set_active_key", {
        let discriminator = discriminator.clone();
        let probe = Arc::clone(&probe);
        move || {
            discriminator.set_active_key(Probing::new(2, &probe));
            discriminator.active_key().id
        }
    });
    *probe.lock().unwrap() = None;
    assert_eq!(active, 2);
    assert_eq!(
        *seen.lock().unwrap(),
        [2],
        "the equal outer assignment is inert"
    );
}

/// A pager holding pages `[1]` and `[2]` whose refresh loads `[3]`; the
/// refresh plan's first comparison appends `[9]` through an ad hoc load,
/// which supersedes the refresh.
fn superseded_refresh_pager(probe: &Probe) -> TokenPagedComposition<Probing, u8> {
    let refreshing = Arc::new(AtomicBool::new(false));
    let pages_probe = Arc::clone(probe);
    let pager = TokenPagedComposition::with_loader(None, {
        let refreshing = Arc::clone(&refreshing);
        move |token: Option<u8>| match token {
            None if refreshing.load(Ordering::SeqCst) => {
                (vec![Probing::new(3, &pages_probe)], None)
            }
            None => (vec![Probing::new(1, &pages_probe)], Some(1)),
            Some(_) => (vec![Probing::new(2, &pages_probe)], None),
        }
    });
    pager.load_next();
    pager.load_next();
    refreshing.store(true, Ordering::SeqCst);
    let writer = pager.clone();
    let appended = Probing::new(9, probe);
    *probe.lock().unwrap() = Some(first_call(move || {
        let appended = appended.clone();
        writer.load_more(move |_| (vec![appended], None));
    }));
    pager
}

#[test]
fn token_paged_refresh_yields_to_an_operation_started_by_eq() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pager = superseded_refresh_pager(&probe);
    let ids = within_timeout("TokenPagedComposition::refresh", {
        let pager = pager.clone();
        move || {
            pager.refresh();
            pager.items().iter().map(|item| item.id).collect::<Vec<_>>()
        }
    });
    *probe.lock().unwrap() = None;
    // The ad hoc load started after the refresh, so the refresh is stale.
    assert_eq!(ids, [1, 2, 9]);
}

/// A VM node whose `eq` calls `probe`.
#[derive(Clone)]
struct ProbingNode(Probing);

impl PartialEq for ProbingNode {
    fn eq(&self, other: &Self) -> bool {
        self.0 == other.0
    }
}

impl VmNode for ProbingNode {
    fn id(&self) -> usize {
        self.0.id as usize
    }

    fn construct(&self) -> vmx::VmxResult<()> {
        Ok(())
    }

    fn destruct(&self) -> vmx::VmxResult<()> {
        Ok(())
    }

    fn dispose(&self) -> vmx::VmxResult<()> {
        Ok(())
    }

    fn status(&self) -> ConstructionStatus {
        ConstructionStatus::Constructed
    }

    fn set_parent_id(&self, _parent_id: Option<usize>) {}

    fn parent_id(&self) -> Option<usize> {
        None
    }
}

#[test]
fn auto_construct_token_paged_refresh_yields_to_an_operation_started_by_eq() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let refreshing = Arc::new(AtomicBool::new(false));
    let pages_probe = Arc::clone(&probe);
    let node = move |id| ProbingNode(Probing::new(id, &pages_probe));
    let pager = TokenPagedComposition::with_auto_construct_loader(None, {
        let refreshing = Arc::clone(&refreshing);
        move |token: Option<u8>| match token {
            None if refreshing.load(Ordering::SeqCst) => (vec![node(3)], None),
            None => (vec![node(1)], Some(1)),
            Some(_) => (vec![node(2)], None),
        }
    });
    pager.load_next();
    pager.load_next();
    refreshing.store(true, Ordering::SeqCst);
    let writer = pager.clone();
    let appended = ProbingNode(Probing::new(9, &probe));
    *probe.lock().unwrap() = Some(first_call(move || {
        let appended = appended.clone();
        writer.load_more(move |_| (vec![appended], None));
    }));
    let ids = within_timeout("TokenPagedComposition::refresh (auto-construct)", {
        let pager = pager.clone();
        move || {
            pager.refresh();
            pager.items().iter().map(VmNode::id).collect::<Vec<_>>()
        }
    });
    *probe.lock().unwrap() = None;
    assert_eq!(ids, [1, 2, 9]);
}

fn custom(name: &str) -> Message {
    Message::Custom {
        sender_id: 1,
        sender_name: "sender".to_string(),
        name: name.to_string(),
    }
}

/// Subscribes an outer handler whose closure owns the only reference to an
/// inner subscription on the same hub, so releasing the outer handler drops
/// the inner subscription.
fn nested_hub_subscriptions(hub: &MessageHub) -> vmx::Subscription {
    let inner = hub.subscribe(|_| {});
    hub.subscribe(move |_| {
        let _ = &inner;
    })
}

#[test]
fn hub_subscription_dispose_may_drop_a_subscription_on_the_same_hub() {
    within_timeout("Subscription::dispose", || {
        let hub = MessageHub::new();
        let outer = nested_hub_subscriptions(&hub);
        outer.dispose();
        hub.send(custom("after"));
    });
}

#[test]
fn hub_subscription_drop_may_drop_a_subscription_on_the_same_hub() {
    within_timeout("Subscription drop", || {
        let hub = MessageHub::new();
        drop(nested_hub_subscriptions(&hub));
        hub.send(custom("after"));
    });
}

#[test]
fn hub_dispose_may_drop_a_subscription_on_the_same_hub() {
    within_timeout("MessageHub::dispose", || {
        let hub = MessageHub::new();
        let _outer = nested_hub_subscriptions(&hub);
        hub.dispose();
    });
}

#[test]
fn hub_dispose_during_delivery_may_drop_a_subscription_on_the_same_hub() {
    within_timeout("MessageHub::dispose during delivery", || {
        let hub = MessageHub::new();
        let _outer = nested_hub_subscriptions(&hub);
        let disposer = hub.clone();
        let _trigger = hub.subscribe(move |_| disposer.dispose());
        hub.send(custom("dispose"));
    });
}

#[test]
fn value_stream_teardown_may_drop_a_subscription_on_the_same_stream() {
    within_timeout("ValueStream dispose", || {
        let stream = vmx::ValueStream::hot(0_u8);
        let nested = |stream: &vmx::ValueStream<u8>| {
            let inner = stream.subscribe(|_| {});
            stream.subscribe(move |_| {
                let _ = &inner;
            })
        };
        nested(&stream).dispose();
        drop(nested(&stream));
        let _outer = nested(&stream);
        stream.dispose();
    });
}

#[test]
fn hub_skips_a_subscriber_disposed_by_an_earlier_subscriber_of_the_same_message() {
    let hub = MessageHub::new();
    let log = Arc::new(Mutex::new(Vec::<String>::new()));
    let target = Arc::new(Mutex::new(None::<vmx::Subscription>));
    let _a = hub.subscribe({
        let log = Arc::clone(&log);
        let target = Arc::clone(&target);
        move |message| {
            if let Message::Custom { name, .. } = message {
                log.lock().unwrap().push(format!("A:{name}"));
            }
            if let Some(b) = target.lock().unwrap().as_ref() {
                b.dispose();
            }
        }
    });
    let b = hub.subscribe({
        let log = Arc::clone(&log);
        move |message| {
            if let Message::Custom { name, .. } = message {
                log.lock().unwrap().push(format!("B:{name}"));
            }
        }
    });
    *target.lock().unwrap() = Some(b);
    hub.send(custom("1"));
    hub.send(custom("2"));
    assert_eq!(*log.lock().unwrap(), ["A:1", "A:2"]);
}

#[test]
fn hub_self_disposing_subscriber_finishes_its_message_and_later_ones_still_run() {
    let hub = MessageHub::new();
    let log = Arc::new(Mutex::new(Vec::<String>::new()));
    let own = Arc::new(Mutex::new(None::<vmx::Subscription>));
    let a = hub.subscribe({
        let log = Arc::clone(&log);
        let own = Arc::clone(&own);
        move |message| {
            if let Some(me) = own.lock().unwrap().as_ref() {
                me.dispose();
            }
            if let Message::Custom { name, .. } = message {
                log.lock().unwrap().push(format!("A:{name}"));
            }
        }
    });
    *own.lock().unwrap() = Some(a);
    let _b = hub.subscribe({
        let log = Arc::clone(&log);
        move |message| {
            if let Message::Custom { name, .. } = message {
                log.lock().unwrap().push(format!("B:{name}"));
            }
        }
    });
    hub.send(custom("1"));
    hub.send(custom("2"));
    assert_eq!(*log.lock().unwrap(), ["A:1", "B:1", "B:2"]);
}

/// Records the action of every collection-changed message on `hub`.
fn record_actions(hub: &MessageHub) -> (Arc<Mutex<Vec<String>>>, vmx::Subscription) {
    let actions = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&actions);
    let subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            sink.lock().unwrap().push(format!("{:?}", change.action));
        }
    });
    (actions, subscription)
}

/// #747 — a `remove` that finds no match still delivers the change its `eq`
/// made before it returns.
#[test]
fn serviced_collection_remove_without_a_match_delivers_the_eq_change() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(Probing::new(1, &probe));
    collection.push(Probing::new(2, &probe));
    let (actions, _subscription) = record_actions(&collection.collection_changed());
    let writer = collection.clone();
    let once = Arc::new(Mutex::new(true));
    *probe.lock().unwrap() = Some(Arc::new(move || {
        if std::mem::take(&mut *once.lock().unwrap()) {
            let _ = writer.remove_at(0);
        }
    }));

    let removed = within_timeout("ServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(9, &probe))
    });

    assert!(!removed);
    assert_eq!(
        *actions.lock().unwrap(),
        ["Remove"],
        "the eq change is delivered"
    );
    *probe.lock().unwrap() = None;
}

/// #747 — the same for `KeyedServicedObservableCollection::remove`.
#[test]
fn keyed_serviced_collection_remove_without_a_match_delivers_the_eq_change() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = KeyedServicedObservableCollection::new(1, |item: &Probing| Ok(item.id));
    collection.push(Probing::new(1, &probe)).unwrap();
    collection.push(Probing::new(2, &probe)).unwrap();
    let (actions, _subscription) = record_actions(&collection.collection_changed());
    let writer = collection.clone();
    let once = Arc::new(Mutex::new(true));
    *probe.lock().unwrap() = Some(Arc::new(move || {
        if std::mem::take(&mut *once.lock().unwrap()) {
            let _ = writer.remove_at(0);
        }
    }));

    let removed = within_timeout("KeyedServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(9, &probe))
    });

    assert!(!removed);
    assert_eq!(
        *actions.lock().unwrap(),
        ["Remove"],
        "the eq change is delivered"
    );
    *probe.lock().unwrap() = None;
}
