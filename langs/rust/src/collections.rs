//! Observable and serviced collection primitives.
//!
//! Spec: `spec/17-collections-and-paging.md`.

use super::*;

#[derive(Default)]
struct ServicedCollectionDelivery {
    state: Mutex<ServicedCollectionDeliveryState>,
    ready: Condvar,
}

#[derive(Default)]
struct ServicedCollectionDeliveryState {
    pending: VecDeque<Message>,
    draining_owner: Option<ThreadId>,
}

struct ServicedCollectionAdmission {
    delivery: Arc<ServicedCollectionDelivery>,
    current: ThreadId,
    owns_drain: bool,
    armed: bool,
}

impl ServicedCollectionAdmission {
    fn acquire(delivery: Arc<ServicedCollectionDelivery>) -> Self {
        let current = thread::current().id();
        let mut state = lock(&delivery.state);
        while state.draining_owner.is_some_and(|owner| owner != current) {
            state = wait(&delivery.ready, state);
        }
        let owns_drain = state.draining_owner.is_none();
        if owns_drain {
            state.draining_owner = Some(current);
        }
        drop(state);
        Self {
            delivery,
            current,
            owns_drain,
            armed: true,
        }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for ServicedCollectionAdmission {
    fn drop(&mut self) {
        if !self.armed || !self.owns_drain {
            return;
        }
        let mut state = lock(&self.delivery.state);
        if state.draining_owner == Some(self.current) {
            state.draining_owner = None;
        }
        self.delivery.ready.notify_all();
    }
}

/// Hub-aware observable collection with a local change stream.
///
/// Effective mutations update the backing state, publish to the local stream,
/// and then publish the same message to the optional external hub.
#[derive(Clone)]

pub struct ServicedObservableCollection<T>
where
    T: Clone + Send + 'static,
{
    inner: Arc<Mutex<Vec<T>>>,
    local_hub: MessageHub,
    external_hub: Option<MessageHub>,
    delivery: Arc<ServicedCollectionDelivery>,
    pub(crate) owner_id: usize,
}

impl<T> ServicedObservableCollection<T>
where
    T: Clone + Send + 'static,
{
    /// Creates an empty collection without an external message hub.
    pub fn new(owner_id: usize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            local_hub: MessageHub::new(),
            external_hub: None,
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Creates an empty collection that also publishes changes to `hub`.
    pub fn with_hub(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            local_hub: MessageHub::new(),
            external_hub: Some(hub),
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Returns the always-present local collection-change stream.
    pub fn collection_changed(&self) -> MessageHub {
        self.local_hub.clone()
    }

    /// Returns the number of items.
    pub fn len(&self) -> usize {
        lock(&self.inner).len()
    }

    /// Reports whether the collection has no items.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Returns the item at `index`, if present.
    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).get(index).cloned()
    }

    /// Returns an ordered snapshot of all items.
    pub fn to_vec(&self) -> Vec<T> {
        lock(&self.inner).clone()
    }

    /// Appends an item and synchronously publishes an add change.
    pub fn push(&self, item: T) {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let index = {
            let mut inner = lock(&self.inner);
            let index = inner.len();
            inner.push(item);
            index
        };
        self.publish(admission, CollectionChangeAction::Add, None, Some(index));
    }

    /// Removes the first item equal to `item`.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let index = {
            let mut inner = lock(&self.inner);
            let Some(index) = inner.iter().position(|candidate| candidate == item) else {
                return false;
            };
            inner.remove(index);
            index
        };
        self.publish(admission, CollectionChangeAction::Remove, Some(index), None);
        true
    }

