//! Keyed active-mode and modal-precedence state.
//!
//! Spec: `spec/20-discriminator-vm.md`; ADR-0051.

use super::*;

#[derive(Clone)]
/// Keyed active-mode state with LIFO modal override restoration.
pub struct DiscriminatorVm<K: Clone + Eq + Hash + Send + 'static> {
    current_key: Arc<Mutex<K>>,
    allowed: Arc<Mutex<HashSet<K>>>,
    active_changed: MessageHub,
    modal_stack: Arc<Mutex<Vec<K>>>,
}

impl<K: Clone + Eq + Hash + Send + 'static> DiscriminatorVm<K> {
    /// Creates discriminator state with `initial` active and an allowed-key set.
    pub fn new(initial: K, allowed: impl IntoIterator<Item = K>) -> Self {
        let mut allowed_set = allowed.into_iter().collect::<HashSet<_>>();
        allowed_set.insert(initial.clone());
        Self {
            current_key: Arc::new(Mutex::new(initial)),
            allowed: Arc::new(Mutex::new(allowed_set)),
            active_changed: MessageHub::new(),
            modal_stack: Arc::new(Mutex::new(Vec::new())),
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

    /// Sets the current key after validating it against the allowed set.
    pub fn set_current_key(&self, key: K) -> VmxResult<()> {
        self.set_active_key(key)
    }

    /// Sets the active key and publishes one effective change.
    pub fn set_active_key(&self, key: K) -> VmxResult<()> {
        if !lock(&self.allowed).contains(&key) {
            return Err(VmxError::InvalidArgument(
                "unknown discriminator key".to_string(),
            ));
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
        Ok(())
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
    pub fn modal_open(&self, key: K) -> VmxResult<()> {
        lock(&self.allowed).insert(key.clone());
        let previous = self.active_key();
        lock(&self.modal_stack).push(previous);
        self.set_active_key(key)
    }

    /// Closes the top modal scope and restores its prior key.
    pub fn modal_close(&self) -> VmxResult<()> {
        let previous = lock(&self.modal_stack).pop();
        if let Some(previous) = previous {
            self.set_active_key(previous)?;
        }
        Ok(())
    }
}
