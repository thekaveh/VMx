//! Observable and serviced collection primitives.
//!
//! Spec: `spec/21-collections.md`.

use super::{
    catch_unwind, lock, resume_unwind, thread, wait, Arc, AssertUnwindSafe, AtomicBool, BTreeMap,
    CollectionChangeAction, CollectionChangedMessage, Condvar, Hash, HashMap, Message, MessageHub,
    Mutex, Ordering, PropertyChangedMessage, PropertyChangedStream, ThreadId, VecDeque, VmxError,
    VmxResult,
};
use crate::clone_locked;
use crate::runtime::wait_for_owner;
use crate::wait_for_graph::{waits, Resource};
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

type EventHandler<E> = Arc<dyn Fn(&E) + Send + Sync + 'static>;

struct EventStreamInner<E: ?Sized> {
    next_subscription_id: usize,
    subscribers: BTreeMap<usize, EventHandler<E>>,
}

/// A hot, synchronous stream of typed local collection events.
///
/// Each event reaches the subscribers present when it is sent, on the
/// sending thread, before the mutation call returns. Late subscribers do not
/// receive earlier events. A list builds an event only when the stream has a
/// subscriber as the mutation starts, so a subscriber added during a mutation
/// of a stream that had none misses that mutation's event. Subscriber panics
/// are isolated from the publisher and from the other subscribers (spec/21
/// §3.2, ADR-0208).
pub struct EventStream<E: ?Sized + 'static> {
    inner: Arc<Mutex<EventStreamInner<E>>>,
}

impl<E: ?Sized + 'static> Clone for EventStream<E> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
        }
    }
}

impl<E: ?Sized + 'static> EventStream<E> {
    fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(EventStreamInner {
                next_subscription_id: 0,
                subscribers: BTreeMap::new(),
            })),
        }
    }

    /// Subscribes to the events sent after this call.
    pub fn subscribe<F>(&self, handler: F) -> EventSubscription
    where
        F: Fn(&E) + Send + Sync + 'static,
    {
        let id = {
            let mut inner = lock(&self.inner);
            inner.next_subscription_id += 1;
            let id = inner.next_subscription_id;
            inner.subscribers.insert(id, Arc::new(handler));
            id
        };
        let stream = Arc::downgrade(&self.inner);
        EventSubscription {
            detach: Mutex::new(Some(Box::new(move || {
                if let Some(stream) = stream.upgrade() {
                    // The handler drops after the lock is released.
                    let removed = lock(&stream).subscribers.remove(&id);
                    drop(removed);
                }
            }))),
        }
    }

    fn has_subscribers(&self) -> bool {
        !lock(&self.inner).subscribers.is_empty()
    }

    fn send(&self, event: &E) {
        let subscribers = lock(&self.inner)
            .subscribers
            .values()
            .cloned()
            .collect::<Vec<_>>();
        for subscriber in subscribers {
            let _ = catch_unwind(AssertUnwindSafe(|| subscriber(event)));
        }
    }
}

type Detach = Box<dyn FnOnce() + Send + 'static>;

/// Disposable registration in an [`EventStream`].
pub struct EventSubscription {
    detach: Mutex<Option<Detach>>,
}

impl EventSubscription {
    /// Detaches the subscriber; repeated calls are inert.
    pub fn dispose(&self) {
        let detach = lock(&self.detach).take();
        if let Some(detach) = detach {
            detach();
        }
    }
}

impl Drop for EventSubscription {
    fn drop(&mut self) {
        self.dispose();
    }
}

/// Payload of [`ObservableList::item_added`]: the item and its insertion index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ItemAddedEvent<T> {
    /// The added item.
    pub item: T,
    /// The index the item was inserted at.
    pub index: usize,
}

/// Payload of [`ObservableList::item_removed`]: the item and its index
/// before the removal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ItemRemovedEvent<T> {
    /// The removed item.
    pub item: T,
    /// The index the item had before it was removed.
    pub index: usize,
}

/// Payload of [`ObservableList::item_replaced`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ItemReplacedEvent<T> {
    /// The item now at `index`.
    pub new_item: T,
    /// The item that `new_item` replaced.
    pub old_item: T,
    /// The replaced index.
    pub index: usize,
}

/// One granular event, built only when its stream has a subscriber.
enum ItemEvent<T> {
    Added(ItemAddedEvent<T>),
    Removed(ItemRemovedEvent<T>),
    Replaced(ItemReplacedEvent<T>),
}

/// The local streams of one list, shared by its clones.
struct ListStreams<T: 'static> {
    item_added: EventStream<ItemAddedEvent<T>>,
    item_removed: EventStream<ItemRemovedEvent<T>>,
    item_replaced: EventStream<ItemReplacedEvent<T>>,
    reset: EventStream<()>,
    property_changed: PropertyChangedStream,
}

impl<T: 'static> ListStreams<T> {
    fn new() -> Self {
        Self {
            item_added: EventStream::new(),
            item_removed: EventStream::new(),
            item_replaced: EventStream::new(),
            reset: EventStream::new(),
            property_changed: PropertyChangedStream::default(),
        }
    }
}

#[derive(Clone)]
/// An ordered observable list with granular events and reset-coalescing
/// batch updates (spec/21 §3).
///
/// Each mutation sends one granular event on [`item_added`](Self::item_added),
/// [`item_removed`](Self::item_removed), [`item_replaced`](Self::item_replaced)
/// or [`reset`](Self::reset). A mutation that changes the item count then
/// sends the spec-literal `Count` name on
/// [`property_changed`](Self::property_changed). A list made with
/// [`with_hub`](Self::with_hub) also publishes each change to its hub as a
/// `CollectionChangedMessage` and the `Count` change as a
/// `PropertyChangedMessage`. A list made with [`new`](Self::new) has no hub.
pub struct ObservableList<T: Clone + Send + 'static> {
    /// The items. A value removal compares a shared snapshot with no lock
    /// held, so writes copy when a snapshot is outstanding (#765).
    inner: Arc<Mutex<Shared<T>>>,
    hub: Option<MessageHub>,
    local: MessageHub,
    streams: Arc<ListStreams<T>>,
    owner_id: usize,
    owner_name: Arc<str>,
    batch_depth: Arc<Mutex<usize>>,
    batch_dirty: Arc<Mutex<bool>>,
    batch_count_at_start: Arc<Mutex<usize>>,
    publication_closed: Arc<AtomicBool>,
    hub_publication_closed: Arc<AtomicBool>,
}