    /// Removes and returns the item at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let removed = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            inner.remove(index)
        };
        self.publish(admission, CollectionChangeAction::Remove, Some(index), None);
        Ok(removed)
    }

    /// Replaces and returns the item at `index`.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            std::mem::replace(&mut inner[index], item)
        };
        self.publish(
            admission,
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
        );
        Ok(old)
    }

    /// Atomically replaces the collection from a materialized input snapshot.
    pub fn replace_all<I>(&self, items: I)
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot = items.into_iter().collect::<Vec<_>>();
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        {
            let mut inner = lock(&self.inner);
            if inner.is_empty() && snapshot.is_empty() {
                return;
            }
            *inner = snapshot;
        }
        self.publish(admission, CollectionChangeAction::Reset, None, None);
    }

    /// Moves an item between valid indices and publishes one move change.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.len() || to_index >= inner.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(());
            }
            let item = inner.remove(from_index);
            inner.insert(to_index, item);
        }
        self.publish(
            admission,
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
        );
        Ok(())
    }

    /// Clears a non-empty collection and publishes one reset change.
    pub fn clear(&self) {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        {
            let mut inner = lock(&self.inner);
            if inner.is_empty() {
                return;
            }
            inner.clear();
        }
        self.publish(admission, CollectionChangeAction::Reset, None, None);
    }

    fn publish(
        &self,
        mut admission: ServicedCollectionAdmission,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
    ) {
        let message = Message::CollectionChanged(CollectionChangedMessage {
            sender_id: self.owner_id,
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });

        let current = admission.current;
        let mut delivery = lock(&self.delivery.state);
        debug_assert_eq!(delivery.draining_owner, Some(current));
        delivery.pending.push_back(message);
        if !admission.owns_drain {
            admission.disarm();
            return;
        }
        admission.disarm();
        drop(delivery);

        let result = catch_unwind(AssertUnwindSafe(|| self.drain_delivery(current)));
        if let Err(error) = result {
            let mut delivery = lock(&self.delivery.state);
            delivery.pending.clear();
            if delivery.draining_owner == Some(current) {
                delivery.draining_owner = None;
            }
            self.delivery.ready.notify_all();
            drop(delivery);
            resume_unwind(error);
        }
    }

    fn drain_delivery(&self, current: ThreadId) {
        loop {
            let message = {
                let mut delivery = lock(&self.delivery.state);
                debug_assert_eq!(delivery.draining_owner, Some(current));
                let Some(message) = delivery.pending.pop_front() else {
                    delivery.draining_owner = None;
                    self.delivery.ready.notify_all();
                    return;
                };
                message
            };

            self.local_hub.send(message.clone());
            if let Some(hub) = &self.external_hub {
                hub.send(message);
            }
        }
    }
}

impl<T> IntoIterator for &ServicedObservableCollection<T>
where
    T: Clone + Send + 'static,
{
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.to_vec().into_iter()
    }
}

struct KeyedServicedCollectionState<K, T> {
    items: Vec<T>,
    keys: Vec<Arc<K>>,
    index_by_key: HashMap<Arc<K>, usize>,
}

impl<K, T> Default for KeyedServicedCollectionState<K, T> {
    fn default() -> Self {
        Self {
            items: Vec::new(),
            keys: Vec::new(),
            index_by_key: HashMap::new(),
        }
    }
}

type KeyProjector<K, T> = Arc<dyn Fn(&T) -> VmxResult<K> + Send + Sync + 'static>;

/// An insertion-ordered serviced collection with a captured-key hash index.
///
/// The projector runs only when a membership is added or explicitly replaced.
/// Lookup, removal, and movement use the captured key and never reproject stored
/// items. Contained items remain owned by the caller.
pub struct KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    inner: Arc<Mutex<KeyedServicedCollectionState<K, T>>>,
    key_of: KeyProjector<K, T>,
    local_hub: MessageHub,
    external_hub: Option<MessageHub>,
    delivery: Arc<ServicedCollectionDelivery>,
    pub(crate) owner_id: usize,
}

impl<K, T> Clone for KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            key_of: Arc::clone(&self.key_of),
            local_hub: self.local_hub.clone(),
            external_hub: self.external_hub.clone(),
            delivery: Arc::clone(&self.delivery),
            owner_id: self.owner_id,
        }
    }
}

