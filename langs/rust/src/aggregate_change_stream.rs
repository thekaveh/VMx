use super::{
    catch_unwind, lock, resume_unwind, Arc, AssertUnwindSafe, AtomicBool, BTreeMap, ComponentVm,
    CompositeVm, Dispatcher, GroupVm, Hash, HashMap, KeyedServicedObservableCollection, Message,
    Mutex, Ordering, PropertyChangedStream, PropertyChangedSubscription,
    ServicedObservableCollection, Subscription, VecDeque, VmNode, Weak,
};

/// A read-only source of ordered VM membership and structural pulses.
pub trait ObservableMembershipSource<T>: Clone + Send + Sync + 'static
where
    T: VmNode,
{
    /// Returns the source's current ordered membership snapshot.
    fn snapshot(&self) -> Vec<T>;
    /// Subscribes to structural membership changes.
    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static;
}

/// Additive access to a VM's local property-change stream.
pub trait ObservablePropertySource: VmNode {
    /// Returns the VM-local property-change stream.
    fn property_changed(&self) -> PropertyChangedStream;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Identifies why an aggregate change notification was emitted.
pub enum AggregateChangeReason {
    /// Initial emission requested by the subscriber.
    Initial,
    /// The source membership changed.
    Membership,
    /// A current member emitted a property change.
    Item,
    /// One or more changes were coalesced by a batch scope.
    Batch,
}

#[derive(Debug, Clone)]
/// One aggregate notification with an optional originating item.
pub struct AggregateChange<T: VmNode> {
    /// The cause of this notification.
    pub reason: AggregateChangeReason,
    /// The changed member for item notifications.
    pub item: Option<T>,
}

impl<T: VmNode> AggregateChange<T> {
    fn plain(reason: AggregateChangeReason) -> Self {
        Self { reason, item: None }
    }

