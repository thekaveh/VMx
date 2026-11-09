//! Notification values, pending waiters, and resolution hubs.
//!
//! Spec: `spec/16-notifications.md`; ADR-0031. The `notifications` Cargo
//! feature, on by default, compiles this module (ADR-0211).

use super::{
    catch_unwind, lock, thread, wait, Arc, AssertUnwindSafe, AsyncValue, AtomicU64, Condvar,
    Context, Future, HashMap, HashSet, Message, MessageHub, Mutex, Ordering, Pin, Poll, ThreadId,
    ValueStream, VecDeque,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Classifies a notification's presentation and interaction contract.
pub enum NotificationType {
    /// An error notification.
    Error,
    /// An informational notification.
    Notification,
    /// A notification requiring approval or rejection.
    Confirmation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// The current or terminal reaction to a notification.
pub enum NotificationReaction {
    /// The notification has not resolved.
    Pending,
    /// The notification was approved or dismissed positively.
    Approve,
    /// The notification was rejected.
    Reject,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Immutable notification identity, type, and display message.
pub struct Notification {
    /// Stable notification identity allocated at creation.
    pub id: u64,
    /// Presentation and interaction type.
    pub kind: NotificationType,
    /// User-facing notification message.
    pub message: String,
}

impl Notification {
    /// Creates a notification with a new stable identity.
    pub fn new(kind: NotificationType, message: impl Into<String>) -> Self {
        static NEXT_NOTIFICATION_ID: AtomicU64 = AtomicU64::new(1);
        Self {
            id: NEXT_NOTIFICATION_ID.fetch_add(1, Ordering::Relaxed),
            kind,
            message: message.into(),
        }
    }
}

#[derive(Clone)]
/// A cloneable blocking and async-compatible handle for one reaction.
pub struct NotificationWaiter {
    completion: AsyncValue<NotificationReaction>,
}

impl NotificationWaiter {
    /// Blocks until the notification resolves and returns its reaction.
    pub fn wait(&self) -> NotificationReaction {
        self.completion.wait()
    }

    /// Returns the terminal reaction without blocking, or `None` while pending.
    pub fn try_get(&self) -> Option<NotificationReaction> {
        self.completion.try_get()
    }
}

impl Future for NotificationWaiter {
    type Output = NotificationReaction;

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        Pin::new(&mut self.completion).poll(context)
    }
}

#[derive(Default)]
struct NotificationHubState {
    /// Pending notifications in post order (spec/16 §2.1).
    pending: Vec<Notification>,
    reactions: HashMap<u64, NotificationReaction>,
    /// Notifications removed by `resolve`, with any reaction (NOTIF-015).
    resolved: HashSet<u64>,
    completions: HashMap<u64, AsyncValue<NotificationReaction>>,
    pending_publications: VecDeque<PendingPublication>,
    publishing_owner: Option<ThreadId>,
    dispose_completion: Option<Arc<PendingPublicationCompletion>>,
    disposed: bool,
}

#[derive(Default)]
struct PendingPublicationCompletion {
    finished: Mutex<bool>,
    ready: Condvar,
}

impl PendingPublicationCompletion {
    fn wait(&self) {
        let mut finished = lock(&self.finished);
        while !*finished {
            finished = wait(&self.ready, finished);
        }
    }

    fn finish(&self) {
        *lock(&self.finished) = true;
        self.ready.notify_all();
    }
}

struct PendingPublication {
    snapshot: Vec<Notification>,
    completions: Vec<(AsyncValue<NotificationReaction>, NotificationReaction)>,
    terminal: bool,
    completion: Arc<PendingPublicationCompletion>,
}

struct PendingPublicationAdmission {
    completion: Arc<PendingPublicationCompletion>,
    owner: ThreadId,
    should_drain: bool,
    reentrant: bool,
}

/// The post, resolve and pending-list operations of a notification hub
/// (spec/16 §2, ADR-0211).
///
/// [`NotificationHub`] and [`NullNotificationHub`] implement it, so a caller
/// such as [`make_confirm`] accepts either one. Each implementer also has
/// inherent methods with the same names, so a call on a concrete hub does not
/// need this trait in scope.
pub trait NotificationHubApi: Send + Sync {
    /// Posts `notification` and returns the waiter for its reaction.
    fn post_notification(&self, notification: Notification) -> NotificationWaiter;

    /// Resolves the pending notification `notification_id` with `reaction`.
    ///
    /// Resolving a notification that is not pending has no effect.
    fn resolve(&self, notification_id: u64, reaction: NotificationReaction);

    /// Returns a snapshot of the pending notifications, in post order.
    fn pending(&self) -> Vec<Notification>;

    /// Returns the replaying stream of committed pending snapshots.
    fn pending_stream(&self) -> ValueStream<Vec<Notification>>;
}

impl<H: NotificationHubApi + ?Sized> NotificationHubApi for Arc<H> {
    fn post_notification(&self, notification: Notification) -> NotificationWaiter {
        (**self).post_notification(notification)
    }

    fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        (**self).resolve(notification_id, reaction);
    }

    fn pending(&self) -> Vec<Notification> {
        (**self).pending()
    }

    fn pending_stream(&self) -> ValueStream<Vec<Notification>> {
        (**self).pending_stream()
    }
}

#[derive(Clone)]
/// Concurrent notification queue with pending snapshots and first-wins resolution.
///
/// The hub keeps the current pending list, the open waiters and the queue of
/// undelivered snapshots. It keeps no history of delivered snapshots
/// (ADR-0211). Subscribe to [`pending_stream`](Self::pending_stream) to
/// observe each committed snapshot.
pub struct NotificationHub {
    state: Arc<Mutex<NotificationHubState>>,
    pending_changed: MessageHub,
    pending_stream: ValueStream<Vec<Notification>>,
}

impl Default for NotificationHub {
    fn default() -> Self {
        Self {
            state: Arc::new(Mutex::new(NotificationHubState::default())),
            pending_changed: MessageHub::new(),
            pending_stream: ValueStream::new(Vec::new()),
        }
    }
}

impl NotificationHub {
    /// Creates an empty notification hub.
    pub fn new() -> Self {
        Self::default()
    }

    /// Posts `notification` or reuses its existing pending waiter.
    pub fn post_notification(&self, notification: Notification) -> NotificationWaiter {
        let notification_id = notification.id;
        let (completion, admission) = {
            let mut state = lock(&self.state);
            if state.disposed {
                // A post after dispose returns a pending result and never
                // replaces a stored terminal reaction (DISP-004).
                (AsyncValue::ready(NotificationReaction::Pending), None)
            } else if let Some(completion) = state.completions.get(&notification_id).cloned() {
                (completion, None)
            } else {
                let completion = AsyncValue::pending();
                // A re-posted notification is pending again, not resolved.
                state.resolved.remove(&notification_id);
                state.pending.push(notification);
                state
                    .reactions
                    .insert(notification_id, NotificationReaction::Pending);
                state
                    .completions
                    .insert(notification_id, completion.clone());
                let snapshot = state.pending.clone();
                let admission =
                    Self::enqueue_pending_publication(&mut state, snapshot, Vec::new(), false);
                (completion, Some(admission))
            }
        };
        if let Some(admission) = admission {
            self.complete_pending_publication(admission);
        }
        NotificationWaiter { completion }
    }

    /// Creates and posts a notification, returning its identity value.
    pub fn post(&self, kind: NotificationType, message: impl Into<String>) -> Notification {
        let notification = Notification::new(kind, message);
        self.post_notification(notification.clone());
        notification
    }

    /// Creates and posts a notification with its reaction waiter.
    pub fn post_with_waiter(
        &self,
        kind: NotificationType,
        message: impl Into<String>,
    ) -> (Notification, NotificationWaiter) {
        let notification = Notification::new(kind, message);
        let waiter = self.post_notification(notification.clone());
        (notification, waiter)
    }

    /// Resolves a pending notification once and removes it from the queue.
    pub fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        let admission = {
            let mut state = lock(&self.state);
            let Some(index) = state
                .pending
                .iter()
                .position(|pending| pending.id == notification_id)
            else {
                return;
            };
            state.pending.remove(index);
            state.resolved.insert(notification_id);
            state.reactions.insert(notification_id, reaction);
            let completions = state
                .completions
                .remove(&notification_id)
                .into_iter()
                .map(|completion| (completion, reaction))
                .collect();
            let snapshot = state.pending.clone();
            Self::enqueue_pending_publication(&mut state, snapshot, completions, false)
        };
        self.complete_pending_publication(admission);
    }

    /// Reports whether `resolve` removed `notification_id` from the pending
    /// list, with any reaction. Hub disposal does not count as a resolution.
    pub(crate) fn was_resolved(&self, notification_id: u64) -> bool {
        lock(&self.state).resolved.contains(&notification_id)
    }

    /// Returns a snapshot of currently pending notifications.
    pub fn pending(&self) -> Vec<Notification> {
        lock(&self.state).pending.clone()
    }

    /// Returns the hub that publishes committed pending-list changes.
    pub fn pending_changed(&self) -> MessageHub {
        self.pending_changed.clone()
    }

    /// Returns the replaying typed stream of committed pending snapshots.
    pub fn pending_stream(&self) -> ValueStream<Vec<Notification>> {
        self.pending_stream.clone()
    }

    /// Returns an empty list. The hub keeps no snapshot history (ADR-0211).
    ///
    /// Migration: subscribe to [`pending_stream`](Self::pending_stream)
    /// before the posts and resolutions to observe, and collect the values.
    /// The first value is the snapshot that is current at subscription.
    #[deprecated(
        since = "0.36.0",
        note = "the hub keeps no snapshot history, so this is always empty; subscribe to `pending_stream()`"
    )]
    pub fn pending_snapshots(&self) -> Vec<Vec<Notification>> {
        Vec::new()
    }

    /// Returns a pending or terminal reaction for `notification_id`.
    pub fn reaction(&self, notification_id: u64) -> NotificationReaction {
        lock(&self.state)
            .reactions
            .get(&notification_id)
            .copied()
            .unwrap_or(NotificationReaction::Pending)
    }

    /// Resolves all pending waiters as pending and closes the hub.
    pub fn dispose(&self) {
        let current = thread::current().id();
        let admission = {
            let mut state = lock(&self.state);
            if state.disposed {
                let completion = state.dispose_completion.clone();
                let reentrant = state.publishing_owner == Some(current);
                drop(state);
                if let Some(completion) = completion.filter(|_| !reentrant) {
                    completion.wait();
                }
                return;
            }
            state.disposed = true;
            let pending_ids = state
                .pending
                .iter()
                .map(|pending| pending.id)
                .collect::<Vec<_>>();
            for id in pending_ids {
                state.reactions.insert(id, NotificationReaction::Pending);
            }
            let completions = state
                .completions
                .drain()
                .map(|(_, completion)| (completion, NotificationReaction::Pending))
                .collect::<Vec<_>>();
            state.pending.clear();
            let admission =
                Self::enqueue_pending_publication(&mut state, Vec::new(), completions, true);
            state.dispose_completion = Some(admission.completion.clone());
            admission
        };
        self.complete_pending_publication(admission);
    }

    fn enqueue_pending_publication(
        state: &mut NotificationHubState,
        snapshot: Vec<Notification>,
        completions: Vec<(AsyncValue<NotificationReaction>, NotificationReaction)>,
        terminal: bool,
    ) -> PendingPublicationAdmission {
        let current = thread::current().id();
        let completion = Arc::new(PendingPublicationCompletion::default());
        state.pending_publications.push_back(PendingPublication {
            snapshot,
            completions,
            terminal,
            completion: completion.clone(),
        });
        let reentrant = state.publishing_owner == Some(current);
        let should_drain = state.publishing_owner.is_none();
        if should_drain {
            state.publishing_owner = Some(current);
        }
        PendingPublicationAdmission {
            completion,
            owner: current,
            should_drain,
            reentrant,
        }
    }

    fn complete_pending_publication(&self, admission: PendingPublicationAdmission) {
        if admission.should_drain {
            self.drain_pending_publications(admission.owner);
        } else if !admission.reentrant {
            admission.completion.wait();
        }
    }

    fn drain_pending_publications(&self, current: ThreadId) {
        loop {
            let publication = {
                let mut state = lock(&self.state);
                let Some(publication) = state.pending_publications.pop_front() else {
                    state.publishing_owner = None;
                    return;
                };
                debug_assert_eq!(state.publishing_owner, Some(current));
                publication
            };
            self.pending_stream.send(publication.snapshot);
            self.pending_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "NotificationHub".to_string(),
                name: "pending".to_string(),
            });
            if publication.terminal {
                self.pending_stream.dispose();
                self.pending_changed.dispose();
            }
            for (completion, reaction) in publication.completions {
                let _ = catch_unwind(AssertUnwindSafe(|| completion.resolve(reaction)));
            }
            publication.completion.finish();
        }
    }
}