impl<K, T> KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    /// Creates an empty keyed collection without an external message hub.
    pub fn new<F>(owner_id: usize, key_of: F) -> Self
    where
        F: Fn(&T) -> VmxResult<K> + Send + Sync + 'static,
    {
        Self {
            inner: Arc::new(Mutex::new(KeyedServicedCollectionState::default())),
            key_of: Arc::new(key_of),
            local_hub: MessageHub::new(),
            external_hub: None,
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Creates an empty keyed collection that also publishes changes to `hub`.
    pub fn with_hub<F>(owner_id: usize, hub: MessageHub, key_of: F) -> Self
    where
        F: Fn(&T) -> VmxResult<K> + Send + Sync + 'static,
    {
        Self {
            inner: Arc::new(Mutex::new(KeyedServicedCollectionState::default())),
            key_of: Arc::new(key_of),
            local_hub: MessageHub::new(),
            external_hub: Some(hub),
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Returns the always-present local collection-change stream.
    pub fn collection_changed(&self) -> MessageHub {
        self.local_hub.clone()
    }

    /// Returns the number of keyed memberships.
    pub fn len(&self) -> usize {
        lock(&self.inner).items.len()
    }

    /// Reports whether the keyed collection has no memberships.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Returns the item at `index`, preserving the unkeyed collection's read API.
    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).items.get(index).cloned()
    }

    /// Returns the item whose membership captured `key`.
    pub fn get_by_key(&self, key: &K) -> Option<T> {
        let inner = lock(&self.inner);
        inner
            .index_by_key
            .get(key)
            .and_then(|index| inner.items.get(*index))
            .cloned()
    }

    /// Reports whether `key` identifies a captured membership.
    pub fn contains_key(&self, key: &K) -> bool {
        lock(&self.inner).index_by_key.contains_key(key)
    }

    /// Returns an insertion-ordered item snapshot.
    pub fn to_vec(&self) -> Vec<T> {
        lock(&self.inner).items.clone()
    }

    /// Projects and appends `item`, rejecting duplicate keys atomically.
    pub fn push(&self, item: T) -> VmxResult<()> {
        let key = Arc::new((self.key_of)(&item)?);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let position = {
            let mut inner = lock(&self.inner);
            if inner.index_by_key.contains_key(key.as_ref()) {
                return Err(Self::duplicate_key_error());
            }
            let position = inner.items.len();
            inner.items.push(item);
            inner.keys.push(Arc::clone(&key));
            inner.index_by_key.insert(key, position);
            position
        };
        self.publish(admission, CollectionChangeAction::Add, None, Some(position));
        Ok(())
    }

    /// Removes the first item equal to `item`.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let position = {
            let mut inner = lock(&self.inner);
            let Some(position) = inner.items.iter().position(|candidate| candidate == item) else {
                return false;
            };
            Self::remove_membership(&mut inner, position);
            position
        };
        self.publish(
            admission,
            CollectionChangeAction::Remove,
            Some(position),
            None,
        );
        true
    }

    /// Removes and returns the membership at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let removed = {
            let mut inner = lock(&self.inner);
            if index >= inner.items.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            Self::remove_membership(&mut inner, index)
        };
        self.publish(admission, CollectionChangeAction::Remove, Some(index), None);
        Ok(removed)
    }

    /// Removes and returns the membership captured under `key`.
    pub fn remove_key(&self, key: &K) -> Option<T> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let (position, removed) = {
            let mut inner = lock(&self.inner);
            let position = *inner.index_by_key.get(key)?;
            let removed = Self::remove_membership(&mut inner, position);
            (position, removed)
        };
        self.publish(
            admission,
            CollectionChangeAction::Remove,
            Some(position),
            None,
        );
        Some(removed)
    }

    /// Replaces a membership and its captured key atomically.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let key = Arc::new((self.key_of)(&item)?);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.items.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            if inner
                .index_by_key
                .get(key.as_ref())
                .is_some_and(|owner| *owner != index)
            {
                return Err(Self::duplicate_key_error());
            }
            let old_key = Arc::clone(&inner.keys[index]);
            inner.index_by_key.remove(old_key.as_ref());
            inner.keys[index] = Arc::clone(&key);
            inner.index_by_key.insert(key, index);
            std::mem::replace(&mut inner.items[index], item)
        };
        self.publish(
            admission,
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
        );
        Ok(old)
    }

    /// Preflights keys and atomically replaces every membership.
    pub fn replace_all<I>(&self, items: I) -> VmxResult<()>
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot = items.into_iter().collect::<Vec<_>>();
        let mut keys = Vec::with_capacity(snapshot.len());
        let mut index_by_key = HashMap::with_capacity(snapshot.len());
        for (index, item) in snapshot.iter().enumerate() {
            let key = Arc::new((self.key_of)(item)?);
            if index_by_key.insert(Arc::clone(&key), index).is_some() {
                return Err(Self::duplicate_key_error());
            }
            keys.push(key);
        }
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        {
            let mut inner = lock(&self.inner);
            if inner.items.is_empty() && snapshot.is_empty() {
                return Ok(());
            }
            inner.items = snapshot;
            inner.keys = keys;
            inner.index_by_key = index_by_key;
        }
        self.publish(admission, CollectionChangeAction::Reset, None, None);
        Ok(())
    }

    /// Adds a missing key or replaces the existing membership in place.
    ///
    /// Returns `true` for Add and `false` for Replace.
    pub fn upsert(&self, item: T) -> VmxResult<bool> {
        let key = Arc::new((self.key_of)(&item)?);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let (added, index) = {
            let mut inner = lock(&self.inner);
            if let Some(index) = inner.index_by_key.get(key.as_ref()).copied() {
                let old_key = Arc::clone(&inner.keys[index]);
                inner.index_by_key.remove(old_key.as_ref());
                inner.keys[index] = Arc::clone(&key);
                inner.index_by_key.insert(key, index);
                inner.items[index] = item;
                (false, index)
            } else {
                let index = inner.items.len();
                inner.items.push(item);
                inner.keys.push(Arc::clone(&key));
                inner.index_by_key.insert(key, index);
                (true, index)
            }
        };
        if added {
            self.publish(admission, CollectionChangeAction::Add, None, Some(index));
            Ok(true)
        } else {
            self.publish(
                admission,
                CollectionChangeAction::Replace,
                Some(index),
                Some(index),
            );
            Ok(false)
        }
    }

    /// Moves a membership while preserving and reindexing captured keys.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.items.len() || to_index >= inner.items.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(());
            }
            let item = inner.items.remove(from_index);
            let key = inner.keys.remove(from_index);
            inner.items.insert(to_index, item);
            inner.keys.insert(to_index, key);
            Self::repair_indices(&mut inner, from_index.min(to_index));
        }
        self.publish(
            admission,
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
        );
        Ok(())
    }

    /// Clears every membership and captured key, publishing one reset.
    pub fn clear(&self) {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        {
            let mut inner = lock(&self.inner);
            if inner.items.is_empty() {
                return;
            }
            inner.items.clear();
            inner.keys.clear();
            inner.index_by_key.clear();
        }
        self.publish(admission, CollectionChangeAction::Reset, None, None);
    }

    fn duplicate_key_error() -> VmxError {
        VmxError::InvalidArgument("duplicate key".to_string())
    }

    fn remove_membership(inner: &mut KeyedServicedCollectionState<K, T>, index: usize) -> T {
        let removed = inner.items.remove(index);
        let old_key = inner.keys.remove(index);
        inner.index_by_key.remove(&old_key);
        Self::repair_indices(inner, index);
        removed
    }

    fn repair_indices(inner: &mut KeyedServicedCollectionState<K, T>, start: usize) {
        for index in start..inner.keys.len() {
            inner
                .index_by_key
                .insert(Arc::clone(&inner.keys[index]), index);
        }
    }

    fn publish(
        &self,
        mut admission: ServicedCollectionAdmission,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
    ) {
        let message = Message::CollectionChanged(CollectionChangedMessage {
            sender_id: self.owner_id,
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });

        let current = admission.current;
        let mut delivery = lock(&self.delivery.state);
        debug_assert_eq!(delivery.draining_owner, Some(current));
        delivery.pending.push_back(message);
        if !admission.owns_drain {
            admission.disarm();
            return;
        }
        admission.disarm();
        drop(delivery);

        let result = catch_unwind(AssertUnwindSafe(|| self.drain_delivery(current)));
        if let Err(error) = result {
            let mut delivery = lock(&self.delivery.state);
            delivery.pending.clear();
            if delivery.draining_owner == Some(current) {
                delivery.draining_owner = None;
            }
            self.delivery.ready.notify_all();
            drop(delivery);
            resume_unwind(error);
        }
    }

    fn drain_delivery(&self, current: ThreadId) {
        loop {
            let message = {
                let mut delivery = lock(&self.delivery.state);
                debug_assert_eq!(delivery.draining_owner, Some(current));
                let Some(message) = delivery.pending.pop_front() else {
                    delivery.draining_owner = None;
                    self.delivery.ready.notify_all();
                    return;
                };
                message
            };

            self.local_hub.send(message.clone());
            if let Some(hub) = &self.external_hub {
                hub.send(message);
            }
        }
    }
}

