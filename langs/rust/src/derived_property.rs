//! Read-only and validated write-back derived properties.
//!
//! Spec: `spec/15-derived-properties.md`; ADR-0035.

use super::{
    lock, Arc, AtomicUsize, Message, MessageHub, Mutex, Ordering, PropertyChangedMessage,
    ValueStream, ValueSubscription, VmxError, VmxResult,
};

#[cfg(test)]
type RevisionedCommitHook = Arc<dyn Fn(usize) + Send + Sync>;

#[derive(Clone)]
struct RevisionedComputation<T> {
    revision: usize,
    value: T,
}

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
    #[cfg(test)]
    revisioned_commit_hook: Arc<Mutex<Option<RevisionedCommitHook>>>,
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
            #[cfg(test)]
            revisioned_commit_hook: Arc::new(Mutex::new(None)),
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
            #[cfg(test)]
            revisioned_commit_hook: Arc::new(Mutex::new(None)),
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
        let source_revision = Arc::new(AtomicUsize::new(0));
        let transform = Arc::new(transform);
        let initial = {
            let latest = lock(&latest);
            transform(latest.0.clone(), latest.1.clone())
        };
        let property = Self::new(initial);
        let computed_results = property.revisioned_results(source_revision.clone());

        let current = latest.clone();
        let projection = transform.clone();
        let revisions = source_revision.clone();
        let results = computed_results.clone();
        let first_subscription = first.subscribe(move |value| {
            let (values, revision) = {
                let mut current = lock(&current);
                current.0 = value;
                (
                    current.clone(),
                    revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                )
            };
            results.send(RevisionedComputation {
                revision,
                value: projection(values.0, values.1),
            });
        });
        let revisions = source_revision;
        let results = computed_results;
        let second_subscription = second.subscribe(move |value| {
            let (values, revision) = {
                let mut latest = lock(&latest);
                latest.1 = value;
                (
                    latest.clone(),
                    revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                )
            };
            results.send(RevisionedComputation {
                revision,
                value: transform(values.0, values.1),
            });
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
        let source_revision = Arc::new(AtomicUsize::new(0));
        let transform = Arc::new(transform);
        let initial = {
            let latest = lock(&latest);
            transform(latest.0.clone(), latest.1.clone(), latest.2.clone())
        };
        let property = Self::new(initial);
        let computed_results = property.revisioned_results(source_revision.clone());

        let mut subscriptions = Vec::new();
        let current = latest.clone();
        let projection = transform.clone();
        let revisions = source_revision.clone();
        let results = computed_results.clone();
        subscriptions.push(first.subscribe(move |value| {
            let (values, revision) = {
                let mut current = lock(&current);
                current.0 = value;
                (
                    current.clone(),
                    revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                )
            };
            results.send(RevisionedComputation {
                revision,
                value: projection(values.0, values.1, values.2),
            });
        }));
        let current = latest.clone();
        let projection = transform.clone();
        let revisions = source_revision.clone();
        let results = computed_results.clone();
        subscriptions.push(second.subscribe(move |value| {
            let (values, revision) = {
                let mut current = lock(&current);
                current.1 = value;
                (
                    current.clone(),
                    revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                )
            };
            results.send(RevisionedComputation {
                revision,
                value: projection(values.0, values.1, values.2),
            });
        }));
        let revisions = source_revision;
        let results = computed_results;
        subscriptions.push(third.subscribe(move |value| {
            let (values, revision) = {
                let mut latest = lock(&latest);
                latest.2 = value;
                (
                    latest.clone(),
                    revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                )
            };
            results.send(RevisionedComputation {
                revision,
                value: transform(values.0, values.1, values.2),
            });
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
        let source_revision = Arc::new(AtomicUsize::new(0));
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
        let computed_results = property.revisioned_results(source_revision.clone());

        let mut subscriptions = Vec::new();
        macro_rules! subscribe_source {
            ($source:expr, $field:tt) => {{
                let current = latest.clone();
                let projection = transform.clone();
                let revisions = source_revision.clone();
                let results = computed_results.clone();
                $source.subscribe(move |value| {
                    let (values, revision) = {
                        let mut current = lock(&current);
                        current.$field = value;
                        (
                            current.clone(),
                            revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                        )
                    };
                    results.send(RevisionedComputation {
                        revision,
                        value: projection(values.0, values.1, values.2, values.3),
                    });
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
        let source_revision = Arc::new(AtomicUsize::new(0));
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
        let computed_results = property.revisioned_results(source_revision.clone());

        let mut subscriptions = Vec::new();
        macro_rules! subscribe_source {
            ($source:expr, $field:tt) => {{
                let current = latest.clone();
                let projection = transform.clone();
                let revisions = source_revision.clone();
                let results = computed_results.clone();
                $source.subscribe(move |value| {
                    let (values, revision) = {
                        let mut current = lock(&current);
                        current.$field = value;
                        (
                            current.clone(),
                            revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                        )
                    };
                    results.send(RevisionedComputation {
                        revision,
                        value: projection(values.0, values.1, values.2, values.3, values.4),
                    });
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
        let source_revision = Arc::new(AtomicUsize::new(0));
        let transform = Arc::new(transform);
        let property = Self::new(transform(lock(&latest).clone()));
        let computed_results = property.revisioned_results(source_revision.clone());
        let subscriptions = sources
            .into_iter()
            .enumerate()
            .map(|(index, source)| {
                let current = latest.clone();
                let projection = transform.clone();
                let revisions = source_revision.clone();
                let results = computed_results.clone();
                source.subscribe(move |value| {
                    let (values, revision) = {
                        let mut current = lock(&current);
                        current[index] = value;
                        (
                            current.clone(),
                            revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                        )
                    };
                    results.send(RevisionedComputation {
                        revision,
                        value: projection(values),
                    });
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
        let source_revision = Arc::new(AtomicUsize::new(0));
        let transform = Arc::new(transform);
        let property =
            Self::with_write_back(transform(lock(&latest).clone()), validator, write_back);
        let computed_results = property.revisioned_results(source_revision.clone());
        let subscriptions = sources
            .into_iter()
            .enumerate()
            .map(|(index, source)| {
                let current = latest.clone();
                let projection = transform.clone();
                let revisions = source_revision.clone();
                let results = computed_results.clone();
                source.subscribe(move |value| {
                    let (values, revision) = {
                        let mut current = lock(&current);
                        current[index] = value;
                        (
                            current.clone(),
                            revisions.fetch_add(1, Ordering::AcqRel).wrapping_add(1),
                        )
                    };
                    results.send(RevisionedComputation {
                        revision,
                        value: projection(values),
                    });
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

    fn revisioned_results(
        &self,
        source_revision: Arc<AtomicUsize>,
    ) -> ValueStream<RevisionedComputation<T>> {
        let results = ValueStream::hot(RevisionedComputation {
            revision: 0,
            value: self.value(),
        });
        let target = self.clone();
        let subscription = results.subscribe({
            let source_revision = source_revision.clone();
            move |computed| target.commit_revisioned(computed, &source_revision)
        });
        lock(&self.source_subscriptions).push(subscription);
        results
    }

    fn commit_revisioned(&self, computed: RevisionedComputation<T>, source_revision: &AtomicUsize) {
        if *lock(&self.disposed) {
            return;
        }
        let changed = {
            let mut value = lock(&self.value);
            if source_revision.load(Ordering::Acquire) != computed.revision
                || *value == computed.value
            {
                false
            } else {
                *value = computed.value.clone();
                true
            }
        };
        if changed {
            #[cfg(test)]
            let commit_hook = lock(&self.revisioned_commit_hook).clone();
            #[cfg(test)]
            if let Some(hook) = commit_hook {
                hook(computed.revision);
            }
            self.value_changes.send(computed.value);
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{mpsc, Barrier};
    use std::time::Duration;

    #[test]
    fn owns_exactly_one_subscription_per_source_until_disposal() {
        let sources = (1..=5).map(ValueStream::new).collect::<Vec<_>>();
        let property = DerivedProperty::from_sources(sources.clone(), |values| {
            values.into_iter().sum::<i32>()
        });

        assert!(sources
            .iter()
            .all(|source| source.active_subscription_count() == 1));

        property.dispose();

        assert!(sources
            .iter()
            .all(|source| source.active_subscription_count() == 0));
    }

    #[test]
    fn revisioned_commit_serializes_value_and_publication() {
        let left = ValueStream::new(0);
        let right = ValueStream::new(0);
        let (older_committed_tx, older_committed_rx) = mpsc::channel();
        let (newer_committed_tx, newer_committed_rx) = mpsc::channel();
        let older_release = Arc::new(Barrier::new(2));
        let hook_release = older_release.clone();

        let (newer_transform_tx, newer_transform_rx) = mpsc::channel();
        let property = DerivedProperty::from_two(
            left.clone(),
            right.clone(),
            move |left_value, right_value| {
                if (left_value, right_value) == (1, 1) {
                    newer_transform_tx.send(()).unwrap();
                }
                left_value + right_value
            },
        );
        *lock(&property.revisioned_commit_hook) = Some(Arc::new(move |revision| match revision {
            3 => {
                older_committed_tx.send(()).unwrap();
                hook_release.wait();
            }
            4 => newer_committed_tx.send(()).unwrap(),
            _ => {}
        }));
        let values = Arc::new(Mutex::new(Vec::new()));
        let observed = values.clone();
        let _subscription = property
            .value_changes()
            .subscribe(move |value| lock(&observed).push(value));

        let older_sender = std::thread::spawn(move || left.send(1));
        older_committed_rx.recv().unwrap();
        let newer_sender = std::thread::spawn(move || right.send(1));
        newer_transform_rx.recv().unwrap();
        let newer_committed_before_release = newer_committed_rx
            .recv_timeout(Duration::from_millis(50))
            .is_ok();

        older_release.wait();
        older_sender.join().unwrap();
        newer_sender.join().unwrap();

        assert!(
            !newer_committed_before_release,
            "a newer result committed while an older publication was paused"
        );
        assert_eq!(*lock(&values), vec![1, 2]);
        assert_eq!(property.value(), 2);
        assert_eq!(property.value_changes().value(), 2);
    }
}