impl<T: Clone + Send + 'static> ObservableList<T> {
    /// Creates an empty list without a message hub. Its mutations reach only
    /// the local streams.
    pub fn new(owner_id: usize) -> Self {
        Self::build(owner_id, "ObservableList", None)
    }

    /// Creates an empty list that also publishes its changes to `hub`.
    pub fn with_hub(owner_id: usize, hub: MessageHub) -> Self {
        Self::build(owner_id, "ObservableList", Some(hub))
    }

    /// Creates an empty list whose messages carry the owning container's
    /// identity and name (ADR-0120). A `CompositeVm` or `GroupVm` passes its
    /// `name()`, so each message carries the container's name (ADR-0194).
    pub(crate) fn with_owner_name(
        owner_id: usize,
        owner_name: impl Into<Arc<str>>,
        hub: MessageHub,
    ) -> Self {
        Self::build(owner_id, owner_name, Some(hub))
    }

    fn build(owner_id: usize, owner_name: impl Into<Arc<str>>, hub: Option<MessageHub>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Shared::default())),
            hub,
            local: MessageHub::new(),
            streams: Arc::new(ListStreams::new()),
            owner_id,
            owner_name: owner_name.into(),
            batch_depth: Arc::new(Mutex::new(0)),
            batch_dirty: Arc::new(Mutex::new(false)),
            batch_count_at_start: Arc::new(Mutex::new(0)),
            publication_closed: Arc::new(AtomicBool::new(false)),
            hub_publication_closed: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Stops all further publication for a disposed owning container
    /// (ADR-0142): later mutations, including a pending batch `Reset`, send
    /// nothing to the hub.
    pub(crate) fn close_publication(&self) {
        self.publication_closed.store(true, Ordering::Release);
    }

    /// Stops hub publication for an owning container whose disposal is
    /// requested but deferred (ADR-0190). Local subscribers still receive
    /// each change until the disposal closes all publication.
    pub(crate) fn close_hub_publication(&self) {
        self.hub_publication_closed.store(true, Ordering::Release);
    }

    /// Returns the local collection-change stream. It receives each
    /// `CollectionChanged` message before the hub does and is never deferred
    /// by a hub batch, like the local collection events of the other flavors
    /// that `AggregateChangeStream` membership uses (spec/21 §9.1).
    pub(crate) fn local_changes(&self) -> MessageHub {
        self.local.clone()
    }

    /// Returns a reader of the current items that does not keep the list's
    /// streams alive, so a subscriber of those streams may hold it.
    pub(crate) fn reader(&self) -> impl Fn() -> Vec<T> + Send + Sync + 'static
    where
        T: Sync,
    {
        let inner = Arc::clone(&self.inner);
        move || {
            let snapshot = Arc::clone(&lock(&inner));
            Vec::clone(&snapshot)
        }
    }

    /// Returns the stream of added items and their insertion indices.
    pub fn item_added(&self) -> EventStream<ItemAddedEvent<T>> {
        self.streams.item_added.clone()
    }

    /// Returns the stream of removed items and their indices before removal.
    pub fn item_removed(&self) -> EventStream<ItemRemovedEvent<T>> {
        self.streams.item_removed.clone()
    }

    /// Returns the stream of replacements.
    pub fn item_replaced(&self) -> EventStream<ItemReplacedEvent<T>> {
        self.streams.item_replaced.clone()
    }

    /// Returns the stream that fires after a clear, a whole-list replacement,
    /// or a batch that changed the list.
    pub fn reset(&self) -> EventStream<()> {
        self.streams.reset.clone()
    }

    /// Returns the local property-change stream. It sends the spec-literal
    /// `Count` name after each granular event or `Reset` that changed the
    /// item count (spec/21 §3.3).
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.streams.property_changed.clone()
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
        let snapshot = Arc::clone(&lock(&self.inner));
        Vec::clone(&snapshot)
    }

    /// Returns the item at `index`, if present.
    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).get(index).cloned()
    }

    /// Appends an item and publishes add and count changes.
    pub fn push(&self, item: T) {
        let event_item = self
            .streams
            .item_added
            .has_subscribers()
            .then(|| item.clone());
        let mut retired = None;
        let index = {
            let mut inner = lock(&self.inner);
            let items = cow_mut(&mut inner, &mut retired);
            items.push(item);
            items.len() - 1
        };
        // A displaced snapshot drops after the change is published (#1295).
        publish_then_drop(retired, || {
            self.publish(
                CollectionChangeAction::Add,
                None,
                Some(index),
                true,
                event_item.map(|item| ItemEvent::Added(ItemAddedEvent { item, index })),
            );
        });
    }

    /// Inserts an item at a valid boundary index.
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let event_item = self
            .streams
            .item_added
            .has_subscribers()
            .then(|| item.clone());
        let mut retired = None;
        {
            let mut inner = lock(&self.inner);
            if index > inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            cow_mut(&mut inner, &mut retired).insert(index, item);
        }
        // A displaced snapshot drops after the change is published (#1295).
        publish_then_drop(retired, || {
            self.publish(
                CollectionChangeAction::Add,
                None,
                Some(index),
                true,
                event_item.map(|item| ItemEvent::Added(ItemAddedEvent { item, index })),
            );
        });
        Ok(())
    }

    /// Removes the first item equal to `item` and returns `true`, or returns
    /// `false` and publishes nothing when no item is equal (spec/21 §3.1).
    ///
    /// `PartialEq` runs on a shared snapshot with no lock held. When the list
    /// changed meanwhile, the search runs again.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        loop {
            let snapshot = Arc::clone(&lock(&self.inner));
            let Some(index) = snapshot.iter().position(|candidate| candidate == item) else {
                return false;
            };
            let mut retired = None;
            let removed = {
                let mut inner = lock(&self.inner);
                // A write copies while the snapshot is held, so an unchanged
                // pointer means that no write happened since the search.
                if !Arc::ptr_eq(&inner, &snapshot) {
                    drop(inner);
                    drop(snapshot);
                    continue;
                }
                // The store still holds the items, so this drops no item.
                drop(snapshot);
                cow_mut(&mut inner, &mut retired).remove(index)
            };
            // The removed item drops after the change is published (#1295).
            publish_then_drop(retired, || {
                self.publish(
                    CollectionChangeAction::Remove,
                    Some(index),
                    None,
                    true,
                    Some(ItemEvent::Removed(ItemRemovedEvent {
                        item: removed,
                        index,
                    })),
                );
            });
            return true;
        }
    }

    /// Removes and returns the item at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let item = self
            .remove_at_silent(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        let event_item = self
            .streams
            .item_removed
            .has_subscribers()
            .then(|| item.clone());
        self.publish(
            CollectionChangeAction::Remove,
            Some(index),
            None,
            true,
            event_item.map(|item| ItemEvent::Removed(ItemRemovedEvent { item, index })),
        );
        Ok(item)
    }

    pub(crate) fn remove_at_silent(&self, index: usize) -> Option<T> {
        let mut retired = None;
        let removed = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                None
            } else {
                Some(cow_mut(&mut inner, &mut retired).remove(index))
            }
        };
        drop(retired);
        removed
    }

    pub(crate) fn insert_silent(&self, index: usize, item: T) -> VmxResult<()> {
        let mut retired = None;
        {
            let mut inner = lock(&self.inner);
            if index > inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            cow_mut(&mut inner, &mut retired).insert(index, item);
        }
        drop(retired);
        Ok(())
    }

    pub(crate) fn publish_remove(&self, index: usize) {
        self.publish(
            CollectionChangeAction::Remove,
            Some(index),
            None,
            true,
            None,
        );
    }

    pub(crate) fn publish_add(&self, index: usize) {
        self.publish(CollectionChangeAction::Add, None, Some(index), true, None);
    }

    pub(crate) fn replace_silent(&self, index: usize, item: T) -> VmxResult<T> {
        let mut retired = None;
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            std::mem::replace(&mut cow_mut(&mut inner, &mut retired)[index], item)
        };
        drop(retired);
        Ok(old)
    }

    pub(crate) fn publish_replace(&self, index: usize) {
        self.publish(
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
            false,
            None,
        );
    }

    /// Replaces and returns an item without changing the count.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let new_item = self
            .streams
            .item_replaced
            .has_subscribers()
            .then(|| item.clone());
        let old = self.replace_silent(index, item)?;
        let event = new_item.map(|new_item| {
            ItemEvent::Replaced(ItemReplacedEvent {
                new_item,
                old_item: old.clone(),
                index,
            })
        });
        self.publish(
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
            false,
            event,
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
        let previous = {
            let mut inner = lock(&self.inner);
            if inner.is_empty() && snapshot.is_empty() {
                return;
            }
            std::mem::replace(&mut *inner, Arc::new(snapshot))
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
                None,
            );
        });
    }

    pub(crate) fn move_item_silent(&self, from_index: usize, to_index: usize) -> VmxResult<bool> {
        let mut retired = None;
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
            let items = cow_mut(&mut inner, &mut retired);
            let item = items.remove(from_index);
            items.insert(to_index, item);
        }
        drop(retired);
        Ok(true)
    }

    pub(crate) fn publish_move(&self, from_index: usize, to_index: usize) {
        self.publish(
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
            false,
            None,
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
    pub(crate) fn take_silent(&self) -> Shared<T> {
        std::mem::take(&mut *lock(&self.inner))
    }

    pub(crate) fn publish_reset(&self) {
        self.publish(CollectionChangeAction::Reset, None, None, true, None);
    }

    /// Runs `action` while coalescing effective changes into one reset.
    ///
    /// Granular events are suppressed inside the batch. Nested batches are
    /// supported, and a panic is resumed after batch state and notifications
    /// are finalized.
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
                self.publish(
                    CollectionChangeAction::Reset,
                    None,
                    None,
                    count_changed,
                    None,
                );
            }
        }
        if let Err(error) = result {
            resume_unwind(error);
        }
    }

    /// Sends the granular event, the local and hub collection messages, and
    /// then the `Count` change, in that order (spec/21 §3.3).
    fn publish(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
        count_changed: bool,
        event: Option<ItemEvent<T>>,
    ) {
        if self.publication_closed.load(Ordering::Acquire) {
            return;
        }
        if *lock(&self.batch_depth) > 0 {
            *lock(&self.batch_dirty) = true;
            return;
        }
        match &event {
            Some(ItemEvent::Added(event)) => self.streams.item_added.send(event),
            Some(ItemEvent::Removed(event)) => self.streams.item_removed.send(event),
            Some(ItemEvent::Replaced(event)) => self.streams.item_replaced.send(event),
            None if action == CollectionChangeAction::Reset => self.streams.reset.send(&()),
            None => {}
        }
        // The payload items drop after the messages are sent, with no lock
        // held, so a panicking item `Drop` cannot suppress them (#1295).
        publish_then_drop(event, || {
            self.publish_messages(action, old_index, new_index, count_changed);
        });
    }

    /// Sends the local and hub collection messages, then the `Count` change.
    fn publish_messages(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
        count_changed: bool,
    ) {
        let message = Message::CollectionChanged(CollectionChangedMessage {
            sender_id: self.owner_id,
            sender_name: self.owner_name.to_string(),
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });
        self.local.send(message.clone());
        // A local subscriber may request the owner's disposal; the hub then
        // receives nothing for this change (spec/01 §1.4, ADR-0190).
        if !self.hub_publication_is_closed() {
            if let Some(hub) = &self.hub {
                hub.send(message);
            }
        }
        if count_changed {
            if self.publication_closed.load(Ordering::Acquire) {
                return;
            }
            self.streams.property_changed.notify("Count");
            if self.hub_publication_is_closed() {
                return;
            }
            if let Some(hub) = &self.hub {
                hub.send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.owner_id,
                    sender_name: self.owner_name.to_string(),
                    property_name: "Count".to_string(),
                }));
            }
        }
    }

    /// Returns whether hub publication is closed, by a disposal or by a
    /// deferred disposal request of the owning container (ADR-0190).
    fn hub_publication_is_closed(&self) -> bool {
        self.publication_closed.load(Ordering::Acquire)
            || self.hub_publication_closed.load(Ordering::Acquire)
    }
}

