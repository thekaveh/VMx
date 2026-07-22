//! Notification values, pending waiters, and resolution hubs.
//!
//! Spec: `spec/16-notifications.md`; ADR-0031.

use super::{
    lock, Arc, AsyncValue, AtomicU64, BTreeMap, Context, Future, HashMap, Message, MessageHub,
    Mutex, Ordering, Pin, Poll,
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
}

impl Future for NotificationWaiter {
    type Output = NotificationReaction;

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        Pin::new(&mut self.completion).poll(context)
    }
}

#[derive(Default)]
struct NotificationHubState {
    pending: BTreeMap<u64, Notification>,
    reactions: HashMap<u64, NotificationReaction>,
    completions: HashMap<u64, AsyncValue<NotificationReaction>>,
    pending_snapshots: Vec<Vec<Notification>>,
    disposed: bool,
}

#[derive(Clone, Default)]
/// Concurrent notification queue with pending snapshots and first-wins resolution.
pub struct NotificationHub {
    state: Arc<Mutex<NotificationHubState>>,
    pending_changed: MessageHub,
}

impl NotificationHub {
    /// Creates an empty notification hub.
    pub fn new() -> Self {
        Self::default()
    }

    /// Posts `notification` or reuses its existing pending waiter.
    pub fn post_notification(&self, notification: Notification) -> NotificationWaiter {
        let notification_id = notification.id;
        let (completion, publish) = {
            let mut state = lock(&self.state);
            if state.disposed {
                state
                    .reactions
                    .insert(notification_id, NotificationReaction::Pending);
                (AsyncValue::ready(NotificationReaction::Pending), false)
            } else if let Some(completion) = state.completions.get(&notification_id).cloned() {
                (completion, false)
            } else {
                let completion = AsyncValue::pending();
                state.pending.insert(notification_id, notification);
                state
                    .reactions
                    .insert(notification_id, NotificationReaction::Pending);
                state
                    .completions
                    .insert(notification_id, completion.clone());
                let snapshot = state.pending.values().cloned().collect();
                state.pending_snapshots.push(snapshot);
                (completion, true)
            }
        };
        if publish {
            self.publish_pending();
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
        let completion = {
            let mut state = lock(&self.state);
            if state.pending.remove(&notification_id).is_none() {
                return;
            }
            state.reactions.insert(notification_id, reaction);
            let completion = state.completions.remove(&notification_id);
            let snapshot = state.pending.values().cloned().collect();
            state.pending_snapshots.push(snapshot);
            completion
        };
        // spec/16-notifications.md §2.2: emit the new Pending value BEFORE
        // completing the awaitable returned by the original post. The four peers
        // publish then complete; do the same.
        self.publish_pending();
        if let Some(completion) = completion {
            completion.resolve(reaction);
        }
    }

    /// Returns a snapshot of currently pending notifications.
    pub fn pending(&self) -> Vec<Notification> {
        lock(&self.state).pending.values().cloned().collect()
    }

    /// Returns the hub that publishes committed pending-list changes.
    pub fn pending_changed(&self) -> MessageHub {
        self.pending_changed.clone()
    }

    /// Returns the history of committed pending snapshots.
    pub fn pending_snapshots(&self) -> Vec<Vec<Notification>> {
        lock(&self.state).pending_snapshots.clone()
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
        let completions = {
            let mut state = lock(&self.state);
            if state.disposed {
                return;
            }
            state.disposed = true;
            let pending_ids = state.pending.keys().copied().collect::<Vec<_>>();
            for id in pending_ids {
                state.reactions.insert(id, NotificationReaction::Pending);
            }
            let completions = state
                .completions
                .drain()
                .map(|(_, value)| value)
                .collect::<Vec<_>>();
            state.pending.clear();
            state.pending_snapshots.push(Vec::new());
            completions
        };
        // spec §2.2 order: emit the (now empty) Pending value before resuming
        // waiters, matching resolve() and the four peers.
        self.publish_pending();
        for completion in completions {
            completion.resolve(NotificationReaction::Pending);
        }
    }

    fn publish_pending(&self) {
        self.pending_changed.send(Message::Custom {
            sender_id: 0,
            sender_name: "NotificationHub".to_string(),
            name: "pending".to_string(),
        });
    }
}

/// Null notification hub that returns safe immediate approvals.
pub struct NullNotificationHub;

impl NullNotificationHub {
    /// Returns an immediately approved waiter without retaining the notification.
    pub fn post(_notification: Notification) -> NotificationWaiter {
        NotificationWaiter {
            completion: AsyncValue::ready(NotificationReaction::Approve),
        }
    }

    /// Creates a notification and returns it with an immediately approved waiter.
    pub fn post_message(message: impl Into<String>) -> (Notification, NotificationWaiter) {
        let notification = Notification {
            id: 0,
            kind: NotificationType::Notification,
            message: message.into(),
        };
        (
            notification,
            NotificationWaiter {
                completion: AsyncValue::ready(NotificationReaction::Approve),
            },
        )
    }
}

/// Creates a cloneable confirmation predicate backed by `hub` and `prompt`.
pub fn make_confirm(
    hub: NotificationHub,
    prompt: impl Into<String>,
) -> impl Fn() -> AsyncValue<bool> + Clone {
    let prompt = Arc::new(prompt.into());
    move || {
        let (_, waiter) = hub.post_with_waiter(NotificationType::Confirmation, (*prompt).clone());
        let decision = AsyncValue::pending();
        let resolved = decision.clone();
        std::thread::spawn(move || {
            resolved.resolve(waiter.wait() == NotificationReaction::Approve);
        });
        decision
    }
}
