//! Keyed active-mode and modal-precedence state.
//!
//! Spec: `spec/22-discriminator-vm.md`; ADR-0051.

use super::{lock, Arc, AtomicU64, Message, MessageHub, Mutex, Ordering, ValueStream};

/// The active key plus a counter of its replacements, so a setter that
/// compared keys on a copy can detect an intervening change.
struct ActiveKey<K> {
    key: K,
    generation: u64,
}

#[derive(Clone)]
/// Keyed active-mode state with LIFO modal override restoration.
pub struct DiscriminatorVm<K: Clone + PartialEq + Send + 'static> {
    current_key: Arc<Mutex<ActiveKey<K>>>,
    /// The active key's generation, stored under `current_key`; read without
    /// that lock when a publication checks that it is still current (#752).
    published_generation: Arc<AtomicU64>,
    active_changed: MessageHub,
    active_key_changes: ValueStream<K>,
    modal_stack: Arc<Mutex<Vec<K>>>,
    disposed: Arc<Mutex<bool>>,
}

impl<K: Clone + PartialEq + Send + 'static> DiscriminatorVm<K> {
    /// Creates discriminator state with `initial` active.
    pub fn new(initial: K) -> Self {
        Self {
            current_key: Arc::new(Mutex::new(ActiveKey {
                key: initial.clone(),
                generation: 0,
            })),
            published_generation: Arc::new(AtomicU64::new(0)),
            active_changed: MessageHub::new(),
            active_key_changes: ValueStream::hot(initial),
            modal_stack: Arc::new(Mutex::new(Vec::new())),
            disposed: Arc::new(Mutex::new(false)),
        }
    }

    /// Returns the current key.
    pub fn current_key(&self) -> K {
        lock(&self.current_key).key.clone()
    }

    /// Returns the active key.
    pub fn active_key(&self) -> K {
        self.current_key()
    }

    /// Sets the current key.
    pub fn set_current_key(&self, key: K) {
        self.set_active_key(key)
    }

    /// Sets the active key, abandons modal history, and publishes one effective change.
    pub fn set_active_key(&self, key: K) {
        if *lock(&self.disposed) {
            return;
        }
        let abandoned = std::mem::take(&mut *lock(&self.modal_stack));
        drop(abandoned);
        self.set_active_key_preserving_modals(key);
    }

    fn set_active_key_preserving_modals(&self, key: K) {
        // `PartialEq` runs on a copy with no lock held, so an `eq` may read
        // this discriminator; the install re-checks the generation and
        // compares again when another setter got there first.
        let installed = loop {
            let (generation, current) = {
                let active = lock(&self.current_key);
                (active.generation, active.key.clone())
            };
            if current == key {
                break None;
            }
            drop(current);
            let replaced = {
                let mut active = lock(&self.current_key);
                if active.generation != generation {
                    continue;
                }
                active.generation = active.generation.wrapping_add(1);
                self.published_generation
                    .store(active.generation, Ordering::Release);
                (
                    std::mem::replace(&mut active.key, key.clone()),
                    active.generation,
                )
            };
            drop(replaced.0);
            break Some(replaced.1);
        };
        if let Some(generation) = installed {
            // The key stream goes first: a hub subscriber that changes the key
            // again must not have its newer key overtaken by this one. A newer
            // setter that committed in the gap, on another thread or from the
            // replaced key's `Drop`, publishes its own key; this one is then
            // skipped, so the stream ends on the active key (#752).
            let current = Arc::clone(&self.published_generation);
            self.active_key_changes
                .send_if(key, move || current.load(Ordering::Acquire) == generation);
            self.active_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "DiscriminatorVm".to_string(),
                name: "active_changed".to_string(),
            });
        }
    }

    /// Reports whether `key` is active.
    pub fn is_active(&self, key: &K) -> bool {
        // Compare a copy, so no lock is held while `PartialEq` runs.
        self.current_key() == *key
    }

    /// Returns the hub that publishes effective active-key changes.
    ///
    /// Its messages carry no key; use [`active_key_changes`](Self::active_key_changes)
    /// to receive the new key with each change.
    pub fn active_changed(&self) -> MessageHub {
        self.active_changed.clone()
    }

    /// Returns a typed stream of the new active key, one value per effective
    /// change. It does not replay the current key to a new subscriber. When a
    /// newer change commits before an older one publishes, the older key is
    /// skipped, so the stream ends on the active key.
    pub fn active_key_changes(&self) -> ValueStream<K> {
        self.active_key_changes.clone()
    }

    /// Returns the number of saved modal frames.
    pub fn modal_depth(&self) -> usize {
        lock(&self.modal_stack).len()
    }

    /// Pushes the prior key and activates a modal key.
    pub fn modal_open(&self, key: K) {
        if *lock(&self.disposed) {
            return;
        }
        let previous = self.active_key();
        lock(&self.modal_stack).push(previous);
        self.set_active_key_preserving_modals(key)
    }

    /// Closes the top modal scope and restores its prior key.
    pub fn modal_close(&self) {
        if *lock(&self.disposed) {
            return;
        }
        let previous = lock(&self.modal_stack).pop();
        if let Some(previous) = previous {
            self.set_active_key_preserving_modals(previous);
        }
    }

    /// Releases all saved modal frames without changing the active key.
    pub fn clear_modals(&self) {
        if *lock(&self.disposed) {
            return;
        }
        // Saved keys are dropped after the lock is released: a user `Drop`
        // may read this discriminator.
        let frames = std::mem::take(&mut *lock(&self.modal_stack));
        drop(frames);
    }

    /// Completes the change stream and makes subsequent mutations inert.
    pub fn dispose(&self) {
        let should_dispose = {
            let mut disposed = lock(&self.disposed);
            if *disposed {
                false
            } else {
                *disposed = true;
                true
            }
        };
        if !should_dispose {
            return;
        }
        let frames = std::mem::take(&mut *lock(&self.modal_stack));
        drop(frames);
        self.active_changed.dispose();
        self.active_key_changes.dispose();
    }
}