impl<T: Clone + Send + 'static> IntoIterator for &ObservableList<T> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.to_vec().into_iter()
    }
}

/// A live, read-only view of an [`ObservableList`] (spec/21 §4.2,
/// ADR-0208).
///
/// It has every read and subscribe member of the list and no mutator and no
/// batch member. Only its owner changes the backing list.
pub struct ReadOnlyObservableList<T: Clone + Send + 'static> {
    list: ObservableList<T>,
}

impl<T: Clone + Send + 'static> Clone for ReadOnlyObservableList<T> {
    fn clone(&self) -> Self {
        Self {
            list: self.list.clone(),
        }
    }
}

impl<T: Clone + Send + 'static> ReadOnlyObservableList<T> {
    fn new(list: ObservableList<T>) -> Self {
        Self { list }
    }

    /// Returns the stream of added items and their insertion indices.
    pub fn item_added(&self) -> EventStream<ItemAddedEvent<T>> {
        self.list.item_added()
    }

    /// Returns the stream of removed items and their indices before removal.
    pub fn item_removed(&self) -> EventStream<ItemRemovedEvent<T>> {
        self.list.item_removed()
    }

    /// Returns the stream of replacements.
    pub fn item_replaced(&self) -> EventStream<ItemReplacedEvent<T>> {
        self.list.item_replaced()
    }

    /// Returns the stream that fires after a reset of the view.
    pub fn reset(&self) -> EventStream<()> {
        self.list.reset()
    }

    /// Returns the local `Count` property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.list.property_changed()
    }

    /// Returns the number of items.
    pub fn len(&self) -> usize {
        self.list.len()
    }

    /// Reports whether the view has no items.
    pub fn is_empty(&self) -> bool {
        self.list.is_empty()
    }

    /// Returns the item at `index`, if present.
    pub fn get(&self, index: usize) -> Option<T> {
        self.list.get(index)
    }

    /// Returns an ordered snapshot of all items.
    pub fn to_vec(&self) -> Vec<T> {
        self.list.to_vec()
    }
}