impl<K, T> IntoIterator for &KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.to_vec().into_iter()
    }
}

#[derive(Clone)]
/// An ordered observable list with reset-coalescing batch updates.
///
/// Mutations publish collection messages and publish the spec-literal `Count`
/// property when the effective item count changes.
pub struct ObservableList<T: Clone + Send + 'static> {
    inner: Arc<Mutex<Vec<T>>>,
    hub: MessageHub,
    owner_id: usize,
    batch_depth: Arc<Mutex<usize>>,
    batch_dirty: Arc<Mutex<bool>>,
    batch_count_at_start: Arc<Mutex<usize>>,
}

impl<T: Clone + Send + 'static> ObservableList<T> {
    /// Creates an empty list whose messages use `owner_id`.
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
            batch_depth: Arc::new(Mutex::new(0)),
            batch_dirty: Arc::new(Mutex::new(false)),
            batch_count_at_start: Arc::new(Mutex::new(0)),
        }
    }

    /// Returns the number of items.
    pub fn len(&self) -> usize {
        lock(&self.inner).len()
    }

    /// Reports whether the list has no items.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Returns an ordered snapshot of all items.
    pub fn to_vec(&self) -> Vec<T> {
        lock(&self.inner).clone()
    }

    /// Returns the item at `index`, if present.
    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).get(index).cloned()
    }

    /// Appends an item and publishes add and count changes.
    pub fn push(&self, item: T) {
        let index = {
            let mut inner = lock(&self.inner);
            let index = inner.len();
            inner.push(item);
            index
        };
        self.publish(CollectionChangeAction::Add, None, Some(index), true);
    }

    /// Inserts an item at a valid boundary index.
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let mut inner = lock(&self.inner);
        if index > inner.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        inner.insert(index, item);
        drop(inner);
        self.publish(CollectionChangeAction::Add, None, Some(index), true);
        Ok(())
    }

    /// Removes and returns the item at `index`, if present.
    pub fn remove_at(&self, index: usize) -> Option<T> {
        let item = self.remove_at_silent(index);
        if item.is_some() {
            self.publish(CollectionChangeAction::Remove, Some(index), None, true);
        }
        item
    }

    pub(crate) fn remove_at_silent(&self, index: usize) -> Option<T> {
        let mut inner = lock(&self.inner);
        if index >= inner.len() {
            None
        } else {
            Some(inner.remove(index))
        }
    }

    pub(crate) fn insert_silent(&self, index: usize, item: T) -> VmxResult<()> {
        let mut inner = lock(&self.inner);
        if index > inner.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        inner.insert(index, item);
        Ok(())
    }

    pub(crate) fn publish_remove(&self, index: usize) {
        self.publish(CollectionChangeAction::Remove, Some(index), None, true);
    }

    pub(crate) fn publish_add(&self, index: usize) {
        self.publish(CollectionChangeAction::Add, None, Some(index), true);
    }

    /// Replaces and returns an item without changing the count.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            std::mem::replace(&mut inner[index], item)
        };
        self.publish(
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
            false,
        );
        Ok(old)
    }

    /// Atomically replaces the list from a materialized input snapshot.
    pub fn replace_all<I>(&self, items: I)
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot: Vec<T> = items.into_iter().collect();
        let new_count = snapshot.len();
        let old_count = {
            let mut inner = lock(&self.inner);
            let old_count = inner.len();
            if old_count == 0 && snapshot.is_empty() {
                return;
            }
            *inner = snapshot;
            old_count
        };
        self.publish(
            CollectionChangeAction::Reset,
            None,
            None,
            old_count != new_count,
        );
    }

    pub(crate) fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.len() || to_index >= inner.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(());
            }
            let item = inner.remove(from_index);
            inner.insert(to_index, item);
        }
        self.publish(
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
            false,
        );
        Ok(())
    }

    /// Clears a non-empty list and publishes reset and count changes.
    pub fn clear(&self) {
        let changed = {
            let mut inner = lock(&self.inner);
            let changed = !inner.is_empty();
            inner.clear();
            changed
        };
        if changed {
            self.publish(CollectionChangeAction::Reset, None, None, true);
        }
    }

    /// Runs `action` while coalescing effective changes into one reset.
    ///
    /// Nested batches are supported, and a panic is resumed after batch state
    /// and notifications are finalized.
    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        let mut depth = lock(&self.batch_depth);
        if *depth == 0 {
            *lock(&self.batch_count_at_start) = self.len();
        }
        *depth += 1;
        drop(depth);
        let result = catch_unwind(AssertUnwindSafe(action));
        let mut depth = lock(&self.batch_depth);
        *depth -= 1;
        if *depth == 0 {
            drop(depth);
            let changed = {
                let mut dirty = lock(&self.batch_dirty);
                let changed = *dirty;
                *dirty = false;
                changed
            };
            if changed {
                let count_changed = self.len() != *lock(&self.batch_count_at_start);
                self.publish(CollectionChangeAction::Reset, None, None, count_changed);
            }
        }
        if let Err(error) = result {
            resume_unwind(error);
        }
    }

    fn publish(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
        count_changed: bool,
    ) {
        if *lock(&self.batch_depth) > 0 {
            *lock(&self.batch_dirty) = true;
            return;
        }
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action: action.clone(),
                old_index,
                new_index,
            }));
        if count_changed {
            self.hub
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.owner_id,
                    property_name: "Count".to_string(),
                }));
        }
    }
}