impl NotificationHubApi for NotificationHub {
    fn post_notification(&self, notification: Notification) -> NotificationWaiter {
        NotificationHub::post_notification(self, notification)
    }

    fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        NotificationHub::resolve(self, notification_id, reaction);
    }

    fn pending(&self) -> Vec<Notification> {
        NotificationHub::pending(self)
    }

    fn pending_stream(&self) -> ValueStream<Vec<Notification>> {
        NotificationHub::pending_stream(self)
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
/// Null notification hub that returns safe immediate approvals (spec/16 §3).
///
/// It keeps no notification. A post returns an approved waiter at once,
/// `resolve` has no effect, and the pending list is always empty. It
/// implements [`NotificationHubApi`], so it can replace a [`NotificationHub`]
/// wherever a caller accepts that trait.
pub struct NullNotificationHub;

impl NullNotificationHub {
    /// Creates a null notification hub.
    pub fn new() -> Self {
        Self
    }

    /// Returns an immediately approved waiter without retaining the notification.
    pub fn post_notification(&self, _notification: Notification) -> NotificationWaiter {
        NotificationWaiter {
            completion: AsyncValue::ready(NotificationReaction::Approve),
        }
    }

    /// Creates a notification and returns it. Nothing retains it.
    pub fn post(&self, kind: NotificationType, message: impl Into<String>) -> Notification {
        Notification::new(kind, message)
    }

    /// Creates a notification and returns it with an immediately approved waiter.
    pub fn post_with_waiter(
        &self,
        kind: NotificationType,
        message: impl Into<String>,
    ) -> (Notification, NotificationWaiter) {
        let notification = Notification::new(kind, message);
        let waiter = self.post_notification(notification.clone());
        (notification, waiter)
    }

    /// Has no effect: the null hub has no pending notification.
    pub fn resolve(&self, _notification_id: u64, _reaction: NotificationReaction) {}

    /// Returns an empty list.
    pub fn pending(&self) -> Vec<Notification> {
        Vec::new()
    }

    /// Returns a stream that replays the empty list once and completes.
    pub fn pending_stream(&self) -> ValueStream<Vec<Notification>> {
        let pending = ValueStream::new(Vec::new());
        pending.dispose();
        pending
    }
}

impl NotificationHubApi for NullNotificationHub {
    fn post_notification(&self, notification: Notification) -> NotificationWaiter {
        NullNotificationHub::post_notification(self, notification)
    }

    fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        NullNotificationHub::resolve(self, notification_id, reaction);
    }

    fn pending(&self) -> Vec<Notification> {
        NullNotificationHub::pending(self)
    }

    fn pending_stream(&self) -> ValueStream<Vec<Notification>> {
        NullNotificationHub::pending_stream(self)
    }
}