impl<T: Clone + Send + 'static> IntoIterator for &ReadOnlyObservableList<T> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.to_vec().into_iter()
    }
}

/// Insertion-ordered dictionary keys and values, a hash index, and a write
/// counter.
///
/// Key comparisons run user `PartialEq` code, so the dictionaries compare
/// keys against a shared snapshot of `keys` with no lock held and commit only
/// when `revision` still matches the snapshot; otherwise they search again
/// (the `FormVm::set_model` pattern). Taking the snapshot clones one `Arc`,
/// not the keys (#765). A key is hashed with no lock held before the search.
/// The search compares only the entries in that hash's bucket, so a lookup
/// makes O(1) comparisons on average (#1296). Replaced and removed keys and
/// values, and a key snapshot that a write displaced, are dropped after the
/// change is published, with no lock held (#1295).
///
/// The dictionaries store each value as a [`StoredValue`], behind its own
/// lock, which no write takes. A reader copies the value's handle under the
/// dictionary lock and runs `V::clone` after it releases that lock, so a
/// clone may read or write the dictionary (#1276).
struct DictionaryEntries<K, V> {
    keys: Shared<K>,
    values: Vec<V>,
    /// The hash of each key, in entry order.
    hashes: Vec<u64>,
    /// The entry positions of each key hash, in ascending order.
    buckets: HashMap<u64, Vec<usize>>,
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
            hashes: Vec::new(),
            buckets: HashMap::new(),
            revision: 0,
        }
    }
}

impl<K: Clone, V> DictionaryEntries<K, V> {
    /// Appends an entry and returns its index.
    fn push(&mut self, key: K, hash: u64, value: V, retired: &mut Retired<K>) -> usize {
        let index = self.values.len();
        cow_mut(&mut self.keys, retired).push(key);
        self.values.push(value);
        self.hashes.push(hash);
        self.buckets.entry(hash).or_default().push(index);
        index
    }

    /// Removes and returns the entry at `index`. The bucket positions of the
    /// later entries shift down by one, so a removal is O(n).
    fn remove(&mut self, index: usize, retired: &mut Retired<K>) -> (K, V) {
        let key = cow_mut(&mut self.keys, retired).remove(index);
        let value = self.values.remove(index);
        let hash = self.hashes.remove(index);
        if let Some(bucket) = self.buckets.get_mut(&hash) {
            bucket.retain(|position| *position != index);
            if bucket.is_empty() {
                self.buckets.remove(&hash);
            }
        }
        for (position, hash) in self.hashes.iter().enumerate().skip(index) {
            if let Some(slot) = self
                .buckets
                .get_mut(hash)
                .and_then(|bucket| bucket.iter_mut().find(|slot| **slot == position + 1))
            {
                *slot = position;
            }
        }
        (key, value)
    }

    /// Empties the entries and returns the keys and values, for the caller to
    /// drop after it releases the lock.
    fn take(&mut self) -> (Shared<K>, Vec<V>) {
        self.hashes.clear();
        self.buckets.clear();
        (
            std::mem::take(&mut self.keys),
            std::mem::take(&mut self.values),
        )
    }
}

impl<K, V> DictionaryEntries<K, V> {
    /// Returns the key snapshot and the positions whose key has `hash`.
    fn candidates(&self, hash: u64) -> (Shared<K>, Vec<usize>) {
        (
            Arc::clone(&self.keys),
            self.buckets.get(&hash).cloned().unwrap_or_default(),
        )
    }
}

/// Returns the first candidate whose key `matches`. It runs with no lock
/// held. The key snapshot drops here, with no lock held, so a commit after
/// the search does not copy the keys.
fn search<K>(
    keys: Shared<K>,
    candidates: Vec<usize>,
    mut matches: impl FnMut(&K) -> bool,
) -> Option<usize> {
    let found = candidates
        .into_iter()
        .find(|position| matches(&keys[*position]));
    drop(keys);
    found
}

/// Returns the shared key snapshot. The caller drops it with no lock held.
fn key_snapshot<K, V>(inner: &Mutex<DictionaryEntries<K, V>>) -> Shared<K> {
    Arc::clone(&lock(inner).keys)
}

/// Finds the first key with `hash` that `matches`, running it with no lock
/// held, and returns the revision that the search saw.
fn locate_key<K, V>(
    inner: &Mutex<DictionaryEntries<K, V>>,
    hash: u64,
    matches: impl FnMut(&K) -> bool,
) -> (u64, Option<usize>) {
    let (revision, (keys, candidates)) = {
        let inner = lock(inner);
        (inner.revision, inner.candidates(hash))
    };
    (revision, search(keys, candidates, matches))
}

/// Returns the stored value at `index` when no write happened since
/// `revision`, or `None` inside `Some` when `index` is `None`. Returns `None`
/// when a write happened, so the caller searches again. No user code runs.
fn stored_value_at<K, V>(
    inner: &Mutex<DictionaryEntries<K, StoredValue<V>>>,
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
    inner: Arc<Mutex<DictionaryEntries<K, StoredValue<V>>>>,
    hasher: RandomState,
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
            hasher: RandomState::new(),
            hub,
            owner_id,
        }
    }

    fn locate(&self, key: &K, hash: u64) -> (u64, Option<usize>) {
        locate_key(&self.inner, hash, |candidate| candidate == key)
    }

    /// Adds `key` or replaces its existing value in place.
    pub fn insert(&self, key: K, value: V) {
        let hash = self.hasher.hash_one(&key);
        let mut entry = Some((key, value));
        let ((action, replaced, (old_index, new_index)), retired) = loop {
            let (revision, index) = self.locate(&entry.as_ref().expect("entry pending").0, hash);
            let committed = commit_entries(&self.inner, revision, |entries, retired| {
                let (key, value) = entry.take().expect("entry pending");
                match index {
                    // The stored key stays; the argument key is returned so
                    // that it drops after the lock is released.
                    // Replace keeps the entry in place, so both positions
                    // are its index (spec/21 §2.4 and §4.7, ADR-0193).
                    Some(index) => (
                        CollectionChangeAction::Replace,
                        Some((
                            key,
                            std::mem::replace(&mut entries.values[index], store_value(value)),
                        )),
                        (Some(index), Some(index)),
                    ),
                    None => {
                        let position = entries.push(key, hash, store_value(value), retired);
                        // Add carries its insertion position (spec/21 §2.4).
                        (CollectionChangeAction::Add, None, (None, Some(position)))
                    }
                }
            });
            if let Some(committed) = committed {
                break committed;
            }
        };
        publish_then_drop((replaced, retired), || {
            self.publish_at(action, old_index, new_index);
        });
    }

    /// Returns the value associated with `key`, if present.
    ///
    /// `V::clone` runs with no dictionary lock held, so a clone may read this
    /// dictionary (#1276). Clones of one stored value take turns: a
    /// `V::clone` must not wait for another clone of the same value, and must
    /// not read that value again on its own thread.
    pub fn get(&self, key: &K) -> Option<V> {
        let hash = self.hasher.hash_one(key);
        loop {
            let (revision, index) = self.locate(key, hash);
            if let Some(stored) = stored_value_at(&self.inner, revision, index) {
                return stored.map(|stored| clone_locked(&stored));
            }
        }
    }

    /// Removes and returns the value associated with `key`.
    ///
    /// If another thread is cloning the removed value in [`get`](Self::get),
    /// `remove` waits for that clone and then returns a clone of its own. The
    /// stored value then drops on whichever of the two threads releases it
    /// last.
    pub fn remove(&self, key: &K) -> Option<V> {
        let hash = self.hasher.hash_one(key);
        let removed = loop {
            let (revision, index) = self.locate(key, hash);
            let Some(index) = index else {
                break None;
            };
            if let Some(removed) = commit_entries(&self.inner, revision, |entries, retired| {
                entries.remove(index, retired)
            }) {
                break Some((index, removed));
            }
        };
        let (index, ((removed_key, value), retired)) = removed?;
        // The removed key drops after the change is published (#1295).
        // Remove carries the entry's position before the removal (spec/21
        // §2.4 and §4.7, ADR-0193).
        publish_then_drop((removed_key, retired), || {
            self.publish_at(CollectionChangeAction::Remove, Some(index), None);
        });
        Some(take_value(value))
    }

    /// Clears a non-empty dictionary and publishes one reset.
    pub fn clear(&self) {
        let removed = {
            let mut inner = lock(&self.inner);
            inner.revision = inner.revision.wrapping_add(1);
            inner.take()
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
        self.publish_at(action, None, None);
    }

    fn publish_at(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
    ) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                sender_name: "ObservableDictionary".to_string(),
                property_name: "items".to_string(),
                action,
                old_index,
                new_index,
            }));
    }
}

