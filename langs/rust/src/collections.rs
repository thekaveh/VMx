//! Observable and serviced collection primitives.
//!
//! Spec: `spec/21-collections.md`.

use super::{
    catch_unwind, lock, resume_unwind, thread, wait, Arc, AssertUnwindSafe, AtomicBool,
    CollectionChangeAction, CollectionChangedMessage, Condvar, Hash, HashMap, Message, MessageHub,
    Mutex, Ordering, PropertyChangedMessage, ThreadId, VecDeque, VmxError, VmxResult,
};
use crate::clone_locked;
use std::collections::hash_map::RandomState;
use std::hash::BuildHasher;

/// A copy-on-write vector shared with lock-free readers.
///
/// A reader clones the `Arc` under the owner's lock, releases the lock, and
/// runs user `PartialEq` against the snapshot (#765). A writer mutates in
/// place when no snapshot is outstanding, and otherwise copies.
type Shared<T> = Arc<Vec<T>>;

/// A displaced snapshot that a writer must drop after releasing its lock.
type Retired<T> = Option<Shared<T>>;

/// Returns `shared` for mutation, copying it first when a reader still holds
/// a snapshot. The displaced `Arc` goes to `retired`, never dropped here: a
/// reader may release its snapshot meanwhile, which makes the displaced
/// `Arc` the last reference, and its items must not drop under the lock.
fn cow_mut<'a, T: Clone>(shared: &'a mut Shared<T>, retired: &mut Retired<T>) -> &'a mut Vec<T> {
    if Arc::get_mut(shared).is_none() {
        let copy = Arc::new(Vec::clone(shared));
        let displaced = std::mem::replace(shared, copy);
        debug_assert!(retired.is_none(), "one copy per write");
        *retired = Some(displaced);
    }
    // Snapshots are only taken under the owner's lock, which the caller
    // holds, so neither the unshared original nor a fresh copy can gain a
    // reader before this returns.
    Arc::get_mut(shared).expect("an unshared snapshot is unique")
}

/// Runs `publish` for a committed change, then drops what the change
/// displaced, with no lock held (#1295).
///
/// A removed or replaced item's `Drop` is user code. It runs only after the
/// change has reached the local stream and the hub, so a panicking `Drop`
/// cannot suppress the change (spec/21 §2.5). When `publish` itself panics,
/// the displaced values drop before that panic resumes, so they never drop
/// while a panic unwinds.
fn publish_then_drop<D>(displaced: D, publish: impl FnOnce()) {
    let published = catch_unwind(AssertUnwindSafe(publish));
    drop(displaced);
    if let Err(panic) = published {
        resume_unwind(panic);
    }
}

#[derive(Default)]
struct ServicedCollectionDelivery {
    state: Mutex<ServicedCollectionDeliveryState>,
    ready: Condvar,
}

#[derive(Default)]
struct ServicedCollectionDeliveryState {
    pending: VecDeque<Message>,
    draining_owner: Option<ThreadId>,
    /// Counts published changes. Every effective mutation publishes, so a
    /// caller that compared items on a copy detects an intervening change.
    revision: u64,
}

