//! Pull-based filtering state with change notifications.
//!
//! Spec: `spec/06-composite-vm.md` §Search / filter; ADR-0014.

use super::{lock, Arc, AtomicBool, Message, MessageHub, Mutex, Ordering, Subscription};

type ItemsProvider<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;
type SearchPredicate<T> = Arc<dyn Fn(&T, &str) -> bool + Send + Sync>;

/// A search term and predicate projected over a snapshot or live item source.
///
/// Live providers are pulled whenever filtered state is requested. When a
/// source-change hub is supplied, its messages announce that the projection
/// may have changed without eagerly retaining a second collection.
#[derive(Clone)]
pub struct SearchableState<T: Clone + Send + Sync + 'static> {
    source: ItemsProvider<T>,
    search_term: Arc<Mutex<String>>,
    predicate: SearchPredicate<T>,
    filtered_changed: MessageHub,
    source_changes_subscription: Arc<Mutex<Option<Subscription>>>,
    disposed: Arc<AtomicBool>,
}

impl<T: Clone + Send + Sync + 'static> SearchableState<T> {
    /// Creates searchable state over an immutable source snapshot.
    pub fn new<F>(source: Vec<T>, predicate: F) -> Self
    where
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(move || source.clone(), predicate, None)
    }

    /// Creates searchable state over a snapshot with an external change hub.
    ///
    /// Each source-change message publishes a filtered-change notification.
    pub fn new_with_changes<F>(source: Vec<T>, predicate: F, source_changes: MessageHub) -> Self
    where
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(move || source.clone(), predicate, Some(source_changes))
    }

    /// Creates searchable state that pulls a fresh item snapshot on demand.
    pub fn from_items<S, F>(source: S, predicate: F) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(source, predicate, None)
    }

    /// Creates live searchable state and observes its source-change hub.
    pub fn from_items_with_changes<S, F>(
        source: S,
        predicate: F,
        source_changes: MessageHub,
    ) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(source, predicate, Some(source_changes))
    }

    fn build<S, F>(source: S, predicate: F, source_changes: Option<MessageHub>) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        let source: ItemsProvider<T> = Arc::new(source);
        if source_changes.is_some() {
            // First half of snapshot/attach reconciliation. The Rust facade is
            // pull-based, so the constructor does not retain this projection.
            let _ = source();
        }
        let state = Self {
            source,
            search_term: Arc::new(Mutex::new(String::new())),
            predicate: Arc::new(predicate),
            filtered_changed: MessageHub::new(),
            source_changes_subscription: Arc::new(Mutex::new(None)),
            disposed: Arc::new(AtomicBool::new(false)),
        };
        if let Some(source_changes) = source_changes {
            let filtered_changed = state.filtered_changed.clone();
            let disposed = state.disposed.clone();
            let subscription = source_changes.subscribe(move |_| {
                if disposed.load(Ordering::Acquire) {
                    return;
                }
                filtered_changed.send(Message::Custom {
                    sender_id: 0,
                    sender_name: "SearchableState".to_string(),
                    name: "filtered".to_string(),
                });
            });
            *lock(&state.source_changes_subscription) = Some(subscription);

            // Second half of reconciliation: anything that changed before
            // attachment is visible to the first post-construction pull.
            let _ = state.filtered();
        }
        state
    }

    /// Returns the current search term.
    pub fn search_term(&self) -> String {
        lock(&self.search_term).clone()
    }

    /// Changes the search term and announces a changed filtered projection.
    ///
    /// Equal assignments and assignments after disposal are inert.
    pub fn set_search_term(&self, term: impl Into<String>) {
        if self.disposed.load(Ordering::Acquire) {
            return;
        }
        let changed = {
            let mut current = lock(&self.search_term);
            let next = term.into();
            if *current == next {
                false
            } else {
                *current = next;
                true
            }
        };
        if changed {
            self.filtered_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "SearchableState".to_string(),
                name: "filtered".to_string(),
            });
        }
    }

    /// Evaluates and returns the current filtered projection.
    pub fn search(&self) -> Vec<T> {
        self.filtered()
    }

    /// Pulls the source and returns items accepted by the current term.
    pub fn filtered(&self) -> Vec<T> {
        let term = self.search_term();
        (self.source)()
            .into_iter()
            .filter(|item| (self.predicate)(item, &term))
            .collect()
    }

    /// Reports whether the current source contains any searchable items.
    pub fn can_search(&self) -> bool {
        !(self.source)().is_empty()
    }

    /// Returns the hub that announces filtered-projection changes.
    pub fn filtered_changed(&self) -> MessageHub {
        self.filtered_changed.clone()
    }

    /// Stops source observation and disposes the filtered-change hub.
    ///
    /// Disposal is idempotent.
    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::AcqRel) {
            return;
        }
        lock(&self.source_changes_subscription).take();
        self.filtered_changed.dispose();
    }
}