/// One change to a key view, applied in commit order.
enum KeyViewChange<K> {
    Push(K),
    RemoveAt(usize),
    Clear,
}

/// One committed dictionary mutation that waits for delivery.
struct DictionaryChange<K1, K2> {
    action: CollectionChangeAction,
    /// For an Add or a Replace: the entry's identity, its commit position
    /// and the revision of the commit.
    entry: Option<(u64, usize, u64)>,
    /// For a Remove: the entry's position just before the removal.
    removed_at: Option<usize>,
    keys1: Option<KeyViewChange<K1>>,
    keys2: Option<KeyViewChange<K2>>,
}

/// The entries of a multi-key dictionary and the distinct keys of each axis.
struct MultiDictionaryState<K1, K2, V> {
    entries: DictionaryEntries<(K1, K2), StoredValue<V>>,
    /// Each entry's position in the `Keys1` and `Keys2` views.
    slots: Vec<(usize, usize)>,
    /// Each entry's identity, which locates an entry after a later write.
    ids: Vec<u64>,
    next_id: u64,
    /// The distinct first keys in view order, each with its entry count.
    axis1: DictionaryEntries<K1, usize>,
    /// The distinct second keys in view order, each with its entry count.
    axis2: DictionaryEntries<K2, usize>,
}

impl<K1, K2, V> Default for MultiDictionaryState<K1, K2, V> {
    fn default() -> Self {
        Self {
            entries: DictionaryEntries::default(),
            slots: Vec::new(),
            ids: Vec::new(),
            next_id: 0,
            axis1: DictionaryEntries::default(),
            axis2: DictionaryEntries::default(),
        }
    }
}

/// Removes one entry of the distinct key at `slot` and returns the view
/// change when the key's last entry is gone.
fn release_axis_key<K: Clone>(
    axis: &mut DictionaryEntries<K, usize>,
    slot: usize,
    retired: &mut Retired<K>,
) -> Option<(KeyViewChange<K>, K)> {
    axis.values[slot] -= 1;
    if axis.values[slot] > 0 {
        return None;
    }
    let (key, _) = axis.remove(slot, retired);
    Some((KeyViewChange::RemoveAt(slot), key))
}

/// The queue of committed changes and the thread that delivers them.
struct DictionaryDelivery<K1, K2> {
    state: Mutex<DictionaryDeliveryState<K1, K2>>,
    ready: Condvar,
}

struct DictionaryDeliveryState<K1, K2> {
    pending: VecDeque<DictionaryChange<K1, K2>>,
    draining_owner: Option<ThreadId>,
    /// The threads that wait for the delivery to end.
    waiters: usize,
}

impl<K1, K2> DictionaryDeliveryState<K1, K2> {
    fn waiters(&mut self) -> &mut usize {
        &mut self.waiters
    }
}

impl<K1, K2> Default for DictionaryDelivery<K1, K2> {
    fn default() -> Self {
        Self {
            state: Mutex::new(DictionaryDeliveryState {
                pending: VecDeque::new(),
                draining_owner: None,
                waiters: 0,
            }),
            ready: Condvar::new(),
        }
    }
}

impl<K1, K2> DictionaryDelivery<K1, K2> {
    /// The delivery, as one wait-for graph resource (spec/03 §4.1).
    fn resource(&self) -> Resource {
        Resource::DictionaryDelivery(std::ptr::from_ref(self) as usize)
    }

    /// Ends the delivery. The edges of the waiting threads are removed
    /// before they wake (spec/03 §4.1 rule 4).
    fn release(&self, state: &mut DictionaryDeliveryState<K1, K2>) {
        state.draining_owner = None;
        if state.waiters > 0 {
            waits().release_waiters(self.resource(), &[]);
        }
        self.ready.notify_all();
    }
}

/// Admits one mutation of a multi-key dictionary.
///
/// One thread at a time mutates and delivers; another thread waits until the
/// delivery ends, and records that wait in the wait-for graph. A nested
/// mutation on the delivering thread, from a key comparison or a subscriber,
/// commits at once and queues its change behind the change being delivered.
/// When the admission that owns the delivery drops, it delivers every queued
/// change in commit order. When the wait would close a wait-for cycle, the
/// waiting thread does not wait: it commits and queues its change for the
/// delivering thread, as a refused hub `send` does (spec/03 §4.1).
struct DictionaryAdmission<'a, K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    dictionary: &'a ObservableMultiDictionary<K1, K2, V>,
    current: ThreadId,
    owns_drain: bool,
}

impl<K1, K2, V> Drop for DictionaryAdmission<'_, K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    fn drop(&mut self) {
        if self.owns_drain || self.dictionary.claim_released_drain(self.current) {
            self.dictionary.drain(self.current);
        }
    }
}