#[derive(Clone)]
/// An insertion-ordered observable key/value dictionary.
pub struct ObservableDictionary<K, V>
where
    K: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    inner: Arc<Mutex<Vec<(K, V)>>>,
    hub: MessageHub,
    owner_id: usize,
}

impl<K, V> ObservableDictionary<K, V>
where
    K: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    /// Creates an empty dictionary whose messages use `owner_id`.
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
        }
    }

    /// Adds `key` or replaces its existing value in place.
    pub fn insert(&self, key: K, value: V) {
        let action = {
            let mut inner = lock(&self.inner);
            if let Some((_, existing)) = inner.iter_mut().find(|(candidate, _)| *candidate == key) {
                *existing = value;
                CollectionChangeAction::Replace
            } else {
                inner.push((key, value));
                CollectionChangeAction::Add
            }
        };
        self.publish(action);
    }

    /// Returns the value associated with `key`, if present.
    pub fn get(&self, key: &K) -> Option<V> {
        lock(&self.inner)
            .iter()
            .find(|(candidate, _)| candidate == key)
            .map(|(_, value)| value.clone())
    }

    /// Removes and returns the value associated with `key`.
    pub fn remove(&self, key: &K) -> Option<V> {
        let removed = {
            let mut inner = lock(&self.inner);
            inner
                .iter()
                .position(|(candidate, _)| candidate == key)
                .map(|index| inner.remove(index).1)
        };
        if removed.is_some() {
            self.publish(CollectionChangeAction::Remove);
        }
        removed
    }

    /// Clears a non-empty dictionary and publishes one reset.
    pub fn clear(&self) {
        let changed = {
            let mut inner = lock(&self.inner);
            let changed = !inner.is_empty();
            inner.clear();
            changed
        };
        if changed {
            self.publish(CollectionChangeAction::Reset);
        }
    }

    /// Returns keys in insertion order.
    pub fn keys(&self) -> Vec<K> {
        lock(&self.inner)
            .iter()
            .map(|(key, _)| key.clone())
            .collect()
    }

    fn publish(&self, action: CollectionChangeAction) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action,
                old_index: None,
                new_index: None,
            }));
    }
}