impl ServicedCollectionDelivery {
    fn revision(&self) -> u64 {
        lock(&self.state).revision
    }
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
    /// Releases a drain that was not handed to `publish` or `finish`. If user
    /// code under the admission panicked, the messages its nested mutations
    /// queued are discarded. A subscriber panic does the same, so a later
    /// mutation never delivers them late (#1065).
    fn drop(&mut self) {
        if !self.armed || !self.owns_drain {
            return;
        }
        let mut state = lock(&self.delivery.state);
        if thread::panicking() {
            state.pending.clear();
        }
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
    inner: Arc<Mutex<Shared<T>>>,
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
            inner: Arc::new(Mutex::new(Shared::default())),
            local_hub: MessageHub::new(),
            external_hub: None,
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Creates an empty collection that also publishes changes to `hub`.
    pub fn with_hub(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Shared::default())),
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
        Vec::clone(&lock(&self.inner))
    }

    /// Appends an item and synchronously publishes an add change.
    pub fn push(&self, item: T) {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let mut retired = None;
        let index = {
            let mut inner = lock(&self.inner);
            let items = cow_mut(&mut inner, &mut retired);
            items.push(item);
            items.len() - 1
        };
        publish_then_drop(retired, || {
            self.publish(admission, CollectionChangeAction::Add, None, Some(index));
        });
    }

    /// Removes the first item equal to `item`.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        // `PartialEq` runs on a shared snapshot, with no lock held; the
        // admission keeps other threads out, and the revision check catches a
        // change that `eq` itself made, after which the search runs again.
        // The snapshot is released before the lock is retaken, so the write
        // below does not copy, and a snapshot that a nested write displaced
        // drops its items with no lock held.
        loop {
            let revision = self.delivery.revision();
            let snapshot = Arc::clone(&lock(&self.inner));
            let found = snapshot.iter().position(|candidate| candidate == item);
            drop(snapshot);
            let Some(index) = found else {
                self.finish(admission);
                return false;
            };
            let mut retired = None;
            let removed = {
                let mut inner = lock(&self.inner);
                if self.delivery.revision() != revision {
                    continue;
                }
                cow_mut(&mut inner, &mut retired).remove(index)
            };
            // The removed item drops after the change is published (#1295).
            publish_then_drop((removed, retired), || {
                self.publish(admission, CollectionChangeAction::Remove, Some(index), None);
            });
            return true;
        }
    }

    /// Removes and returns the item at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let mut retired = None;
        let removed = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            cow_mut(&mut inner, &mut retired).remove(index)
        };
        publish_then_drop(retired, || {
            self.publish(admission, CollectionChangeAction::Remove, Some(index), None);
        });
        Ok(removed)
    }

    /// Replaces and returns the item at `index`.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let mut retired = None;
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            std::mem::replace(&mut cow_mut(&mut inner, &mut retired)[index], item)
        };
        publish_then_drop(retired, || {
            self.publish(
                admission,
                CollectionChangeAction::Replace,
                Some(index),
                Some(index),
            );
        });
        Ok(old)
    }

    /// Atomically replaces the collection from a materialized input snapshot.
    pub fn replace_all<I>(&self, items: I)
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot = items.into_iter().collect::<Vec<_>>();
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        // Old items are dropped after the reset is published, with no lock
        // held: a user `Drop` may read this collection or panic (#1295).
        let previous = {
            let mut inner = lock(&self.inner);
            if inner.is_empty() && snapshot.is_empty() {
                return;
            }
            std::mem::replace(&mut *inner, Arc::new(snapshot))
        };
        publish_then_drop(previous, || {
            self.publish(admission, CollectionChangeAction::Reset, None, None);
        });
    }

    /// Moves an item between valid indices and publishes one move change.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let mut retired = None;
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
            let items = cow_mut(&mut inner, &mut retired);
            let item = items.remove(from_index);
            items.insert(to_index, item);
        }
        publish_then_drop(retired, || {
            self.publish(
                admission,
                CollectionChangeAction::Move,
                Some(from_index),
                Some(to_index),
            );
        });
        Ok(())
    }

    /// Clears a non-empty collection and publishes one reset change.
    pub fn clear(&self) {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let previous = {
            let mut inner = lock(&self.inner);
            if inner.is_empty() {
                return;
            }
            std::mem::take(&mut *inner)
        };
        // The items drop after the reset is published (#1295).
        publish_then_drop(previous, || {
            self.publish(admission, CollectionChangeAction::Reset, None, None);
        });
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
            sender_name: "ServicedObservableCollection".to_string(),
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });

        let current = admission.current;
        let mut delivery = lock(&self.delivery.state);
        debug_assert_eq!(delivery.draining_owner, Some(current));
        delivery.pending.push_back(message);
        delivery.revision = delivery.revision.wrapping_add(1);
        if !admission.owns_drain {
            admission.disarm();
            return;
        }
        admission.disarm();
        drop(delivery);
        self.drain_as_owner(current);
    }

    /// Ends an admission that published nothing. When it owns the drain, a
    /// nested mutation from user `PartialEq` may have queued messages
    /// meanwhile; they are delivered before the drain is released (#747).
    fn finish(&self, mut admission: ServicedCollectionAdmission) {
        admission.disarm();
        if admission.owns_drain {
            self.drain_as_owner(admission.current);
        }
    }

    /// Delivers every pending message as the drain owner, then releases the
    /// drain. A panicking subscriber clears the queue and re-raises.
    fn drain_as_owner(&self, current: ThreadId) {
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

/// A captured key and the hash it had when its membership was added.
///
/// The index finds memberships by this stored hash, so the lock-held index
/// work compares only `u64` values and `Arc` pointers. `K::hash` and `K::eq`
/// run with no lock held (#1276).
struct CapturedKey<K> {
    hash: u64,
    key: Arc<K>,
}

impl<K> Clone for CapturedKey<K> {
    fn clone(&self) -> Self {
        Self {
            hash: self.hash,
            key: Arc::clone(&self.key),
        }
    }
}

/// The memberships whose captured keys share one hash: each captured key and
/// its position.
type KeyBucket<K> = Vec<(Arc<K>, usize)>;

struct KeyedServicedCollectionState<K, T> {
    items: Shared<T>,
    keys: Vec<CapturedKey<K>>,
    index_by_hash: HashMap<u64, KeyBucket<K>>,
}

impl<K, T> Default for KeyedServicedCollectionState<K, T> {
    fn default() -> Self {
        Self {
            items: Shared::default(),
            keys: Vec::new(),
            index_by_hash: HashMap::new(),
        }
    }
}

impl<K, T> KeyedServicedCollectionState<K, T> {
    /// Returns the memberships whose captured key has `hash`. Copying the
    /// bucket clones `Arc`s only, so no user code runs.
    fn candidates(&self, hash: u64) -> KeyBucket<K> {
        self.index_by_hash.get(&hash).cloned().unwrap_or_default()
    }

    /// Records `key` at `position` in the index. No user code runs.
    fn index_key(&mut self, key: &CapturedKey<K>, position: usize) {
        self.index_by_hash
            .entry(key.hash)
            .or_default()
            .push((Arc::clone(&key.key), position));
    }

    /// Removes `key` from the index by pointer identity. No user code runs.
    fn unindex_key(&mut self, key: &CapturedKey<K>) {
        if let Some(bucket) = self.index_by_hash.get_mut(&key.hash) {
            bucket.retain(|(candidate, _)| !Arc::ptr_eq(candidate, &key.key));
            if bucket.is_empty() {
                self.index_by_hash.remove(&key.hash);
            }
        }
    }

    /// Stores the current position of every key from `start` on. No user code
    /// runs.
    fn repair_positions(&mut self, start: usize) {
        for position in start..self.keys.len() {
            let key = &self.keys[position];
            if let Some(entry) = self.index_by_hash.get_mut(&key.hash).and_then(|bucket| {
                bucket
                    .iter_mut()
                    .find(|(candidate, _)| Arc::ptr_eq(candidate, &key.key))
            }) {
                entry.1 = position;
            }
        }
    }
}

/// Returns the position of the first candidate whose key equals `key`. It
/// runs user `K::eq`, so callers hold no lock.
fn find_key<K: Eq>(candidates: &KeyBucket<K>, key: &K) -> Option<usize> {
    candidates
        .iter()
        .find(|(candidate, _)| candidate.as_ref() == key)
        .map(|(_, position)| *position)
}

type KeyProjector<K, T> = Arc<dyn Fn(&T) -> VmxResult<K> + Send + Sync + 'static>;

/// An insertion-ordered serviced collection with a captured-key hash index.
///
/// The projector runs only when a membership is added or explicitly replaced.
/// Lookup, removal, and movement use the captured key and never reproject stored
/// items. Contained items remain owned by the caller.
///
/// User `K::hash` and `K::eq` code runs with no collection lock held, so a key
/// may read this collection, for example through [`len`](Self::len), during
/// any lookup or write (#1276). The collection hashes each key once, when
/// its membership is added, and finds memberships by that stored hash. A
/// write that user key code makes to this collection on the same thread is
/// detected, and the outer operation then searches again.
pub struct KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    inner: Arc<Mutex<KeyedServicedCollectionState<K, T>>>,
    key_of: KeyProjector<K, T>,
    hasher: RandomState,
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
            hasher: self.hasher.clone(),
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
            hasher: RandomState::new(),
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
            hasher: RandomState::new(),
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

    /// Hashes `key` with no lock held. `K::hash` is user code.
    fn hash_of(&self, key: &K) -> u64 {
        self.hasher.hash_one(key)
    }

    /// Captures `key` and its hash for a new membership.
    fn capture(&self, key: K) -> CapturedKey<K> {
        CapturedKey {
            hash: self.hash_of(&key),
            key: Arc::new(key),
        }
    }

    /// Returns the item whose membership captured `key`.
    ///
    /// The lookup searches a snapshot of the index with no lock held, so
    /// `K::hash` and `K::eq` may read this collection.
    pub fn get_by_key(&self, key: &K) -> Option<T> {
        let hash = self.hash_of(key);
        let (candidates, items) = {
            let inner = lock(&self.inner);
            (inner.candidates(hash), Arc::clone(&inner.items))
        };
        let position = find_key(&candidates, key);
        position.and_then(|position| items.get(position).cloned())
    }

    /// Reports whether `key` identifies a captured membership.
    ///
    /// Like [`get_by_key`](Self::get_by_key), it runs `K::hash` and `K::eq`
    /// with no lock held.
    pub fn contains_key(&self, key: &K) -> bool {
        let hash = self.hash_of(key);
        let candidates = lock(&self.inner).candidates(hash);
        find_key(&candidates, key).is_some()
    }

    /// Returns an insertion-ordered item snapshot.
    pub fn to_vec(&self) -> Vec<T> {
        Vec::clone(&lock(&self.inner).items)
    }

    /// Projects and appends `item`, rejecting duplicate keys atomically.
    pub fn push(&self, item: T) -> VmxResult<()> {
        let key = self.capture((self.key_of)(&item)?);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        // `K::eq` runs on a snapshot of the bucket, with no lock held; the
        // admission keeps other threads out, and the revision check catches a
        // change that `eq` itself made, after which the search runs again.
        loop {
            let revision = self.delivery.revision();
            let candidates = lock(&self.inner).candidates(key.hash);
            let duplicate = find_key(&candidates, &key.key).is_some();
            drop(candidates);
            if duplicate {
                self.finish(admission);
                return Err(Self::duplicate_key_error());
            }
            let mut retired = None;
            let position = {
                let mut inner = lock(&self.inner);
                if self.delivery.revision() != revision {
                    continue;
                }
                let position = inner.items.len();
                cow_mut(&mut inner.items, &mut retired).push(item);
                inner.index_key(&key, position);
                inner.keys.push(key);
                position
            };
            publish_then_drop(retired, || {
                self.publish(admission, CollectionChangeAction::Add, None, Some(position));
            });
            return Ok(());
        }
    }

    /// Removes the first item equal to `item`.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        // `PartialEq` runs on a shared snapshot, with no lock held (see
        // `ServicedObservableCollection::remove`).
        loop {
            let revision = self.delivery.revision();
            let snapshot = Arc::clone(&lock(&self.inner).items);
            let found = snapshot.iter().position(|candidate| candidate == item);
            drop(snapshot);
            let Some(position) = found else {
                self.finish(admission);
                return false;
            };
            let removed = {
                let mut inner = lock(&self.inner);
                if self.delivery.revision() != revision {
                    continue;
                }
                Self::remove_membership(&mut inner, position)
            };
            publish_then_drop(removed, || {
                self.publish(
                    admission,
                    CollectionChangeAction::Remove,
                    Some(position),
                    None,
                );
            });
            return true;
        }
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
        let (removed, old_key, retired) = removed;
        publish_then_drop((old_key, retired), || {
            self.publish(admission, CollectionChangeAction::Remove, Some(index), None);
        });
        Ok(removed)
    }

    /// Removes and returns the membership captured under `key`.
    pub fn remove_key(&self, key: &K) -> Option<T> {
        let hash = self.hash_of(key);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        loop {
            let revision = self.delivery.revision();
            let candidates = lock(&self.inner).candidates(hash);
            let found = find_key(&candidates, key);
            drop(candidates);
            let Some(position) = found else {
                self.finish(admission);
                return None;
            };
            let removed = {
                let mut inner = lock(&self.inner);
                if self.delivery.revision() != revision {
                    continue;
                }
                Self::remove_membership(&mut inner, position)
            };
            let (removed, old_key, retired) = removed;
            publish_then_drop((old_key, retired), || {
                self.publish(
                    admission,
                    CollectionChangeAction::Remove,
                    Some(position),
                    None,
                );
            });
            return Some(removed);
        }
    }

    /// Replaces a membership and its captured key atomically.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let key = self.capture((self.key_of)(&item)?);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        if index >= self.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        loop {
            let revision = self.delivery.revision();
            let candidates = lock(&self.inner).candidates(key.hash);
            let owner = find_key(&candidates, &key.key);
            drop(candidates);
            if owner.is_some_and(|owner| owner != index) {
                self.finish(admission);
                return Err(Self::duplicate_key_error());
            }
            let mut retired = None;
            let (old, old_key) = {
                let mut inner = lock(&self.inner);
                if self.delivery.revision() != revision {
                    continue;
                }
                if index >= inner.items.len() {
                    drop(inner);
                    self.finish(admission);
                    return Err(VmxError::InvalidArgument("index out of range".to_string()));
                }
                Self::replace_membership(&mut inner, index, key, item, &mut retired)
            };
            publish_then_drop((old_key, retired), || {
                self.publish(
                    admission,
                    CollectionChangeAction::Replace,
                    Some(index),
                    Some(index),
                );
            });
            return Ok(old);
        }
    }

    /// Preflights keys and atomically replaces every membership.
    pub fn replace_all<I>(&self, items: I) -> VmxResult<()>
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot = items.into_iter().collect::<Vec<_>>();
        // The new index is built with no lock held: `K::hash` and `K::eq`
        // run here.
        let mut fresh = KeyedServicedCollectionState::<K, T>::default();
        for (position, item) in snapshot.iter().enumerate() {
            let key = self.capture((self.key_of)(item)?);
            if find_key(&fresh.candidates(key.hash), &key.key).is_some() {
                return Err(Self::duplicate_key_error());
            }
            fresh.index_key(&key, position);
            fresh.keys.push(key);
        }
        fresh.items = Arc::new(snapshot);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        // Old memberships and keys are dropped after the change is published,
        // with no lock held.
        let previous = {
            let mut inner = lock(&self.inner);
            if inner.items.is_empty() && fresh.items.is_empty() {
                return Ok(());
            }
            std::mem::replace(&mut *inner, fresh)
        };
        publish_then_drop(previous, || {
            self.publish(admission, CollectionChangeAction::Reset, None, None);
        });
        Ok(())
    }

    /// Adds a missing key or replaces the existing membership in place.
    ///
    /// Returns `true` for Add and `false` for Replace.
    pub fn upsert(&self, item: T) -> VmxResult<bool> {
        let key = self.capture((self.key_of)(&item)?);
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        loop {
            let revision = self.delivery.revision();
            let candidates = lock(&self.inner).candidates(key.hash);
            let existing = find_key(&candidates, &key.key);
            drop(candidates);
            let mut retired = None;
            let (index, replaced) = {
                let mut inner = lock(&self.inner);
                if self.delivery.revision() != revision {
                    continue;
                }
                if let Some(index) = existing {
                    let replaced =
                        Self::replace_membership(&mut inner, index, key, item, &mut retired);
                    (index, Some(replaced))
                } else {
                    let index = inner.items.len();
                    cow_mut(&mut inner.items, &mut retired).push(item);
                    inner.index_key(&key, index);
                    inner.keys.push(key);
                    (index, None)
                }
            };
            let added = replaced.is_none();
            publish_then_drop((replaced, retired), || {
                if added {
                    self.publish(admission, CollectionChangeAction::Add, None, Some(index));
                } else {
                    self.publish(
                        admission,
                        CollectionChangeAction::Replace,
                        Some(index),
                        Some(index),
                    );
                }
            });
            return Ok(added);
        }
    }

    /// Moves a membership while preserving and reindexing captured keys.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        let mut retired = None;
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
            let items = cow_mut(&mut inner.items, &mut retired);
            let item = items.remove(from_index);
            items.insert(to_index, item);
            let key = inner.keys.remove(from_index);
            inner.keys.insert(to_index, key);
            inner.repair_positions(from_index.min(to_index));
        }
        publish_then_drop(retired, || {
            self.publish(
                admission,
                CollectionChangeAction::Move,
                Some(from_index),
                Some(to_index),
            );
        });
        Ok(())
    }

    /// Clears every membership and captured key, publishing one reset.
    pub fn clear(&self) {
        let admission = ServicedCollectionAdmission::acquire(Arc::clone(&self.delivery));
        // Memberships and keys are dropped after the reset is published, with
        // no lock held (#1295).
        let previous = {
            let mut inner = lock(&self.inner);
            if inner.items.is_empty() {
                return;
            }
            std::mem::take(&mut *inner)
        };
        publish_then_drop(previous, || {
            self.publish(admission, CollectionChangeAction::Reset, None, None);
        });
    }

    fn duplicate_key_error() -> VmxError {
        VmxError::InvalidArgument("duplicate key".to_string())
    }

    /// Removes a membership, returning its item, captured key, and any
    /// displaced item snapshot so the caller drops them after releasing the
    /// lock. No user code runs.
    fn remove_membership(
        inner: &mut KeyedServicedCollectionState<K, T>,
        index: usize,
    ) -> (T, CapturedKey<K>, Retired<T>) {
        let mut retired = None;
        let removed = cow_mut(&mut inner.items, &mut retired).remove(index);
        let old_key = inner.keys.remove(index);
        inner.unindex_key(&old_key);
        inner.repair_positions(index);
        (removed, old_key, retired)
    }

    /// Replaces the membership at `index` with `item` under `key`, returning
    /// the old item and its captured key. No user code runs.
    fn replace_membership(
        inner: &mut KeyedServicedCollectionState<K, T>,
        index: usize,
        key: CapturedKey<K>,
        item: T,
        retired: &mut Retired<T>,
    ) -> (T, CapturedKey<K>) {
        inner.index_key(&key, index);
        let old_key = std::mem::replace(&mut inner.keys[index], key);
        inner.unindex_key(&old_key);
        let items = cow_mut(&mut inner.items, retired);
        (std::mem::replace(&mut items[index], item), old_key)
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
            sender_name: "KeyedServicedObservableCollection".to_string(),
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });

        let current = admission.current;
        let mut delivery = lock(&self.delivery.state);
        debug_assert_eq!(delivery.draining_owner, Some(current));
        delivery.pending.push_back(message);
        delivery.revision = delivery.revision.wrapping_add(1);
        if !admission.owns_drain {
            admission.disarm();
            return;
        }
        admission.disarm();
        drop(delivery);
        self.drain_as_owner(current);
    }

    /// Ends an admission that published nothing. When it owns the drain, a
    /// nested mutation from user `PartialEq` may have queued messages
    /// meanwhile; they are delivered before the drain is released (#747).
    fn finish(&self, mut admission: ServicedCollectionAdmission) {
        admission.disarm();
        if admission.owns_drain {
            self.drain_as_owner(admission.current);
        }
    }

    /// Delivers every pending message as the drain owner, then releases the
    /// drain. A panicking subscriber clears the queue and re-raises.
    fn drain_as_owner(&self, current: ThreadId) {
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
    local: MessageHub,
    owner_id: usize,
    owner_name: Arc<str>,
    batch_depth: Arc<Mutex<usize>>,
    batch_dirty: Arc<Mutex<bool>>,
    batch_count_at_start: Arc<Mutex<usize>>,
    publication_closed: Arc<AtomicBool>,
}