#[derive(Clone)]
/// An observable dictionary keyed by an ordered pair of keys (spec/21 §4).
///
/// Each effective mutation commits the entries and the count, then updates
/// the live [`keys1`](Self::keys1) and [`keys2`](Self::keys2) views, then
/// sends one `CollectionChangedMessage` on the local
/// [`collection_changed`](Self::collection_changed) stream, then the same
/// message to the hub when one was given (ADR-0177, ADR-0208).
pub struct ObservableMultiDictionary<K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    inner: Arc<Mutex<MultiDictionaryState<K1, K2, V>>>,
    delivery: Arc<DictionaryDelivery<K1, K2>>,
    keys1: ObservableList<K1>,
    keys2: ObservableList<K2>,
    hasher: RandomState,
    local: MessageHub,
    hub: Option<MessageHub>,
    owner_id: usize,
}

/// The keys that one multi-key dictionary removal displaced: the entry's key
/// pair, each distinct key whose last entry it was, and the key snapshots
/// that the write displaced. They drop after the change is delivered (#1295).
type RemovedEntryKeys<K1, K2> = (
    ((K1, K2), Option<K1>, Option<K2>),
    (Retired<(K1, K2)>, Retired<K1>, Retired<K2>),
);

/// The result of one search: the revision it saw, the entry, and, for a
/// missing entry, the distinct-key slots of both keys.
struct MultiLocation {
    revision: u64,
    entry: Option<usize>,
    slot1: Option<usize>,
    slot2: Option<usize>,
}