/// Creates a cloneable confirmation predicate backed by `hub` and `prompt`.
///
/// `hub` is any [`NotificationHubApi`] implementer, such as a
/// [`NotificationHub`], a [`NullNotificationHub`] or an
/// `Arc<dyn NotificationHubApi>`. Each call posts a confirmation and completes
/// with `true` only for [`NotificationReaction::Approve`].
pub fn make_confirm<H>(hub: H, prompt: impl Into<String>) -> impl Fn() -> AsyncValue<bool> + Clone
where
    H: NotificationHubApi + Clone + 'static,
{
    let prompt = Arc::new(prompt.into());
    move || {
        let notification = Notification::new(NotificationType::Confirmation, (*prompt).clone());
        hub.post_notification(notification)
            .completion
            .map(|reaction| reaction == NotificationReaction::Approve)
    }
}

#[cfg(test)]
mod blocking_wait_tests {
    use super::*;

    #[test]
    fn post_waiter_remains_pending_until_resolve() {
        let hub = NotificationHub::new();
        let (notification, waiter) = hub.post_with_waiter(NotificationType::Notification, "info");
        let observation = waiter.completion.observe_wait();
        let waiting_copy = waiter.clone();
        let waiting = thread::spawn(move || waiting_copy.wait());
        let checks = catch_unwind(AssertUnwindSafe(|| {
            observation
                .entered
                .recv_timeout(std::time::Duration::from_secs(2))
                .expect("blocking waiter entered the completion's native wait");
            assert_eq!(waiter.try_get(), None);
            assert!(!waiting.is_finished(), "waiter returned before resolution");
        }));
        // Cleanup also runs after a failed observation/assertion. A broken
        // production lock cycle still requires the external process watchdog.
        hub.resolve(notification.id, NotificationReaction::Reject);
        let result = waiting.join();
        if let Err(error) = checks {
            match &result {
                Ok(reaction) => eprintln!("waiter cleanup returned {reaction:?}"),
                Err(_) => eprintln!("waiter also panicked during cleanup"),
            }
            std::panic::resume_unwind(error);
        }
        assert_eq!(
            result.expect("waiter worker panicked"),
            NotificationReaction::Reject
        );
    }
}

