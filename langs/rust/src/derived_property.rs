//! Read-only and validated write-back derived properties.
//!
//! Spec: `spec/15-derived-properties.md`; ADR-0035.

use super::{
    lock, Arc, Message, MessageHub, Mutex, PropertyChangedMessage, ValueStream, ValueSubscription,
    VmxError, VmxResult,
};

#[derive(Clone)]
/// A value computed from other state with optional validated write-back.
///
/// Recomputations publish a `value` property-change message only when the
/// resulting value differs from the current value. Disposed properties ignore
/// recomputations and reject write-back.
pub struct DerivedProperty<T: Clone + PartialEq + Send + 'static> {
    value: Arc<Mutex<T>>,
    value_changed: MessageHub,
    value_changes: ValueStream<T>,
    validator: Arc<dyn Fn(&T) -> bool + Send + Sync>,
    write_back: Arc<dyn Fn(T) + Send + Sync>,
    disposed: Arc<Mutex<bool>>,
    source_subscriptions: Arc<Mutex<Vec<ValueSubscription>>>,
}

impl<T: Clone + PartialEq + Send + 'static> DerivedProperty<T> {
    /// Creates a read-only derived property with the supplied initial value.
    pub fn new(value: T) -> Self {
        Self {
            value: Arc::new(Mutex::new(value.clone())),
            value_changed: MessageHub::new(),
            value_changes: ValueStream::hot(value),
            validator: Arc::new(|_| false),
            write_back: Arc::new(|_| {}),
            disposed: Arc::new(Mutex::new(false)),
            source_subscriptions: Arc::new(Mutex::new(Vec::new())),
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
            value: Arc::new(Mutex::new(value.clone())),
            value_changed: MessageHub::new(),
            value_changes: ValueStream::hot(value),
            validator: Arc::new(validator),
            write_back: Arc::new(write_back),
            disposed: Arc::new(Mutex::new(false)),
            source_subscriptions: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Creates a derived property from one replaying source.
    pub fn from_one<S, F>(source: ValueStream<S>, transform: F) -> Self
    where
        S: Clone + Send + 'static,
        F: Fn(S) -> T + Send + Sync + 'static,
    {
        let transform = Arc::new(transform);
        let property = Self::new(transform(source.value()));
        let target = property.clone();
        let subscription = source.subscribe(move |value| {
            target.set_computed(transform(value));
        });
        lock(&property.source_subscriptions).push(subscription);
        property
    }

    /// Creates a derived property from two replaying sources.
    pub fn from_two<S1, S2, F>(
        first: ValueStream<S1>,
        second: ValueStream<S2>,
        transform: F,
    ) -> Self
    where
        S1: Clone + Send + 'static,
        S2: Clone + Send + 'static,
        F: Fn(S1, S2) -> T + Send + Sync + 'static,
    {
        let latest = Arc::new(Mutex::new((first.value(), second.value())));
        let transform = Arc::new(transform);
        let initial = {
            let latest = lock(&latest);
            transform(latest.0.clone(), latest.1.clone())
        };
        let property = Self::new(initial);

        let target = property.clone();
        let current = latest.clone();
        let projection = transform.clone();
        let first_subscription = first.subscribe(move |value| {
            let values = {
                let mut current = lock(&current);
                current.0 = value;
                current.clone()
            };
            target.set_computed(projection(values.0, values.1));
        });
        let target = property.clone();
        let second_subscription = second.subscribe(move |value| {
            let values = {
                let mut latest = lock(&latest);
                latest.1 = value;
                latest.clone()
            };
            target.set_computed(transform(values.0, values.1));
        });
        lock(&property.source_subscriptions).extend([first_subscription, second_subscription]);
        property
    }

    /// Creates a derived property from three replaying sources.
    pub fn from_three<S1, S2, S3, F>(
        first: ValueStream<S1>,
        second: ValueStream<S2>,
        third: ValueStream<S3>,
        transform: F,
    ) -> Self
    where
        S1: Clone + Send + 'static,
        S2: Clone + Send + 'static,
        S3: Clone + Send + 'static,
        F: Fn(S1, S2, S3) -> T + Send + Sync + 'static,
    {
        let latest = Arc::new(Mutex::new((first.value(), second.value(), third.value())));
        let transform = Arc::new(transform);
        let initial = {
            let latest = lock(&latest);
            transform(latest.0.clone(), latest.1.clone(), latest.2.clone())
        };
        let property = Self::new(initial);

        let mut subscriptions = Vec::new();
        let target = property.clone();
        let current = latest.clone();
        let projection = transform.clone();
        subscriptions.push(first.subscribe(move |value| {
            let values = {
                let mut current = lock(&current);
                current.0 = value;
                current.clone()
            };
            target.set_computed(projection(values.0, values.1, values.2));
        }));
        let target = property.clone();
        let current = latest.clone();
        let projection = transform.clone();
        subscriptions.push(second.subscribe(move |value| {
            let values = {
                let mut current = lock(&current);
                current.1 = value;
                current.clone()
            };
            target.set_computed(projection(values.0, values.1, values.2));
        }));
        let target = property.clone();
        subscriptions.push(third.subscribe(move |value| {
            let values = {
                let mut latest = lock(&latest);
                latest.2 = value;
                latest.clone()
            };
            target.set_computed(transform(values.0, values.1, values.2));
        }));
        lock(&property.source_subscriptions).extend(subscriptions);
        property
    }

    /// Creates a derived property from four replaying sources.
    pub fn from_four<S1, S2, S3, S4, F>(
        first: ValueStream<S1>,
        second: ValueStream<S2>,
        third: ValueStream<S3>,
        fourth: ValueStream<S4>,
        transform: F,
    ) -> Self
    where
        S1: Clone + Send + 'static,
        S2: Clone + Send + 'static,
        S3: Clone + Send + 'static,
        S4: Clone + Send + 'static,
        F: Fn(S1, S2, S3, S4) -> T + Send + Sync + 'static,
    {
        let latest = Arc::new(Mutex::new((
            first.value(),
            second.value(),
            third.value(),
            fourth.value(),
        )));
        let transform = Arc::new(transform);
        let initial = {
            let latest = lock(&latest);
            transform(
                latest.0.clone(),
                latest.1.clone(),
                latest.2.clone(),
                latest.3.clone(),
            )
        };
        let property = Self::new(initial);

        let mut subscriptions = Vec::new();
        macro_rules! subscribe_source {
            ($source:expr, $field:tt) => {{
                let target = property.clone();
                let current = latest.clone();
                let projection = transform.clone();
                $source.subscribe(move |value| {
                    let values = {
                        let mut current = lock(&current);
                        current.$field = value;
                        current.clone()
                    };
                    target.set_computed(projection(values.0, values.1, values.2, values.3));
                })
            }};
        }
        subscriptions.push(subscribe_source!(first, 0));
        subscriptions.push(subscribe_source!(second, 1));
        subscriptions.push(subscribe_source!(third, 2));
        subscriptions.push(subscribe_source!(fourth, 3));
        lock(&property.source_subscriptions).extend(subscriptions);
        property
    }

    /// Creates a derived property from five replaying sources.
    pub fn from_five<S1, S2, S3, S4, S5, F>(
        first: ValueStream<S1>,
        second: ValueStream<S2>,
        third: ValueStream<S3>,
        fourth: ValueStream<S4>,
        fifth: ValueStream<S5>,
        transform: F,
    ) -> Self
    where
        S1: Clone + Send + 'static,
        S2: Clone + Send + 'static,
        S3: Clone + Send + 'static,
        S4: Clone + Send + 'static,
        S5: Clone + Send + 'static,
        F: Fn(S1, S2, S3, S4, S5) -> T + Send + Sync + 'static,
    {
        let latest = Arc::new(Mutex::new((
            first.value(),
            second.value(),
            third.value(),
            fourth.value(),
            fifth.value(),
        )));
        let transform = Arc::new(transform);
        let initial = {
            let latest = lock(&latest);
            transform(
                latest.0.clone(),
                latest.1.clone(),
                latest.2.clone(),
                latest.3.clone(),
                latest.4.clone(),
            )
        };
        let property = Self::new(initial);

        let mut subscriptions = Vec::new();
        macro_rules! subscribe_source {
            ($source:expr, $field:tt) => {{
                let target = property.clone();
                let current = latest.clone();
                let projection = transform.clone();
                $source.subscribe(move |value| {
                    let values = {
                        let mut current = lock(&current);
                        current.$field = value;
                        current.clone()
                    };
                    target
                        .set_computed(projection(values.0, values.1, values.2, values.3, values.4));
                })
            }};
        }
        subscriptions.push(subscribe_source!(first, 0));
        subscriptions.push(subscribe_source!(second, 1));
        subscriptions.push(subscribe_source!(third, 2));
        subscriptions.push(subscribe_source!(fourth, 3));
        subscriptions.push(subscribe_source!(fifth, 4));
        lock(&property.source_subscriptions).extend(subscriptions);
        property
    }

    /// Creates a derived property from an arbitrary number of same-typed sources.
    pub fn from_sources<S, F>(sources: Vec<ValueStream<S>>, transform: F) -> Self
    where
        S: Clone + Send + 'static,
        F: Fn(Vec<S>) -> T + Send + Sync + 'static,
    {
        assert!(
            !sources.is_empty(),
            "derived property requires at least one source"
        );
        let latest = Arc::new(Mutex::new(
            sources.iter().map(ValueStream::value).collect::<Vec<_>>(),
        ));
        let transform = Arc::new(transform);
        let property = Self::new(transform(lock(&latest).clone()));
        let subscriptions = sources
            .into_iter()
            .enumerate()
            .map(|(index, source)| {
                let target = property.clone();
                let current = latest.clone();
                let projection = transform.clone();
                source.subscribe(move |value| {
                    let values = {
                        let mut current = lock(&current);
                        current[index] = value;
                        current.clone()
                    };
                    target.set_computed(projection(values));
                })
            })
            .collect::<Vec<_>>();
        lock(&property.source_subscriptions).extend(subscriptions);
        property
    }

    /// Creates a writable derived property from same-typed replaying sources.
    pub fn from_sources_with_write_back<S, F, Validate, WriteBack>(
        sources: Vec<ValueStream<S>>,
        transform: F,
        validator: Validate,
        write_back: WriteBack,
    ) -> Self
    where
        S: Clone + Send + 'static,
        F: Fn(Vec<S>) -> T + Send + Sync + 'static,
        Validate: Fn(&T) -> bool + Send + Sync + 'static,
        WriteBack: Fn(T) + Send + Sync + 'static,
    {
        assert!(
            !sources.is_empty(),
            "derived property requires at least one source"
        );
        let latest = Arc::new(Mutex::new(
            sources.iter().map(ValueStream::value).collect::<Vec<_>>(),
        ));
        let transform = Arc::new(transform);
        let property =
            Self::with_write_back(transform(lock(&latest).clone()), validator, write_back);
        let subscriptions = sources
            .into_iter()
            .enumerate()
            .map(|(index, source)| {
                let target = property.clone();
                let current = latest.clone();
                let projection = transform.clone();
                source.subscribe(move |value| {
                    let values = {
                        let mut current = lock(&current);
                        current[index] = value;
                        current.clone()
                    };
                    target.set_computed(projection(values));
                })
            })
            .collect::<Vec<_>>();
        lock(&property.source_subscriptions).extend(subscriptions);
        property
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
        self.set_computed(next);
    }

    fn set_computed(&self, next: T) {
        if *lock(&self.disposed) {
            return;
        }
        let changed = {
            let mut value = lock(&self.value);
            if *value == next {
                false
            } else {
                *value = next.clone();
                true
            }
        };
        if changed {
            self.value_changes.send(next);
            self.value_changed
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: 0,
                    sender_name: "DerivedProperty".to_string(),
                    property_name: "value".to_string(),
                }));
        }
    }

    /// Returns the hub that publishes changes to the derived value.
    pub fn value_changed(&self) -> MessageHub {
        self.value_changed.clone()
    }

    /// Returns typed distinct recomputations without replaying the initial value.
    pub fn value_changes(&self) -> ValueStream<T> {
        self.value_changes.clone()
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
        lock(&self.source_subscriptions).clear();
        self.value_changes.dispose();
        self.value_changed.dispose();
    }
}