impl<K1, K2, V> ObservableMultiDictionary<K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    /// Creates an empty multi-key dictionary without a message hub. Its
    /// mutations reach only the key views and the local stream.
    pub fn new(owner_id: usize) -> Self {
        Self::build(owner_id, None)
    }

    /// Creates an empty multi-key dictionary that also publishes its changes
    /// to `hub`.
    pub fn with_hub(owner_id: usize, hub: MessageHub) -> Self {
        Self::build(owner_id, Some(hub))
    }

    fn build(owner_id: usize, hub: Option<MessageHub>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(MultiDictionaryState::default())),
            delivery: Arc::new(DictionaryDelivery::default()),
            keys1: ObservableList::new(owner_id),
            keys2: ObservableList::new(owner_id),
            hasher: RandomState::new(),
            local: MessageHub::new(),
            hub,
            owner_id,
        }
    }

    /// Returns the local collection-change stream. It receives each
    /// `CollectionChangedMessage` before the hub does.
    pub fn collection_changed(&self) -> MessageHub {
        self.local.clone()
    }

    /// Hashes both keys, and the pair from the two key hashes, with no lock
    /// held.
    fn hashes(&self, key1: &K1, key2: &K2) -> (u64, u64, u64) {
        let hash1 = self.hasher.hash_one(key1);
        let hash2 = self.hasher.hash_one(key2);
        (hash1, hash2, self.hasher.hash_one((hash1, hash2)))
    }

    /// Searches the entry and, when `with_slots` is set and the entry is
    /// missing, the distinct-key slots, with no lock held.
    fn locate(
        &self,
        key1: &K1,
        key2: &K2,
        (hash1, hash2, hash): (u64, u64, u64),
        with_slots: bool,
    ) -> MultiLocation {
        let (revision, entries, axis1, axis2) = {
            let inner = lock(&self.inner);
            (
                inner.entries.revision,
                inner.entries.candidates(hash),
                with_slots.then(|| inner.axis1.candidates(hash1)),
                with_slots.then(|| inner.axis2.candidates(hash2)),
            )
        };
        let entry = search(entries.0, entries.1, |(candidate1, candidate2)| {
            candidate1 == key1 && candidate2 == key2
        });
        let (slot1, slot2) = match (entry, axis1, axis2) {
            (None, Some(axis1), Some(axis2)) => (
                search(axis1.0, axis1.1, |candidate| candidate == key1),
                search(axis2.0, axis2.1, |candidate| candidate == key2),
            ),
            _ => (None, None),
        };
        MultiLocation {
            revision,
            entry,
            slot1,
            slot2,
        }
    }

    /// Admits one mutation. A thread waits while another thread delivers,
    /// and records the wait in the wait-for graph. When the wait would close
    /// a cycle, the mutation is admitted without the delivery: it commits and
    /// queues its change for the delivering thread (spec/03 §4.1, ADR-0208).
    fn admit(&self) -> DictionaryAdmission<'_, K1, K2, V> {
        let current = thread::current().id();
        let mut state = lock(&self.delivery.state);
        while let Some(owner) = state.draining_owner.filter(|owner| *owner != current) {
            let refused;
            (state, refused) = wait_for_owner(
                &self.delivery.state,
                &self.delivery.ready,
                state,
                DictionaryDeliveryState::waiters,
                self.delivery.resource(),
                owner,
            );
            if refused {
                return DictionaryAdmission {
                    dictionary: self,
                    current,
                    owns_drain: false,
                };
            }
        }
        let owns_drain = state.draining_owner.is_none();
        if owns_drain {
            state.draining_owner = Some(current);
        }
        DictionaryAdmission {
            dictionary: self,
            current,
            owns_drain,
        }
    }

    /// Takes the delivery when it was released with changes still queued. A
    /// mutation whose wait was refused queues its change for the delivering
    /// thread; if that thread ended its delivery first, the mutation
    /// delivers the change itself.
    fn claim_released_drain(&self, current: ThreadId) -> bool {
        let mut state = lock(&self.delivery.state);
        if state.draining_owner.is_some() || state.pending.is_empty() {
            return false;
        }
        state.draining_owner = Some(current);
        true
    }

    /// Queues a committed change. The caller holds the entries lock, so the
    /// queue order is the commit order, also when a mutation whose wait was
    /// refused commits beside the delivering thread.
    fn enqueue(&self, change: DictionaryChange<K1, K2>) {
        lock(&self.delivery.state).pending.push_back(change);
    }

    /// Delivers every queued change in commit order, then ends the delivery.
    /// While the thread unwinds, it applies the queued key-view changes with
    /// no notification, so the views stay in step with the entries.
    fn drain(&self, current: ThreadId) {
        loop {
            let change = {
                let mut state = lock(&self.delivery.state);
                debug_assert_eq!(state.draining_owner, Some(current));
                let Some(change) = state.pending.pop_front() else {
                    self.delivery.release(&mut state);
                    return;
                };
                change
            };
            if thread::panicking() {
                // The thread unwinds from user code under the admission.
                self.apply_silently(change);
            } else if let Err(error) = catch_unwind(AssertUnwindSafe(|| self.deliver(change))) {
                // The streams isolate subscriber panics, so this is a hub
                // debug assertion. The views still follow the entries, and
                // the delivery ends before the panic resumes.
                self.drain_silently(current);
                resume_unwind(error);
            }
        }
    }

    /// Applies every queued key-view change with no notification, then ends
    /// the delivery.
    fn drain_silently(&self, current: ThreadId) {
        loop {
            let change = {
                let mut state = lock(&self.delivery.state);
                debug_assert_eq!(state.draining_owner, Some(current));
                let Some(change) = state.pending.pop_front() else {
                    self.delivery.release(&mut state);
                    return;
                };
                change
            };
            self.apply_silently(change);
        }
    }

    fn apply_silently(&self, change: DictionaryChange<K1, K2>) {
        fn apply<K: Clone + Send + 'static>(list: &ObservableList<K>, change: KeyViewChange<K>) {
            match change {
                KeyViewChange::Push(key) => {
                    let end = list.len();
                    let _ = list.insert_silent(end, key);
                }
                KeyViewChange::RemoveAt(position) => drop(list.remove_at_silent(position)),
                KeyViewChange::Clear => drop(list.take_silent()),
            }
        }
        if let Some(view) = change.keys1 {
            apply(&self.keys1, view);
        }
        if let Some(view) = change.keys2 {
            apply(&self.keys2, view);
        }
    }

    /// Updates the key views, then sends the local event and the hub message
    /// (spec/21 §4.2 and §4.6).
    fn deliver(&self, change: DictionaryChange<K1, K2>) {
        fn apply<K: Clone + Send + 'static>(list: &ObservableList<K>, change: KeyViewChange<K>) {
            match change {
                KeyViewChange::Push(key) => list.push(key),
                KeyViewChange::RemoveAt(position) => drop(list.remove_at(position)),
                KeyViewChange::Clear => list.clear(),
            }
        }
        if let Some(view) = change.keys1 {
            apply(&self.keys1, view);
        }
        if let Some(view) = change.keys2 {
            apply(&self.keys2, view);
        }
        // Remove carries the entry's position before the removal. Add and
        // Replace carry the entry's position when each message is sent, and a
        // Replace's positions are equal (spec/21 §4.7, ADR-0193).
        let message = |position: Option<usize>| {
            let (old_index, new_index) = match change.action {
                CollectionChangeAction::Add => (None, position),
                CollectionChangeAction::Replace => (position, position),
                CollectionChangeAction::Remove => (change.removed_at, None),
                _ => (None, None),
            };
            Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                sender_name: "ObservableMultiDictionary".to_string(),
                property_name: "items".to_string(),
                action: change.action.clone(),
                old_index,
                new_index,
            })
        };
        self.local.send(message(self.position(change.entry)));
        if let Some(hub) = &self.hub {
            hub.send(message(self.position(change.entry)));
        }
    }

    /// Returns an added or replaced entry's position now: its commit
    /// position when no later write happened, otherwise its current position,
    /// or `None` when a subscriber removed it (spec/21 §2.4 and §4.7, #733).
    fn position(&self, entry: Option<(u64, usize, u64)>) -> Option<usize> {
        let (id, position, revision) = entry?;
        let inner = lock(&self.inner);
        if inner.entries.revision == revision {
            Some(position)
        } else {
            inner.ids.iter().position(|candidate| *candidate == id)
        }
    }

    /// Adds a new key pair, rejecting a pair that is already present without
    /// changing the dictionary (spec/21 §4.1 `Add`).
    pub fn add(&self, key1: K1, key2: K2, value: V) -> VmxResult<()> {
        let admission = self.admit();
        let hashes = self.hashes(&key1, &key2);
        let mut entry = Some((key1, key2, value));
        loop {
            let pending = entry.as_ref().expect("entry pending");
            let location = self.locate(&pending.0, &pending.1, hashes, true);
            if location.entry.is_some() {
                drop(admission);
                return Err(VmxError::InvalidArgument("duplicate key pair".to_string()));
            }
            if self.commit_insert(&mut entry, hashes, &location) {
                break;
            }
        }
        drop(admission);
        Ok(())
    }

    /// Adds a key pair or replaces its existing value in place.
    pub fn insert(&self, key1: K1, key2: K2, value: V) {
        let admission = self.admit();
        let hashes = self.hashes(&key1, &key2);
        let mut entry = Some((key1, key2, value));
        let mut replaced = None;
        loop {
            let pending = entry.as_ref().expect("entry pending");
            let location = self.locate(&pending.0, &pending.1, hashes, true);
            let committed = match location.entry {
                Some(index) => {
                    replaced = self.commit_replace(&mut entry, index, location.revision);
                    replaced.is_some()
                }
                None => self.commit_insert(&mut entry, hashes, &location),
            };
            if committed {
                break;
            }
        }
        // The old value and the argument keys drop after the change is
        // delivered (#1295).
        publish_then_drop(replaced, || drop(admission));
    }

    /// Replaces the value at `index` when no write happened since `revision`.
    /// The stored keys stay. It returns the argument keys and the old value,
    /// which the caller drops after the change is delivered (#1295).
    fn commit_replace(
        &self,
        entry: &mut Option<(K1, K2, V)>,
        index: usize,
        revision: u64,
    ) -> Option<(K1, K2, StoredValue<V>)> {
        let replaced = {
            let mut inner = lock(&self.inner);
            if inner.entries.revision != revision {
                return None;
            }
            inner.entries.revision = inner.entries.revision.wrapping_add(1);
            let (key1, key2, value) = entry.take().expect("entry pending");
            let replaced = (
                key1,
                key2,
                std::mem::replace(&mut inner.entries.values[index], store_value(value)),
            );
            let entry = (inner.ids[index], index, inner.entries.revision);
            self.enqueue(DictionaryChange {
                action: CollectionChangeAction::Replace,
                entry: Some(entry),
                removed_at: None,
                keys1: None,
                keys2: None,
            });
            replaced
        };
        Some(replaced)
    }

    /// Appends the pending entry when no write happened since the search,
    /// and queues its key-view changes. A key that is new to its view is
    /// cloned before the lock is taken: one clone for the distinct-key index
    /// and one for the view.
    fn commit_insert(
        &self,
        entry: &mut Option<(K1, K2, V)>,
        (hash1, hash2, hash): (u64, u64, u64),
        location: &MultiLocation,
    ) -> bool {
        let pending = entry.as_ref().expect("entry pending");
        let new1 = location
            .slot1
            .is_none()
            .then(|| (pending.0.clone(), pending.0.clone()));
        let new2 = location
            .slot2
            .is_none()
            .then(|| (pending.1.clone(), pending.1.clone()));
        let mut retired = (None, None, None);
        {
            let mut inner = lock(&self.inner);
            if inner.entries.revision != location.revision {
                drop(inner);
                drop((new1, new2));
                return false;
            }
            let state = &mut *inner;
            state.entries.revision = state.entries.revision.wrapping_add(1);
            let (key1, key2, value) = entry.take().expect("entry pending");
            let position =
                state
                    .entries
                    .push((key1, key2), hash, store_value(value), &mut retired.0);
            let (slot1, keys1) = match (location.slot1, new1) {
                (Some(slot), _) => {
                    state.axis1.values[slot] += 1;
                    (slot, None)
                }
                (None, Some((stored, view))) => (
                    state.axis1.push(stored, hash1, 1, &mut retired.1),
                    Some(KeyViewChange::Push(view)),
                ),
                (None, None) => unreachable!("a new first key is cloned"),
            };
            let (slot2, keys2) = match (location.slot2, new2) {
                (Some(slot), _) => {
                    state.axis2.values[slot] += 1;
                    (slot, None)
                }
                (None, Some((stored, view))) => (
                    state.axis2.push(stored, hash2, 1, &mut retired.2),
                    Some(KeyViewChange::Push(view)),
                ),
                (None, None) => unreachable!("a new second key is cloned"),
            };
            state.slots.push((slot1, slot2));
            let id = state.next_id;
            state.next_id = state.next_id.wrapping_add(1);
            state.ids.push(id);
            let added = (id, position, state.entries.revision);
            self.enqueue(DictionaryChange {
                action: CollectionChangeAction::Add,
                entry: Some(added),
                removed_at: None,
                keys1,
                keys2,
            });
        }
        drop(retired);
        true
    }

    /// Removes every entry and publishes one `Reset`, as every flavor's
    /// dictionary does, even when it was already empty.
    pub fn clear(&self) {
        let admission = self.admit();
        let removed = {
            let mut inner = lock(&self.inner);
            let state = &mut *inner;
            state.entries.revision = state.entries.revision.wrapping_add(1);
            state.slots.clear();
            state.ids.clear();
            self.enqueue(DictionaryChange {
                action: CollectionChangeAction::Reset,
                entry: None,
                removed_at: None,
                keys1: Some(KeyViewChange::Clear),
                keys2: Some(KeyViewChange::Clear),
            });
            (state.entries.take(), state.axis1.take(), state.axis2.take())
        };
        // The entries drop after the reset is delivered (#1295).
        publish_then_drop(removed, || drop(admission));
    }

    /// Returns a snapshot of every entry in insertion order.
    ///
    /// Keys and values are cloned with no dictionary lock held, so a clone
    /// may read this dictionary (#1276). Clones of one stored value take
    /// turns, as in [`get`](Self::get).
    pub fn entries(&self) -> Vec<(K1, K2, V)> {
        let (keys, values) = {
            let inner = lock(&self.inner);
            (
                Arc::clone(&inner.entries.keys),
                inner.entries.values.clone(),
            )
        };
        keys.iter()
            .zip(&values)
            .map(|((key1, key2), value)| (key1.clone(), key2.clone(), clone_locked(value)))
            .collect()
    }

    /// Removes and returns the value associated with a key pair.
    ///
    /// If another thread is cloning the removed value in [`get`](Self::get)
    /// or [`entries`](Self::entries), `remove` waits for that clone and then
    /// returns a clone of its own. The stored value then drops on whichever of
    /// the two threads releases it last.
    pub fn remove(&self, key1: &K1, key2: &K2) -> Option<V> {
        let admission = self.admit();
        let hashes = self.hashes(key1, key2);
        let removed = loop {
            let location = self.locate(key1, key2, hashes, false);
            let Some(index) = location.entry else {
                break None;
            };
            if let Some(removed) = self.commit_remove(index, location.revision) {
                break Some(removed);
            }
        };
        let Some((value, displaced)) = removed else {
            drop(admission);
            return None;
        };
        // The removed keys drop after the change is delivered (#1295).
        publish_then_drop(displaced, || drop(admission));
        Some(take_value(value))
    }

    /// Removes the entry at `index` when no write happened since `revision`,
    /// and queues its key-view changes. It returns the removed value and the
    /// removed keys, which the caller drops after the change is delivered.
    fn commit_remove(
        &self,
        index: usize,
        revision: u64,
    ) -> Option<(StoredValue<V>, RemovedEntryKeys<K1, K2>)> {
        let mut retired = (None, None, None);
        let (value, removed) = {
            let mut inner = lock(&self.inner);
            if inner.entries.revision != revision {
                return None;
            }
            let state = &mut *inner;
            state.entries.revision = state.entries.revision.wrapping_add(1);
            let (keys, value) = state.entries.remove(index, &mut retired.0);
            let (slot1, slot2) = state.slots.remove(index);
            state.ids.remove(index);
            let released1 = release_axis_key(&mut state.axis1, slot1, &mut retired.1);
            let released2 = release_axis_key(&mut state.axis2, slot2, &mut retired.2);
            for (entry1, entry2) in &mut state.slots {
                if released1.is_some() && *entry1 > slot1 {
                    *entry1 -= 1;
                }
                if released2.is_some() && *entry2 > slot2 {
                    *entry2 -= 1;
                }
            }
            let (keys1, key1) = released1.unzip();
            let (keys2, key2) = released2.unzip();
            self.enqueue(DictionaryChange {
                action: CollectionChangeAction::Remove,
                entry: None,
                removed_at: Some(index),
                keys1,
                keys2,
            });
            (value, (keys, key1, key2))
        };
        Some((value, (removed, retired)))
    }

    /// Returns the value associated with a key pair, if present.
    ///
    /// `V::clone` runs with no dictionary lock held, as in
    /// [`ObservableDictionary::get`].
    pub fn get(&self, key1: &K1, key2: &K2) -> Option<V> {
        let hashes = self.hashes(key1, key2);
        loop {
            let location = self.locate(key1, key2, hashes, false);
            if let Some(stored) = self.stored_at(&location) {
                return stored.map(|stored| clone_locked(&stored));
            }
        }
    }

    /// Reports whether a key pair is present. It clones no value.
    pub fn contains_key(&self, key1: &K1, key2: &K2) -> bool {
        let hashes = self.hashes(key1, key2);
        loop {
            let location = self.locate(key1, key2, hashes, false);
            if let Some(stored) = self.stored_at(&location) {
                return stored.is_some();
            }
        }
    }

    /// Returns the stored value that `location` found when no write happened
    /// since its search, or `None` inside `Some` when it found no entry.
    /// Returns `None` when a write happened, so the caller searches again. No
    /// user code runs.
    fn stored_at(&self, location: &MultiLocation) -> Option<Option<StoredValue<V>>> {
        let inner = lock(&self.inner);
        (inner.entries.revision == location.revision).then(|| {
            location
                .entry
                .map(|index| Arc::clone(&inner.entries.values[index]))
        })
    }

    /// Returns the number of key-pair memberships.
    pub fn count(&self) -> usize {
        lock(&self.inner).entries.values.len()
    }

    /// Returns the live, read-only view of the distinct first-dimension keys,
    /// in the order of their first appearance (spec/21 §4.2).
    pub fn keys1(&self) -> ReadOnlyObservableList<K1> {
        ReadOnlyObservableList::new(self.keys1.clone())
    }

    /// Returns the live, read-only view of the distinct second-dimension
    /// keys, in the order of their first appearance (spec/21 §4.2).
    pub fn keys2(&self) -> ReadOnlyObservableList<K2> {
        ReadOnlyObservableList::new(self.keys2.clone())
    }
}