#[cfg(test)]
mod hub_api_tests {
    use super::*;

    type Snapshots = Arc<Mutex<Vec<Vec<Notification>>>>;

    /// Subscribes to `stream` and returns the values and completions that
    /// the subscription saw before it was dropped.
    fn pending_values(stream: &ValueStream<Vec<Notification>>) -> (Snapshots, Arc<Mutex<usize>>) {
        let values = Arc::new(Mutex::new(Vec::new()));
        let completions = Arc::new(Mutex::new(0));
        let seen = values.clone();
        let completed = completions.clone();
        let _subscription = stream.subscribe_with_completion(
            move |pending| lock(&seen).push(pending),
            move || *lock(&completed) += 1,
        );
        (values, completions)
    }

    #[test]
    fn null_hub_resolve_has_no_effect_and_pending_stays_empty() {
        let hub = NullNotificationHub::new();
        let (notification, waiter) = hub.post_with_waiter(NotificationType::Confirmation, "ok?");

        hub.resolve(notification.id, NotificationReaction::Reject);

        assert_eq!(waiter.try_get(), Some(NotificationReaction::Approve));
        assert!(hub.pending().is_empty());
        let (values, completions) = pending_values(&hub.pending_stream());
        assert_eq!(*lock(&values), vec![Vec::<Notification>::new()]);
        assert_eq!(*lock(&completions), 1);
    }