impl<T: Clone + Send + 'static> ObservableList<T> {
    /// Creates an empty list whose messages use `owner_id`.
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self::with_owner_name(owner_id, "ObservableList", hub)
    }

    /// Creates an empty list whose messages carry the owning container's
    /// identity and diagnostic name (ADR-0120).
    pub(crate) fn with_owner_name(
        owner_id: usize,
        owner_name: impl Into<Arc<str>>,
        hub: MessageHub,
    ) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            local: MessageHub::new(),
            owner_id,
            owner_name: owner_name.into(),
            batch_depth: Arc::new(Mutex::new(0)),
            batch_dirty: Arc::new(Mutex::new(false)),
            batch_count_at_start: Arc::new(Mutex::new(0)),
            publication_closed: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Stops all further publication for a disposed owning container
    /// (ADR-0142): later mutations, including a pending batch `Reset`, send
    /// nothing to the hub.
    pub(crate) fn close_publication(&self) {
        self.publication_closed.store(true, Ordering::Release);
    }

    /// Returns the local collection-change stream. It receives each
    /// `CollectionChanged` message before the hub does and is never deferred
    /// by a hub batch, like the local collection events of the other flavors
    /// that `AggregateChangeStream` membership uses (spec/21 §9.1).
    pub(crate) fn local_changes(&self) -> MessageHub {
        self.local.clone()
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

    /// Removes and returns the item at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let item = self
            .remove_at_silent(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        self.publish(CollectionChangeAction::Remove, Some(index), None, true);
        Ok(item)
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

    pub(crate) fn replace_silent(&self, index: usize, item: T) -> VmxResult<T> {
        let mut inner = lock(&self.inner);
        if index >= inner.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        Ok(std::mem::replace(&mut inner[index], item))
    }

    pub(crate) fn publish_replace(&self, index: usize) {
        self.publish(
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
            false,
        );
    }

    /// Replaces and returns an item without changing the count.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let old = self.replace_silent(index, item)?;
        self.publish_replace(index);
        Ok(old)
    }

    /// Atomically replaces the list from a materialized input snapshot.
    pub fn replace_all<I>(&self, items: I)
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot: Vec<T> = items.into_iter().collect();
        let new_count = snapshot.len();
        let previous = {
            let mut inner = lock(&self.inner);
            if inner.is_empty() && snapshot.is_empty() {
                return;
            }
            std::mem::replace(&mut *inner, snapshot)
        };
        let old_count = previous.len();
        // Old items are dropped after the reset is published, with no lock
        // held (#1295).
        publish_then_drop(previous, || {
            self.publish(
                CollectionChangeAction::Reset,
                None,
                None,
                old_count != new_count,
            );
        });
    }

    pub(crate) fn move_item_silent(&self, from_index: usize, to_index: usize) -> VmxResult<bool> {
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.len() || to_index >= inner.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(false);
            }
            let item = inner.remove(from_index);
            inner.insert(to_index, item);
        }
        Ok(true)
    }

    pub(crate) fn publish_move(&self, from_index: usize, to_index: usize) {
        self.publish(
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
            false,
        );
    }

    /// Clears a non-empty list and publishes reset and count changes.
    pub fn clear(&self) {
        let previous = self.take_silent();
        // Items are dropped after the reset is published, with no lock held
        // (#1295).
        if !previous.is_empty() {
            publish_then_drop(previous, || self.publish_reset());
        }
    }

    /// Empties the list without notifying and returns the removed items, so
    /// the caller drops them after releasing any lock it holds.
    pub(crate) fn take_silent(&self) -> Vec<T> {
        std::mem::take(&mut *lock(&self.inner))
    }

    pub(crate) fn publish_reset(&self) {
        self.publish(CollectionChangeAction::Reset, None, None, true);
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
        if self.publication_closed.load(Ordering::Acquire) {
            return;
        }
        if *lock(&self.batch_depth) > 0 {
            *lock(&self.batch_dirty) = true;
            return;
        }
        let message = Message::CollectionChanged(CollectionChangedMessage {
            sender_id: self.owner_id,
            sender_name: self.owner_name.to_string(),
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });
        self.local.send(message.clone());
        self.hub.send(message);
        if count_changed {
            self.hub
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.owner_id,
                    sender_name: self.owner_name.to_string(),
                    property_name: "Count".to_string(),
                }));
        }
    }
}

