//! Keyed active-mode and modal-precedence state.
//!
//! Spec: `spec/22-discriminator-vm.md`; ADR-0051.

use super::{lock, Arc, Message, MessageHub, Mutex};

#[derive(Clone)]
/// Keyed active-mode state with LIFO modal override restoration.
pub struct DiscriminatorVm<K: Clone + PartialEq + Send + 'static> {
    current_key: Arc<Mutex<K>>,
    active_changed: MessageHub,
    modal_stack: Arc<Mutex<Vec<K>>>,
    disposed: Arc<Mutex<bool>>,
}

impl<K: Clone + PartialEq + Send + 'static> DiscriminatorVm<K> {
    /// Creates discriminator state with `initial` active.
    pub fn new(initial: K) -> Self {
        Self {
            current_key: Arc::new(Mutex::new(initial)),
            active_changed: MessageHub::new(),
            modal_stack: Arc::new(Mutex::new(Vec::new())),
            disposed: Arc::new(Mutex::new(false)),
        }
    }

    /// Returns the current key.
    pub fn current_key(&self) -> K {
        lock(&self.current_key).clone()
    }

    /// Returns the active key.
    pub fn active_key(&self) -> K {
        self.current_key()
    }

    /// Sets the current key.
    pub fn set_current_key(&self, key: K) {
        self.set_active_key(key)
    }

    /// Sets the active key and publishes one effective change.
    pub fn set_active_key(&self, key: K) {
        if *lock(&self.disposed) {
            return;
        }
        let changed = {
            let mut current = lock(&self.current_key);
            if *current == key {
                false
            } else {
                *current = key;
                true
            }
        };
        if changed {
            self.active_changed.send(Message::Custom {
                sender_id: 0,
                name: "active_changed".to_string(),
            });
        }
    }

    /// Reports whether `key` is active.
    pub fn is_active(&self, key: &K) -> bool {
        lock(&self.current_key).eq(key)
    }

    /// Returns the hub that publishes effective active-key changes.
    pub fn active_changed(&self) -> MessageHub {
        self.active_changed.clone()
    }

    /// Pushes the prior key and activates a modal key.
    pub fn modal_open(&self, key: K) {
        if *lock(&self.disposed) {
            return;
        }
        let previous = self.active_key();
        lock(&self.modal_stack).push(previous);
        self.set_active_key(key)
    }

    /// Closes the top modal scope and restores its prior key.
    pub fn modal_close(&self) {
        if *lock(&self.disposed) {
            return;
        }
        let previous = lock(&self.modal_stack).pop();
        if let Some(previous) = previous {
            self.set_active_key(previous);
        }
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
        lock(&self.modal_stack).clear();
        self.active_changed.dispose();
    }
}