    #[test]
    fn hub_api_trait_objects_dispatch_to_either_hub() {
        let hubs: [Arc<dyn NotificationHubApi>; 2] = [
            Arc::new(NotificationHub::new()),
            Arc::new(NullNotificationHub),
        ];
        for hub in hubs {
            let notification = Notification::new(NotificationType::Notification, "info");
            let waiter = hub.post_notification(notification.clone());
            hub.resolve(notification.id, NotificationReaction::Approve);

            assert_eq!(waiter.wait(), NotificationReaction::Approve);
            assert!(hub.pending().is_empty());
        }
    }

    #[test]
    fn make_confirm_over_a_null_hub_completes_true() {
        let confirm = make_confirm(NullNotificationHub, "ok?");

        assert!(confirm().wait());
        assert!(confirm().wait());
    }

    #[test]
    fn make_confirm_accepts_a_shared_trait_object() {
        let hub = NotificationHub::new();
        let shared: Arc<dyn NotificationHubApi> = Arc::new(hub.clone());
        let confirm = make_confirm(shared, "ok?");
        let decision = confirm();
        let posted = hub.pending();
        assert_eq!(posted.len(), 1);
        assert_eq!(posted[0].kind, NotificationType::Confirmation);

        hub.resolve(posted[0].id, NotificationReaction::Reject);

        assert!(!decision.wait());
    }

    #[test]
    fn post_and_resolve_traffic_retains_no_snapshot_history() {
        let hub = NotificationHub::new();
        let kept = hub.post(NotificationType::Notification, "kept");

        for _ in 0..100_000 {
            let transient = hub.post(NotificationType::Notification, "transient");
            hub.resolve(transient.id, NotificationReaction::Approve);
        }

        assert_eq!(hub.pending(), vec![kept.clone()]);
        assert!(lock(&hub.state).pending_publications.is_empty());
        #[allow(deprecated)]
        let snapshots = hub.pending_snapshots();
        assert!(snapshots.is_empty());
        // The stream keeps only the current snapshot, which it replays.
        let (values, _) = pending_values(&hub.pending_stream());
        assert_eq!(*lock(&values), vec![vec![kept]]);
    }

    #[test]
    fn dispose_retains_no_snapshot() {
        let hub = NotificationHub::new();
        let first = hub.post(NotificationType::Notification, "first");
        hub.post(NotificationType::Notification, "second");
        hub.resolve(first.id, NotificationReaction::Reject);

        hub.dispose();

        assert!(hub.pending().is_empty());
        assert!(lock(&hub.state).pending_publications.is_empty());
        #[allow(deprecated)]
        let snapshots = hub.pending_snapshots();
        assert!(snapshots.is_empty());
    }
}