/// Insertion-ordered dictionary keys and values plus a write counter.
///
/// Key comparisons run user `PartialEq` code, so the dictionaries compare
/// keys against a shared snapshot of `keys` with no lock held and commit only
/// when `revision` still matches the snapshot; otherwise they search again
/// (the `FormVm::set_model` pattern). Taking the snapshot clones one `Arc`,
/// not the keys (#765). Replaced and removed keys and values, and a key
/// snapshot that a write displaced, are dropped after the change is
/// published, with no lock held (#1295).
///
/// Each value sits behind its own lock, which no write takes. A reader copies
/// the value's handle under the dictionary lock and runs `V::clone` after it
/// releases that lock, so a clone may read or write the dictionary (#1276).
struct DictionaryEntries<K, V> {
    keys: Shared<K>,
    values: Vec<StoredValue<V>>,
    revision: u64,
}

/// One stored dictionary value. The lock serializes clones of this value;
/// no dictionary write takes it. `Mutex<V>` is `Sync` when `V: Send`, so the
/// dictionaries keep their `V: Clone + Send` bound.
type StoredValue<V> = Arc<Mutex<V>>;

fn store_value<V>(value: V) -> StoredValue<V> {
    Arc::new(Mutex::new(value))
}

/// Returns the value of a removed entry. When a reader still holds the
/// value's handle, the value is cloned with no dictionary lock held.
fn take_value<V: Clone>(stored: StoredValue<V>) -> V {
    match Arc::try_unwrap(stored) {
        Ok(value) => value
            .into_inner()
            .unwrap_or_else(|poisoned| poisoned.into_inner()),
        Err(shared) => clone_locked(&shared),
    }
}

