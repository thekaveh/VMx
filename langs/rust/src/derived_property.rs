//! Read-only and validated write-back derived properties.
//!
//! Spec: `spec/15-derived-properties.md`; ADR-0035.

use super::*;

#[derive(Clone)]
/// A value computed from other state with optional validated write-back.
///
/// Recomputations publish a `value` property-change message only when the
/// resulting value differs from the current value. Disposed properties ignore
/// recomputations and reject write-back.
pub struct DerivedProperty<T: Clone + PartialEq + Send + 'static> {
    value: Arc<Mutex<T>>,
    value_changed: MessageHub,
    validator: Arc<dyn Fn(&T) -> bool + Send + Sync>,
    write_back: Arc<dyn Fn(T) + Send + Sync>,
    disposed: Arc<Mutex<bool>>,
}

impl<T: Clone + PartialEq + Send + 'static> DerivedProperty<T> {
    /// Creates a read-only derived property with the supplied initial value.
    pub fn new(value: T) -> Self {
        Self {
            value: Arc::new(Mutex::new(value)),
            value_changed: MessageHub::new(),
            validator: Arc::new(|_| false),
            write_back: Arc::new(|_| {}),
            disposed: Arc::new(Mutex::new(false)),
        }
    }

    /// Creates a derived property whose accepted values are written to a source.
    ///
    /// `validator` determines whether [`set_value`](Self::set_value) accepts a
    /// candidate, while `write_back` applies accepted candidates to the source.
    pub fn with_write_back<Validate, WriteBack>(
        value: T,
        validator: Validate,
        write_back: WriteBack,
    ) -> Self
    where
        Validate: Fn(&T) -> bool + Send + Sync + 'static,
        WriteBack: Fn(T) + Send + Sync + 'static,
    {
        Self {
            value: Arc::new(Mutex::new(value)),
            value_changed: MessageHub::new(),
            validator: Arc::new(validator),
            write_back: Arc::new(write_back),
            disposed: Arc::new(Mutex::new(false)),
        }
    }

    /// Returns a snapshot of the current derived value.
    pub fn value(&self) -> T {
        lock(&self.value).clone()
    }

    /// Recomputes the value from its current snapshot.
    ///
    /// The transform and notification are skipped after disposal. An unchanged
    /// result does not publish a property-change message.
    pub fn recompute<F>(&self, transform: F)
    where
        F: FnOnce(&T) -> T,
    {
        if *lock(&self.disposed) {
            return;
        }
        let next = transform(&lock(&self.value));
        let changed = {
            let mut value = lock(&self.value);
            if *value == next {
                false
            } else {
                *value = next;
                true
            }
        };
        if changed {
            self.value_changed
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: 0,
                    property_name: "value".to_string(),
                }));
        }
    }

    /// Returns the hub that publishes changes to the derived value.
    pub fn value_changed(&self) -> MessageHub {
        self.value_changed.clone()
    }

    /// Reports whether `value` is accepted for write-back in the current state.
    pub fn can_set(&self, value: &T) -> bool {
        !*lock(&self.disposed) && (self.validator)(value)
    }

    /// Validates and writes `value` back to the source.
    ///
    /// Returns [`VmxError::InvalidArgument`] when the property is read-only,
    /// disposed, or the configured validator rejects the candidate.
    pub fn set_value(&self, value: T) -> VmxResult<()> {
        if !self.can_set(&value) {
            return Err(VmxError::InvalidArgument(
                "derived property is read-only".to_string(),
            ));
        }
        (self.write_back)(value);
        Ok(())
    }

    /// Disposes the property and its change-notification hub.
    ///
    /// Disposal is idempotent. Subsequent recomputations are ignored and
    /// write-back requests are rejected.
    pub fn dispose(&self) {
        *lock(&self.disposed) = true;
        self.value_changed.dispose();
    }
}
