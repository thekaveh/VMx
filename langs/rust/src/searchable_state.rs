//! Pull-based filtering state with change notifications.
//!
//! Spec: `spec/06-composite-vm.md` §Search / filter; ADR-0014, ADR-0219.

use std::time::Duration;

use super::{
    lock, Arc, AtomicBool, DelayedTask, Message, MessageHub, Mutex, Ordering, Scheduler,
    Searchable, Subscription, SystemScheduler,
};

type ItemsProvider<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;
type SearchPredicate<T> = Arc<dyn Fn(&T, &str) -> bool + Send + Sync>;

/// The default term debounce (spec/06 §8).
const DEFAULT_DEBOUNCE: Duration = Duration::from_secs(1);

fn filtered_message() -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "SearchableState".to_string(),
        name: "filtered".to_string(),
    }
}

/// A search term and predicate projected over a snapshot or live item source.
///
/// Live providers are pulled whenever filtered state is requested. A
/// `filtered` message on [`filtered_changed`](Self::filtered_changed) tells a
/// consumer to pull [`filtered`](Self::filtered) again. A term change sends
/// it after the term debounce, 1 second by default, on the scheduler's
/// thread. [`search`](Self::search) and a source-change message send it at
/// once (spec/06 §8, ADR-0219).
#[derive(Clone)]
pub struct SearchableState<T: Clone + Send + Sync + 'static> {
    source: ItemsProvider<T>,
    search_term: Arc<Mutex<String>>,
    predicate: SearchPredicate<T>,
    filtered_changed: MessageHub,
    source_changes_subscription: Arc<Mutex<Option<Subscription>>>,
    disposed: Arc<AtomicBool>,
    debounce: Duration,
    term_delivery: DelayedTask,
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
            debounce: DEFAULT_DEBOUNCE,
            term_delivery: DelayedTask::new(SystemScheduler),
        };
        if let Some(source_changes) = source_changes {
            let filtered_changed = state.filtered_changed.clone();
            let disposed = state.disposed.clone();
            let subscription = source_changes.subscribe(move |_| {
                if disposed.load(Ordering::Acquire) {
                    return;
                }
                filtered_changed.send(filtered_message());
            });
            *lock(&state.source_changes_subscription) = Some(subscription);

            // Second half of reconciliation: anything that changed before
            // attachment is visible to the first post-construction pull.
            let _ = state.filtered();
        }
        state
    }

    /// Sets the term debounce. The default is 1 second.
    ///
    /// A zero debounce sends the `filtered` message before
    /// [`set_search_term`](Self::set_search_term) returns. Call this before
    /// first use.
    pub fn with_debounce(mut self, debounce: Duration) -> Self {
        self.debounce = debounce;
        self
    }

    /// Sets the scheduler that runs the term debounce. The default is
    /// [`SystemScheduler`]; a test passes a
    /// [`VirtualTimeScheduler`](crate::VirtualTimeScheduler).
    ///
    /// Call this before first use: it cancels a pending term delivery, and a
    /// clone made before this call keeps the previous scheduler.
    pub fn with_scheduler(mut self, scheduler: impl Scheduler) -> Self {
        self.term_delivery.cancel();
        self.term_delivery = DelayedTask::new(scheduler);
        self
    }

    /// Returns the current search term.
    pub fn search_term(&self) -> String {
        if self.disposed.load(Ordering::Acquire) {
            return String::new();
        }
        lock(&self.search_term).clone()
    }

    /// Changes the search term and schedules one `filtered` message after the
    /// debounce.
    ///
    /// A later change inside the window restarts the debounce. A zero
    /// debounce sends the message before this call returns. Equal assignments
    /// and assignments after disposal are inert.
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
        if !changed {
            return;
        }
        if self.debounce.is_zero() {
            self.filtered_changed.send(filtered_message());
            return;
        }
        let (filtered_changed, disposed) = (self.filtered_changed.clone(), self.disposed.clone());
        self.term_delivery.schedule(self.debounce, move || {
            if !disposed.load(Ordering::Acquire) {
                filtered_changed.send(filtered_message());
            }
        });
    }

    /// Evaluates and returns the current filtered projection, and announces it
    /// at once on [`SearchableState::filtered_changed`], as the pushed filtered
    /// output of the other flavors does (SRCH-005).
    ///
    /// A pending term delivery is not cancelled and still sends its message.
    pub fn search(&self) -> Vec<T> {
        if self.disposed.load(Ordering::Acquire) {
            return Vec::new();
        }
        let filtered = self.filtered();
        self.filtered_changed.send(filtered_message());
        filtered
    }

    /// Pulls the source and returns items accepted by the current term.
    pub fn filtered(&self) -> Vec<T> {
        if self.disposed.load(Ordering::Acquire) {
            return Vec::new();
        }
        let term = self.search_term();
        (self.source)()
            .into_iter()
            .filter(|item| (self.predicate)(item, &term))
            .collect()
    }

    /// Reports whether the current source contains any searchable items.
    pub fn can_search(&self) -> bool {
        !self.disposed.load(Ordering::Acquire) && !(self.source)().is_empty()
    }

    /// Returns the hub that announces filtered-projection changes.
    pub fn filtered_changed(&self) -> MessageHub {
        self.filtered_changed.clone()
    }

    /// Stops source observation, cancels a pending term delivery and
    /// disposes the filtered-change hub.
    ///
    /// Disposal is idempotent. It never disposes the scheduler.
    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::AcqRel) {
            return;
        }
        self.term_delivery.dispose();
        lock(&self.source_changes_subscription).take();
        self.filtered_changed.dispose();
    }
}

impl<T: Clone + Send + Sync + 'static> Searchable for SearchableState<T> {
    fn can_search(&self) -> bool {
        SearchableState::can_search(self)
    }

    fn search_term(&self) -> String {
        SearchableState::search_term(self)
    }

    fn set_search_term(&self, term: String) {
        SearchableState::set_search_term(self, term);
    }

    fn search(&self) {
        let _ = SearchableState::search(self);
    }
}