impl<K, V> Default for DictionaryEntries<K, V> {
    fn default() -> Self {
        Self {
            keys: Shared::default(),
            values: Vec::new(),
            revision: 0,
        }
    }
}

impl<K: Clone, V> DictionaryEntries<K, V> {
    /// Appends an entry and returns its index.
    fn push(&mut self, key: K, value: V, retired: &mut Retired<K>) -> usize {
        cow_mut(&mut self.keys, retired).push(key);
        self.values.push(store_value(value));
        self.values.len() - 1
    }

    /// Removes and returns the entry at `index`.
    fn remove(&mut self, index: usize, retired: &mut Retired<K>) -> (K, StoredValue<V>) {
        let key = cow_mut(&mut self.keys, retired).remove(index);
        (key, self.values.remove(index))
    }
}

/// Returns the shared key snapshot. The caller drops it with no lock held.
fn key_snapshot<K, V>(inner: &Mutex<DictionaryEntries<K, V>>) -> Shared<K> {
    Arc::clone(&lock(inner).keys)
}

/// Finds the first key that `matches`, running it with no lock held, and
/// returns the revision that the search saw.
fn locate_key<K, V>(
    inner: &Mutex<DictionaryEntries<K, V>>,
    matches: impl FnMut(&K) -> bool,
) -> (u64, Option<usize>) {
    let (revision, keys) = {
        let inner = lock(inner);
        (inner.revision, Arc::clone(&inner.keys))
    };
    let index = keys.iter().position(matches);
    // Released before the caller retakes the lock, so a commit does not copy
    // the keys, and a snapshot that a write displaced meanwhile drops its
    // keys here, with no lock held.
    drop(keys);
    (revision, index)
}