    fn item(item: T) -> Self {
        Self {
            reason: AggregateChangeReason::Item,
            item: Some(item),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
/// Subscription options for [`AggregateChangeStream::observe`].
pub struct AggregateObserveOptions {
    /// Whether a new subscription receives an immediate initial notification.
    pub emit_initial: bool,
}

impl AggregateObserveOptions {
    /// Sets whether subscriptions emit an initial notification.
    pub fn emit_initial(mut self, value: bool) -> Self {
        self.emit_initial = value;
        self
    }
}

type Handler<T> = Arc<dyn Fn(AggregateChange<T>) + Send + Sync + 'static>;
type Completion = Arc<dyn Fn() + Send + Sync + 'static>;
type EntryHandle<T> = Arc<Mutex<Entry<T>>>;
type RegistrationHandle<T> = Arc<Registration<T>>;

struct Entry<T: VmNode> {
    item: T,
    epoch: u64,
    refcount: usize,
    subscription: Option<PropertyChangedSubscription>,
    admitted: bool,
    terminal: bool,
}

struct Registration<T: VmNode> {
    active: AtomicBool,
    next: Handler<T>,
    complete: Completion,
}

enum Work<T: VmNode> {
    Structural {
        recipients: Vec<RegistrationHandle<T>>,
        coalesced: bool,
    },
    Item {
        entry: EntryHandle<T>,
        epoch: u64,
        recipients: Vec<RegistrationHandle<T>>,
        coalesced: bool,
    },
    Notification {
        change: AggregateChange<T>,
        guard: Option<(EntryHandle<T>, u64)>,
        recipients: Vec<RegistrationHandle<T>>,
    },
    Completion {
        recipients: Vec<RegistrationHandle<T>>,
    },
}

struct Inner<T: VmNode> {
    membership_subscription: Option<Subscription>,
    entries: HashMap<usize, EntryHandle<T>>,
    staged_items: VecDeque<(EntryHandle<T>, u64)>,
    registrations: BTreeMap<usize, RegistrationHandle<T>>,
    batch_recipients: BTreeMap<usize, RegistrationHandle<T>>,
    work: VecDeque<Work<T>>,
    next_registration_id: usize,
    next_epoch: u64,
    structural_version: u64,
    setting_up: bool,
    processing: bool,
    disposed: bool,
    batch_depth: usize,
    batch_dirty: bool,
}

impl<T: VmNode> Default for Inner<T> {
    fn default() -> Self {
        Self {
            membership_subscription: None,
            entries: HashMap::new(),
            staged_items: VecDeque::new(),
            registrations: BTreeMap::new(),
            batch_recipients: BTreeMap::new(),
            work: VecDeque::new(),
            next_registration_id: 0,
            next_epoch: 0,
            structural_version: 0,
            setting_up: true,
            processing: false,
            disposed: false,
            batch_depth: 0,
            batch_dirty: false,
        }
    }
}

struct Shared<T: VmNode> {
    snapshot: Arc<dyn Fn() -> Vec<T> + Send + Sync>,
    observe_item: Arc<dyn Fn(&T) -> PropertyChangedStream + Send + Sync>,
    inner: Mutex<Inner<T>>,
}

/// Dynamic fan-in over one membership source and every current distinct VM.
pub struct AggregateChangeStream<T: VmNode> {
    shared: Arc<Shared<T>>,
}

impl<T: VmNode> AggregateChangeStream<T> {
    /// Creates a fan-in stream from membership and per-item property sources.
    pub fn new<S, F>(source: S, observe_item: F) -> Self
    where
        S: ObservableMembershipSource<T>,
        F: Fn(&T) -> PropertyChangedStream + Send + Sync + 'static,
    {
        let snapshot_source = source.clone();
        let shared = Arc::new(Shared {
            snapshot: Arc::new(move || snapshot_source.snapshot()),
            observe_item: Arc::new(observe_item),
            inner: Mutex::new(Inner::default()),
        });
        let aggregate = Self {
            shared: Arc::clone(&shared),
        };
        let weak = Arc::downgrade(&shared);
        let setup = catch_unwind(AssertUnwindSafe(|| {
            let subscription = source.subscribe_membership(move || {
                if let Some(shared) = weak.upgrade() {
                    Self::membership_changed(&shared);
                }
            });
            lock(&shared.inner).membership_subscription = Some(subscription);
            Self::reconcile(&shared, None, false, true);
        }));
        if let Err(error) = setup {
            aggregate.cleanup_without_completion();
            resume_unwind(error);
        }
        aggregate
    }

    /// Creates a fan-in stream for members exposing their own property stream.
    pub fn for_components<S>(source: S) -> Self
    where
        S: ObservableMembershipSource<T>,
        T: ObservablePropertySource,
    {
        Self::new(source, ObservablePropertySource::property_changed)
    }

    /// Returns an observable view configured with `options`.
    pub fn observe(&self, options: AggregateObserveOptions) -> AggregateChangeObservable<T> {
        AggregateChangeObservable {
            shared: Arc::clone(&self.shared),
            options,
        }
    }

    /// Runs `action` while coalescing all resulting notifications into one batch event.
    pub fn batch<F, R>(&self, action: F) -> R
    where
        F: FnOnce() -> R,
    {
        {
            let mut inner = lock(&self.shared.inner);
            assert!(!inner.disposed, "AggregateChangeStream is no longer active");
            if inner.batch_depth == 0 {
                inner.batch_dirty = false;
                inner.batch_recipients.clear();
            }
            inner.batch_depth += 1;
        }
        let body = catch_unwind(AssertUnwindSafe(action));
        let delivery = catch_unwind(AssertUnwindSafe(|| Self::exit_batch(&self.shared)));
        match body {
            Ok(value) => {
                if let Err(error) = delivery {
                    resume_unwind(error);
                }
                value
            }
            Err(error) => resume_unwind(error),
        }
    }

    /// Detaches membership and item subscriptions and completes observers.
    pub fn dispose(&self) {
        let process = {
            let mut inner = lock(&self.shared.inner);
            if inner.disposed {
                return;
            }
            inner.disposed = true;
            inner.setting_up = false;
            inner.membership_subscription.take();
            let entries = std::mem::take(&mut inner.entries);
            for entry in entries.into_values() {
                let mut entry = lock(&entry);
                entry.admitted = false;
                entry.refcount = 0;
                entry.subscription.take();
            }
            inner.staged_items.clear();
            inner.batch_recipients.clear();
            inner.work.clear();
            let recipients = inner.registrations.values().cloned().collect::<Vec<_>>();
            inner.registrations.clear();
            if !recipients.is_empty() {
                inner.work.push_back(Work::Completion { recipients });
            }
            Self::start_processing(&mut inner)
        };
        if process {
            Self::process_work(&self.shared);
        }
    }

    fn cleanup_without_completion(&self) {
        let mut inner = lock(&self.shared.inner);
        inner.disposed = true;
        inner.membership_subscription.take();
        inner.entries.clear();
        inner.staged_items.clear();
        inner.registrations.clear();
        inner.batch_recipients.clear();
        inner.work.clear();
    }

    fn membership_changed(shared: &Arc<Shared<T>>) {
        let process = {
            let mut inner = lock(&shared.inner);
            inner.structural_version = inner.structural_version.wrapping_add(1);
            if inner.disposed || inner.setting_up {
                return;
            }
            let coalesced = inner.batch_depth > 0;
            if coalesced {
                Self::mark_batch_dirty(&mut inner);
            }
            let recipients = inner.registrations.values().cloned().collect();
            inner.work.push_back(Work::Structural {
                recipients,
                coalesced,
            });
            Self::start_processing(&mut inner)
        };
        if process {
            Self::process_work(shared);
        }
    }

    fn item_changed(shared: &Arc<Shared<T>>, entry: &EntryHandle<T>) {
        let process = {
            let mut inner = lock(&shared.inner);
            if inner.disposed || inner.setting_up {
                return;
            }
            let current = lock(entry);
            if current.terminal {
                return;
            }
            if !current.admitted {
                let epoch = current.epoch;
                drop(current);
                inner.staged_items.push_back((Arc::clone(entry), epoch));
                return;
            }
            let epoch = current.epoch;
            drop(current);
            let coalesced = inner.batch_depth > 0;
            if coalesced {
                Self::mark_batch_dirty(&mut inner);
            }
            let recipients = inner.registrations.values().cloned().collect();
            inner.work.push_back(Work::Item {
                entry: Arc::clone(entry),
                epoch,
                recipients,
                coalesced,
            });
            Self::start_processing(&mut inner)
        };
        if process {
            Self::process_work(shared);
        }
    }

    fn item_completed(shared: &Arc<Shared<T>>, entry: &EntryHandle<T>) {
        let _inner = lock(&shared.inner);
        let mut entry = lock(entry);
        if !entry.terminal {
            entry.terminal = true;
            entry.subscription.take();
        }
    }

    fn process_work(shared: &Arc<Shared<T>>) {
        let mut first_panic = None;
        loop {
            let work = {
                let mut inner = lock(&shared.inner);
                match inner.work.pop_front() {
                    Some(work) => work,
                    None => {
                        inner.processing = false;
                        break;
                    }
                }
            };
            match work {
                Work::Structural {
                    recipients,
                    coalesced,
                } => Self::reconcile(shared, Some(recipients), coalesced, false),
                Work::Item {
                    entry,
                    epoch,
                    recipients,
                    coalesced,
                } => {
                    let valid = Self::entry_is_current(shared, &entry, epoch);
                    if valid && !coalesced {
                        let item = lock(&entry).item.clone();
                        lock(&shared.inner).work.push_front(Work::Notification {
                            change: AggregateChange::item(item),
                            guard: Some((entry, epoch)),
                            recipients,
                        });
                    }
                }
                Work::Notification {
                    change,
                    guard,
                    recipients,
                } => {
                    if guard.as_ref().is_some_and(|(entry, epoch)| {
                        !Self::entry_is_current(shared, entry, *epoch)
                    }) {
                        continue;
                    }
                    let result = catch_unwind(AssertUnwindSafe(|| {
                        Self::deliver_notification(change, &recipients)
                    }));
                    if first_panic.is_none() {
                        first_panic = result.err();
                    }
                }
                Work::Completion { recipients } => {
                    let result =
                        catch_unwind(AssertUnwindSafe(|| Self::deliver_completion(&recipients)));
                    if first_panic.is_none() {
                        first_panic = result.err();
                    }
                }
            }
        }
        if let Some(error) = first_panic {
            resume_unwind(error);
        }
    }

    fn reconcile(
        shared: &Arc<Shared<T>>,
        recipients: Option<Vec<RegistrationHandle<T>>>,
        coalesced: bool,
        initial: bool,
    ) {
        loop {
            let version = {
                let inner = lock(&shared.inner);
                if inner.disposed {
                    return;
                }
                inner.structural_version
            };
            let mut counts = HashMap::<usize, (T, usize)>::new();
            for item in (shared.snapshot)() {
                counts
                    .entry(item.id())
                    .and_modify(|(_, count)| *count += 1)
                    .or_insert((item, 1));
            }
            let missing = {
                let inner = lock(&shared.inner);
                if inner.structural_version != version {
                    continue;
                }
                counts
                    .iter()
                    .filter(|(id, _)| !inner.entries.contains_key(id))
                    .map(|(id, (item, count))| (*id, item.clone(), *count))
                    .collect::<Vec<_>>()
            };
            let mut staged = Vec::with_capacity(missing.len());
            for (id, item, refcount) in missing {
                let epoch = {
                    let mut inner = lock(&shared.inner);
                    inner.next_epoch = inner.next_epoch.wrapping_add(1);
                    inner.next_epoch
                };
                let entry = Arc::new(Mutex::new(Entry {
                    item,
                    epoch,
                    refcount,
                    subscription: None,
                    admitted: false,
                    terminal: false,
                }));
                let selected = (shared.observe_item)(&lock(&entry).item);
                let weak = Arc::downgrade(shared);
                let changed_weak = weak.clone();
                let changed_entry = Arc::downgrade(&entry);
                let completed_entry = Arc::downgrade(&entry);
                let subscription = selected.subscribe_with_completion(
                    move |_| {
                        if let (Some(shared), Some(entry)) =
                            (changed_weak.upgrade(), changed_entry.upgrade())
                        {
                            Self::item_changed(&shared, &entry);
                        }
                    },
                    move || {
                        if let (Some(shared), Some(entry)) =
                            (weak.upgrade(), completed_entry.upgrade())
                        {
                            Self::item_completed(&shared, &entry);
                        }
                    },
                );
                let mut state = lock(&entry);
                if !state.terminal {
                    state.subscription = Some(subscription);
                }
                drop(state);
                staged.push((id, entry));
            }
            let committed = {
                let mut inner = lock(&shared.inner);
                if inner.disposed {
                    return;
                }
                if inner.structural_version != version {
                    false
                } else {
                    let removed = inner
                        .entries
                        .keys()
                        .filter(|id| !counts.contains_key(id))
                        .copied()
                        .collect::<Vec<_>>();
                    for id in removed {
                        if let Some(entry) = inner.entries.remove(&id) {
                            let mut entry = lock(&entry);
                            entry.admitted = false;
                            entry.refcount = 0;
                            entry.subscription.take();
                        }
                    }
                    for (id, (_, refcount)) in &counts {
                        if let Some(entry) = inner.entries.get(id) {
                            lock(entry).refcount = *refcount;
                        }
                    }
                    for (id, entry) in &staged {
                        lock(entry).admitted = true;
                        inner.entries.insert(*id, Arc::clone(entry));
                    }
                    true
                }
            };
            if !committed {
                continue;
            }
            let mut inner = lock(&shared.inner);
            if inner.structural_version != version {
                continue;
            }
            if initial {
                inner.staged_items.clear();
                inner.setting_up = false;
                return;
            }
            let recipients = recipients.clone().unwrap_or_default();
            if coalesced {
                inner.staged_items.clear();
                return;
            }
            let mut notifications = vec![(
                AggregateChange::plain(AggregateChangeReason::Membership),
                None,
            )];
            let staged_items = std::mem::take(&mut inner.staged_items);
            for (entry, epoch) in staged_items {
                let state = lock(&entry);
                if state.admitted && !state.terminal && state.refcount > 0 && state.epoch == epoch {
                    notifications.push((
                        AggregateChange::item(state.item.clone()),
                        Some((Arc::clone(&entry), epoch)),
                    ));
                }
            }
            for (change, guard) in notifications.into_iter().rev() {
                inner.work.push_front(Work::Notification {
                    change,
                    guard,
                    recipients: recipients.clone(),
                });
            }
            return;
        }
    }

    fn entry_is_current(shared: &Arc<Shared<T>>, entry: &EntryHandle<T>, epoch: u64) -> bool {
        let inner = lock(&shared.inner);
        if inner.disposed {
            return false;
        }
        let entry = lock(entry);
        entry.admitted && !entry.terminal && entry.refcount > 0 && entry.epoch == epoch
    }

    fn deliver_notification(change: AggregateChange<T>, recipients: &[RegistrationHandle<T>]) {
        let mut first_panic = None;
        let is_initial = change.reason == AggregateChangeReason::Initial;
        for recipient in recipients {
            if !recipient.active.load(Ordering::SeqCst) {
                continue;
            }
            let result = catch_unwind(AssertUnwindSafe(|| (recipient.next)(change.clone())));
            if result.is_err() && is_initial {
                // A panicking initial callback prevents subscribe() from
                // returning its cancellation handle. Make it immediately
                // ineligible for reentrant work before the drain continues.
                recipient.active.store(false, Ordering::SeqCst);
            }
            if first_panic.is_none() {
                first_panic = result.err();
            }
        }
        if let Some(error) = first_panic {
            resume_unwind(error);
        }
    }

    fn deliver_completion(recipients: &[RegistrationHandle<T>]) {
        let mut first_panic = None;
        for recipient in recipients {
            if !recipient.active.swap(false, Ordering::SeqCst) {
                continue;
            }
            let result = catch_unwind(AssertUnwindSafe(|| (recipient.complete)()));
            if first_panic.is_none() {
                first_panic = result.err();
            }
        }
        if let Some(error) = first_panic {
            resume_unwind(error);
        }
    }

    fn exit_batch(shared: &Arc<Shared<T>>) {
        let process = {
            let mut inner = lock(&shared.inner);
            inner.batch_depth -= 1;
            if inner.batch_depth != 0 || !inner.batch_dirty {
                return;
            }
            inner.batch_dirty = false;
            if inner.disposed {
                return;
            }
            let recipients = std::mem::take(&mut inner.batch_recipients)
                .into_values()
                .collect();
            inner.work.push_back(Work::Notification {
                change: AggregateChange::plain(AggregateChangeReason::Batch),
                guard: None,
                recipients,
            });
            Self::start_processing(&mut inner)
        };
        if process {
            Self::process_work(shared);
        }
    }

    fn start_processing(inner: &mut Inner<T>) -> bool {
        if inner.processing || inner.work.is_empty() {
            false
        } else {
            inner.processing = true;
            true
        }
    }

    fn mark_batch_dirty(inner: &mut Inner<T>) {
        inner.batch_dirty = true;
        let recipients = inner
            .registrations
            .iter()
            .map(|(id, registration)| (*id, Arc::clone(registration)))
            .collect::<Vec<_>>();
        inner.batch_recipients.extend(recipients);
    }
}

/// A configured observable view over an [`AggregateChangeStream`].
pub struct AggregateChangeObservable<T: VmNode> {
    shared: Arc<Shared<T>>,
    options: AggregateObserveOptions,
}

impl<T: VmNode> AggregateChangeObservable<T> {
    /// Subscribes to aggregate changes.
    pub fn subscribe<F>(&self, handler: F) -> AggregateChangeSubscription<T>
    where
        F: Fn(AggregateChange<T>) + Send + Sync + 'static,
    {
        self.subscribe_with_completion(handler, || {})
    }

    /// Subscribes to aggregate changes and terminal completion.
    pub fn subscribe_with_completion<F, C>(
        &self,
        handler: F,
        completion: C,
    ) -> AggregateChangeSubscription<T>
    where
        F: Fn(AggregateChange<T>) + Send + Sync + 'static,
        C: Fn() + Send + Sync + 'static,
    {
        let registration = Arc::new(Registration {
            active: AtomicBool::new(true),
            next: Arc::new(handler),
            complete: Arc::new(completion),
        });
        let (id, process, completed) = {
            let mut inner = lock(&self.shared.inner);
            if inner.disposed {
                (0, false, true)
            } else {
                inner.next_registration_id += 1;
                let id = inner.next_registration_id;
                inner.registrations.insert(id, Arc::clone(&registration));
                if self.options.emit_initial {
                    inner.work.push_back(Work::Notification {
                        change: AggregateChange::plain(AggregateChangeReason::Initial),
                        guard: None,
                        recipients: vec![Arc::clone(&registration)],
                    });
                }
                (
                    id,
                    AggregateChangeStream::start_processing(&mut inner),
                    false,
                )
            }
        };
        if completed {
            registration.active.store(false, Ordering::SeqCst);
            (registration.complete)();
            return AggregateChangeSubscription::noop();
        }
        if process {
            let result = catch_unwind(AssertUnwindSafe(|| {
                AggregateChangeStream::process_work(&self.shared)
            }));
            if let Err(error) = result {
                registration.active.store(false, Ordering::SeqCst);
                lock(&self.shared.inner).registrations.remove(&id);
                resume_unwind(error);
            }
        }
        AggregateChangeSubscription {
            id,
            shared: Arc::downgrade(&self.shared),
            registration: Some(registration),
        }
    }
}

/// A disposable registration on an [`AggregateChangeObservable`].
pub struct AggregateChangeSubscription<T: VmNode> {
    id: usize,
    shared: Weak<Shared<T>>,
    registration: Option<RegistrationHandle<T>>,
}

impl<T: VmNode> AggregateChangeSubscription<T> {
    fn noop() -> Self {
        Self {
            id: 0,
            shared: Weak::new(),
            registration: None,
        }
    }

    /// Detaches this registration; repeated calls are no-ops.
    pub fn dispose(&mut self) {
        let Some(registration) = self.registration.take() else {
            return;
        };
        registration.active.store(false, Ordering::SeqCst);
        if let Some(shared) = self.shared.upgrade() {
            lock(&shared.inner).registrations.remove(&self.id);
        }
    }
}

impl<T: VmNode> Drop for AggregateChangeSubscription<T> {
    fn drop(&mut self) {
        self.dispose();
    }
}

fn membership_message(message: &Message, owner_id: usize) -> bool {
    matches!(message, Message::CollectionChanged(change)
        if change.sender_id == owner_id && change.property_name == "items")
}

impl<T: VmNode, D: Dispatcher> ObservableMembershipSource<T> for CompositeVm<T, D> {
    fn snapshot(&self) -> Vec<T> {
        self.items()
    }

    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static,
    {
        let owner_id = self.id();
        self.hub().subscribe(move |message| {
            if membership_message(message, owner_id) {
                handler();
            }
        })
    }
}

impl<T: VmNode, D: Dispatcher> ObservableMembershipSource<T> for GroupVm<T, D> {
    fn snapshot(&self) -> Vec<T> {
        self.items()
    }

    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static,
    {
        let owner_id = self.id();
        self.hub().subscribe(move |message| {
            if membership_message(message, owner_id) {
                handler();
            }
        })
    }
}

impl<T: VmNode> ObservableMembershipSource<T> for ServicedObservableCollection<T> {
    fn snapshot(&self) -> Vec<T> {
        self.to_vec()
    }

    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static,
    {
        let owner_id = self.owner_id;
        self.collection_changed().subscribe(move |message| {
            if membership_message(message, owner_id) {
                handler();
            }
        })
    }
}

impl<K, T> ObservableMembershipSource<T> for KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + Sync + 'static,
    T: VmNode,
{
    fn snapshot(&self) -> Vec<T> {
        self.to_vec()
    }

    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static,
    {
        let owner_id = self.owner_id;
        self.collection_changed().subscribe(move |message| {
            if membership_message(message, owner_id) {
                handler();
            }
        })
    }
}

impl<M, D> ObservablePropertySource for ComponentVm<M, D>
where
    M: Clone + PartialEq + Send + 'static,
    D: Dispatcher,
{
    fn property_changed(&self) -> PropertyChangedStream {
        ComponentVm::property_changed(self)
    }
}

impl<T: VmNode, D: Dispatcher> ObservablePropertySource for CompositeVm<T, D> {
    fn property_changed(&self) -> PropertyChangedStream {
        CompositeVm::property_changed(self)
    }
}

impl<T: VmNode, D: Dispatcher> ObservablePropertySource for GroupVm<T, D> {
    fn property_changed(&self) -> PropertyChangedStream {
        GroupVm::property_changed(self)
    }
}