#[derive(Clone)]
/// An observable dictionary keyed by an ordered pair of keys.
pub struct ObservableMultiDictionary<K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    inner: Arc<Mutex<Vec<(K1, K2, V)>>>,
    hub: MessageHub,
    owner_id: usize,
}

impl<K1, K2, V> ObservableMultiDictionary<K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    /// Creates an empty multi-key dictionary whose messages use `owner_id`.
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
        }
    }

    /// Adds a key pair or replaces its existing value in place.
    pub fn insert(&self, key1: K1, key2: K2, value: V) {
        let action = {
            let mut inner = lock(&self.inner);
            if let Some((_, _, existing)) = inner
                .iter_mut()
                .find(|(candidate1, candidate2, _)| *candidate1 == key1 && *candidate2 == key2)
            {
                *existing = value;
                CollectionChangeAction::Replace
            } else {
                inner.push((key1, key2, value));
                CollectionChangeAction::Add
            }
        };
        self.publish(action);
    }

    /// Removes and returns the value associated with a key pair.
    pub fn remove(&self, key1: &K1, key2: &K2) -> Option<V> {
        let removed = {
            let mut inner = lock(&self.inner);
            inner
                .iter()
                .position(|(candidate1, candidate2, _)| candidate1 == key1 && candidate2 == key2)
                .map(|index| inner.remove(index).2)
        };
        if removed.is_some() {
            self.publish(CollectionChangeAction::Remove);
        }
        removed
    }

    /// Returns the value associated with a key pair, if present.
    pub fn get(&self, key1: &K1, key2: &K2) -> Option<V> {
        lock(&self.inner)
            .iter()
            .find(|(candidate1, candidate2, _)| candidate1 == key1 && candidate2 == key2)
            .map(|(_, _, value)| value.clone())
    }

    /// Reports whether a key pair is present.
    pub fn contains_key(&self, key1: &K1, key2: &K2) -> bool {
        self.get(key1, key2).is_some()
    }

    /// Returns the number of key-pair memberships.
    pub fn count(&self) -> usize {
        lock(&self.inner).len()
    }

    /// Returns distinct first-dimension keys in insertion order.
    pub fn keys1(&self) -> Vec<K1> {
        let mut keys = Vec::new();
        for (key, _, _) in lock(&self.inner).iter() {
            if !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    /// Returns distinct second-dimension keys in insertion order.
    pub fn keys2(&self) -> Vec<K2> {
        let mut keys = Vec::new();
        for (_, key, _) in lock(&self.inner).iter() {
            if !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    fn publish(&self, action: CollectionChangeAction) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action,
                old_index: None,
                new_index: None,
            }));
    }
}