/// Returns the stored value at `index` when no write happened since
/// `revision`, or `None` inside `Some` when `index` is `None`. Returns `None`
/// when a write happened, so the caller searches again. No user code runs.
fn stored_value_at<K, V>(
    inner: &Mutex<DictionaryEntries<K, V>>,
    revision: u64,
    index: Option<usize>,
) -> Option<Option<StoredValue<V>>> {
    let inner = lock(inner);
    (inner.revision == revision).then(|| index.map(|index| Arc::clone(&inner.values[index])))
}

/// Runs `write` when no write happened since `revision`, bumping it. A key
/// snapshot that the write displaced is returned with the result, for the
/// caller to drop after the lock is released.
fn commit_entries<K, V, R>(
    inner: &Mutex<DictionaryEntries<K, V>>,
    revision: u64,
    write: impl FnOnce(&mut DictionaryEntries<K, V>, &mut Retired<K>) -> R,
) -> Option<(R, Retired<K>)> {
    let mut inner = lock(inner);
    if inner.revision != revision {
        return None;
    }
    inner.revision = inner.revision.wrapping_add(1);
    let mut retired = None;
    let result = write(&mut inner, &mut retired);
    Some((result, retired))
}

#[derive(Clone)]
/// An insertion-ordered observable key/value dictionary.
pub struct ObservableDictionary<K, V>
where
    K: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    inner: Arc<Mutex<DictionaryEntries<K, V>>>,
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
            inner: Arc::new(Mutex::new(DictionaryEntries::default())),
            hub,
            owner_id,
        }
    }

    fn locate(&self, key: &K) -> (u64, Option<usize>) {
        locate_key(&self.inner, |candidate| candidate == key)
    }

    /// Adds `key` or replaces its existing value in place.
    pub fn insert(&self, key: K, value: V) {
        let mut entry = Some((key, value));
        let ((action, replaced, new_index), retired) = loop {
            let (revision, index) = self.locate(&entry.as_ref().expect("entry pending").0);
            let committed = commit_entries(&self.inner, revision, |entries, retired| {
                let (key, value) = entry.take().expect("entry pending");
                match index {
                    // The stored key stays; the argument key is returned so
                    // that it drops after the lock is released.
                    Some(index) => (
                        CollectionChangeAction::Replace,
                        Some((
                            key,
                            std::mem::replace(&mut entries.values[index], store_value(value)),
                        )),
                        None,
                    ),
                    None => {
                        let position = entries.push(key, value, retired);
                        // Add carries its insertion position (spec/21 §2.4).
                        (CollectionChangeAction::Add, None, Some(position))
                    }
                }
            });
            if let Some(committed) = committed {
                break committed;
            }
        };
        publish_then_drop((replaced, retired), || self.publish_at(action, new_index));
    }

    /// Returns the value associated with `key`, if present.
    ///
    /// `V::clone` runs with no dictionary lock held, so a clone may read this
    /// dictionary (#1276). Clones of one stored value take turns: a
    /// `V::clone` must not wait for another clone of the same value, and must
    /// not read that value again on its own thread.
    pub fn get(&self, key: &K) -> Option<V> {
        loop {
            let (revision, index) = self.locate(key);
            if let Some(stored) = stored_value_at(&self.inner, revision, index) {
                return stored.map(|stored| clone_locked(&stored));
            }
        }
    }

    /// Removes and returns the value associated with `key`.
    pub fn remove(&self, key: &K) -> Option<V> {
        let removed = loop {
            let (revision, index) = self.locate(key);
            let Some(index) = index else {
                break None;
            };
            if let Some(removed) = commit_entries(&self.inner, revision, |entries, retired| {
                entries.remove(index, retired)
            }) {
                break Some(removed);
            }
        };
        let ((removed_key, value), retired) = removed?;
        // The removed key drops after the change is published (#1295).
        publish_then_drop((removed_key, retired), || {
            self.publish(CollectionChangeAction::Remove);
        });
        Some(take_value(value))
    }

    /// Clears a non-empty dictionary and publishes one reset.
    pub fn clear(&self) {
        let removed = {
            let mut inner = lock(&self.inner);
            inner.revision = inner.revision.wrapping_add(1);
            (
                std::mem::take(&mut inner.keys),
                std::mem::take(&mut inner.values),
            )
        };
        let changed = !removed.1.is_empty();
        // The entries drop after the reset is published (#1295).
        publish_then_drop(removed, || {
            if changed {
                self.publish(CollectionChangeAction::Reset);
            }
        });
    }

    /// Returns keys in insertion order.
    pub fn keys(&self) -> Vec<K> {
        Vec::clone(&key_snapshot(&self.inner))
    }

    fn publish(&self, action: CollectionChangeAction) {
        self.publish_at(action, None);
    }

    fn publish_at(&self, action: CollectionChangeAction, new_index: Option<usize>) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                sender_name: "ObservableDictionary".to_string(),
                property_name: "items".to_string(),
                action,
                old_index: None,
                new_index,
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
    inner: Arc<Mutex<DictionaryEntries<(K1, K2), V>>>,
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
            inner: Arc::new(Mutex::new(DictionaryEntries::default())),
            hub,
            owner_id,
        }
    }

    fn locate(&self, key1: &K1, key2: &K2) -> (u64, Option<usize>) {
        locate_key(&self.inner, |(candidate1, candidate2)| {
            candidate1 == key1 && candidate2 == key2
        })
    }

    /// Adds a new key pair, rejecting a pair that is already present without
    /// changing the dictionary (spec/21 §4.1 `Add`).
    pub fn add(&self, key1: K1, key2: K2, value: V) -> VmxResult<()> {
        let mut entry = Some((key1, key2, value));
        let (position, retired) = loop {
            let pending = entry.as_ref().expect("entry pending");
            let (revision, index) = self.locate(&pending.0, &pending.1);
            if index.is_some() {
                return Err(VmxError::InvalidArgument("duplicate key pair".to_string()));
            }
            if let Some(committed) = commit_entries(&self.inner, revision, |entries, retired| {
                let (key1, key2, value) = entry.take().expect("entry pending");
                entries.push((key1, key2), value, retired)
            }) {
                break committed;
            }
        };
        // Add carries its insertion position (spec/21 §2.4).
        publish_then_drop(retired, || {
            self.publish_at(CollectionChangeAction::Add, Some(position));
        });
        Ok(())
    }

    /// Removes every entry and publishes one `Reset`, as every flavor's
    /// dictionary does, even when it was already empty.
    pub fn clear(&self) {
        let removed = {
            let mut inner = lock(&self.inner);
            inner.revision = inner.revision.wrapping_add(1);
            (
                std::mem::take(&mut inner.keys),
                std::mem::take(&mut inner.values),
            )
        };
        // The entries drop after the reset is published (#1295).
        publish_then_drop(removed, || self.publish(CollectionChangeAction::Reset));
    }

    /// Returns a snapshot of every entry in insertion order.
    ///
    /// Keys and values are cloned with no dictionary lock held, so a clone
    /// may read this dictionary (#1276). Clones of one stored value take
    /// turns, as in [`get`](Self::get).
    pub fn entries(&self) -> Vec<(K1, K2, V)> {
        let (keys, values) = {
            let inner = lock(&self.inner);
            (Arc::clone(&inner.keys), inner.values.clone())
        };
        keys.iter()
            .zip(&values)
            .map(|((key1, key2), value)| (key1.clone(), key2.clone(), clone_locked(value)))
            .collect()
    }

    /// Adds a key pair or replaces its existing value in place.
    pub fn insert(&self, key1: K1, key2: K2, value: V) {
        let mut entry = Some((key1, key2, value));
        let ((action, replaced, new_index), retired) = loop {
            let pending = entry.as_ref().expect("entry pending");
            let (revision, index) = self.locate(&pending.0, &pending.1);
            let committed = commit_entries(&self.inner, revision, |entries, retired| {
                let (key1, key2, value) = entry.take().expect("entry pending");
                match index {
                    // The stored keys stay; the argument keys are returned so
                    // that they drop after the lock is released.
                    Some(index) => (
                        CollectionChangeAction::Replace,
                        Some((
                            (key1, key2),
                            std::mem::replace(&mut entries.values[index], store_value(value)),
                        )),
                        None,
                    ),
                    None => {
                        let position = entries.push((key1, key2), value, retired);
                        (CollectionChangeAction::Add, None, Some(position))
                    }
                }
            });
            if let Some(committed) = committed {
                break committed;
            }
        };
        publish_then_drop((replaced, retired), || self.publish_at(action, new_index));
    }

    /// Removes and returns the value associated with a key pair.
    pub fn remove(&self, key1: &K1, key2: &K2) -> Option<V> {
        let removed = loop {
            let (revision, index) = self.locate(key1, key2);
            let Some(index) = index else {
                break None;
            };
            if let Some(removed) = commit_entries(&self.inner, revision, |entries, retired| {
                entries.remove(index, retired)
            }) {
                break Some(removed);
            }
        };
        let ((removed_keys, value), retired) = removed?;
        // The removed keys drop after the change is published (#1295).
        publish_then_drop((removed_keys, retired), || {
            self.publish(CollectionChangeAction::Remove);
        });
        Some(take_value(value))
    }

    /// Returns the value associated with a key pair, if present.
    ///
    /// `V::clone` runs with no dictionary lock held, as in
    /// [`ObservableDictionary::get`].
    pub fn get(&self, key1: &K1, key2: &K2) -> Option<V> {
        loop {
            let (revision, index) = self.locate(key1, key2);
            if let Some(stored) = stored_value_at(&self.inner, revision, index) {
                return stored.map(|stored| clone_locked(&stored));
            }
        }
    }

    /// Reports whether a key pair is present.
    pub fn contains_key(&self, key1: &K1, key2: &K2) -> bool {
        loop {
            let (revision, index) = self.locate(key1, key2);
            if let Some(stored) = stored_value_at(&self.inner, revision, index) {
                return stored.is_some();
            }
        }
    }

    /// Returns the number of key-pair memberships.
    pub fn count(&self) -> usize {
        lock(&self.inner).values.len()
    }

    /// Returns distinct first-dimension keys in insertion order.
    pub fn keys1(&self) -> Vec<K1> {
        let mut keys = Vec::new();
        for (key, _) in key_snapshot(&self.inner).iter() {
            if !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    /// Returns distinct second-dimension keys in insertion order.
    pub fn keys2(&self) -> Vec<K2> {
        let mut keys = Vec::new();
        for (_, key) in key_snapshot(&self.inner).iter() {
            if !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    fn publish(&self, action: CollectionChangeAction) {
        self.publish_at(action, None);
    }

    fn publish_at(&self, action: CollectionChangeAction, new_index: Option<usize>) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                sender_name: "ObservableMultiDictionary".to_string(),
                property_name: "items".to_string(),
                action,
                old_index: None,
                new_index,
            }));
    }
}
