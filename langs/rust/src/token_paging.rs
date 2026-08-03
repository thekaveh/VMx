//! Accumulating forward-only token paging.
//!
//! Spec: `spec/21-collections.md`; ADR-0033.

use super::{
    lock, next_id, Arc, CollectionChangeAction, CollectionChangedMessage, Command, Message,
    MessageHub, Mutex, RelayCommand, VmNode,
};
use std::{
    sync::Condvar,
    thread::{self, ThreadId},
};

struct TokenPagerLifecycleState {
    active_owner: Option<ThreadId>,
    active_depth: usize,
    dispose_requested: bool,
    cancel_active: bool,
    disposed: bool,
}

struct TokenPagerLifecycle {
    state: Mutex<TokenPagerLifecycleState>,
    ready: Condvar,
}

impl TokenPagerLifecycle {
    fn new() -> Self {
        Self {
            state: Mutex::new(TokenPagerLifecycleState {
                active_owner: None,
                active_depth: 0,
                dispose_requested: false,
                cancel_active: false,
                disposed: false,
            }),
            ready: Condvar::new(),
        }
    }

    fn is_terminal(&self) -> bool {
        let state = lock(&self.state);
        state.dispose_requested || state.disposed
    }

    fn begin_commit(self: &Arc<Self>) -> Option<TokenPagerCommit> {
        let current = thread::current().id();
        let mut state = lock(&self.state);
        while state.active_owner.is_some() && state.active_owner != Some(current) {
            state = self
                .ready
                .wait(state)
                .unwrap_or_else(|error| error.into_inner());
        }
        if state.dispose_requested || state.disposed {
            return None;
        }
        if state.active_owner == Some(current) {
            state.active_depth += 1;
        } else {
            state.active_owner = Some(current);
            state.active_depth = 1;
        }
        Some(TokenPagerCommit {
            lifecycle: self.clone(),
        })
    }

    fn request_dispose(&self) {
        let current = thread::current().id();
        let mut state = lock(&self.state);
        if state.disposed {
            return;
        }
        if state.dispose_requested {
            if state.active_owner == Some(current) {
                state.cancel_active = true;
                return;
            }
            while !state.disposed {
                state = self
                    .ready
                    .wait(state)
                    .unwrap_or_else(|error| error.into_inner());
            }
            return;
        }
        if state.active_owner == Some(current) {
            state.dispose_requested = true;
            state.cancel_active = true;
            return;
        }
        state.dispose_requested = true;
        while state.active_owner.is_some() {
            state = self
                .ready
                .wait(state)
                .unwrap_or_else(|error| error.into_inner());
        }
        state.disposed = true;
        self.ready.notify_all();
    }

    fn commit_allowed(&self) -> bool {
        !lock(&self.state).cancel_active
    }

    fn finish_commit(&self) {
        let mut state = lock(&self.state);
        debug_assert_eq!(state.active_owner, Some(thread::current().id()));
        debug_assert!(state.active_depth > 0);
        state.active_depth -= 1;
        if state.active_depth > 0 {
            return;
        }
        state.active_owner = None;
        if state.dispose_requested {
            state.disposed = true;
        }
        self.ready.notify_all();
    }
}

struct TokenPagerCommit {
    lifecycle: Arc<TokenPagerLifecycle>,
}

impl TokenPagerCommit {
    fn is_allowed(&self) -> bool {
        self.lifecycle.commit_allowed()
    }
}

impl Drop for TokenPagerCommit {
    fn drop(&mut self) {
        self.lifecycle.finish_commit();
    }
}

#[derive(Clone)]
/// An accumulated, forward-only page sequence driven by continuation tokens.
pub struct TokenPagedComposition<
    T: Clone + PartialEq + Send + 'static,
    Token: Clone + Send + 'static,
> {
    id: usize,
    items: Arc<Mutex<Vec<T>>>,
    next_token: Arc<Mutex<Option<Token>>>,
    has_more: Arc<Mutex<bool>>,
    hub: MessageHub,
    load_more_command: RelayCommand,
    refresh_command: RelayCommand,
    lifecycle: Arc<TokenPagerLifecycle>,
}

impl<T: Clone + PartialEq + Send + 'static, Token: Clone + Send + 'static>
    TokenPagedComposition<T, Token>
{
    /// Creates an empty pager whose default loader immediately reaches the end.
    pub fn new(initial_token: Option<Token>) -> Self {
        Self::with_loader(initial_token, |_token| (Vec::new(), None))
    }

    /// Creates a pager with a private message hub and the supplied loader.
    pub fn with_loader<F>(initial_token: Option<Token>, loader: F) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        Self::build(initial_token, loader, MessageHub::new())
    }

    /// Creates a pager that publishes collection resets to `hub`.
    pub fn with_loader_and_hub<F>(initial_token: Option<Token>, loader: F, hub: MessageHub) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        Self::build(initial_token, loader, hub)
    }

    fn build<F>(initial_token: Option<Token>, loader: F, hub: MessageHub) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        let id = next_id();
        let items = Arc::new(Mutex::new(Vec::new()));
        let initial_token = Arc::new(Mutex::new(initial_token));
        let next_token = Arc::new(Mutex::new(None));
        let has_more = Arc::new(Mutex::new(true));
        let loader = Arc::new(loader);
        let lifecycle = Arc::new(TokenPagerLifecycle::new());

        let load_more_items = items.clone();
        let load_more_token = next_token.clone();
        let load_more_has_more = has_more.clone();
        let load_more_loader = loader.clone();
        let load_more_hub = hub.clone();
        let load_more_lifecycle = lifecycle.clone();
        let load_more_command = RelayCommand::new(move || {
            if load_more_lifecycle.is_terminal() {
                return;
            }
            let token = lock(&load_more_token).clone();
            if load_more_lifecycle.is_terminal() {
                return;
            }
            let (page, next) = load_more_loader(token);
            let Some(commit) = load_more_lifecycle.begin_commit() else {
                return;
            };
            if !commit.is_allowed() {
                return;
            }
            let mut changed = false;
            if !page.is_empty() {
                lock(&load_more_items).extend(page);
                changed = true;
            }
            let has_more = next.is_some();
            let previous_token = std::mem::replace(&mut *lock(&load_more_token), next);
            *lock(&load_more_has_more) = has_more;
            if changed {
                load_more_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    sender_name: "TokenPagedComposition".to_string(),
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
            drop(commit);
            drop(previous_token);
        })
        .with_can_execute({
            let has_more = has_more.clone();
            move || *lock(&has_more)
        });

        let refresh_items = items.clone();
        let refresh_initial_token = initial_token.clone();
        let refresh_next_token = next_token.clone();
        let refresh_has_more = has_more.clone();
        let refresh_loader = loader.clone();
        let refresh_hub = hub.clone();
        let refresh_lifecycle = lifecycle.clone();
        let refresh_command = RelayCommand::new(move || {
            if refresh_lifecycle.is_terminal() {
                return;
            }
            let token = lock(&refresh_initial_token).clone();
            if refresh_lifecycle.is_terminal() {
                return;
            }
            let (page, next) = refresh_loader(token);
            let Some(commit) = refresh_lifecycle.begin_commit() else {
                return;
            };
            if !commit.is_allowed() {
                return;
            }
            let should_replace = lock(&refresh_items).as_slice() != page.as_slice();
            if !commit.is_allowed() {
                return;
            }
            let previous_items = if should_replace {
                Some(std::mem::replace(&mut *lock(&refresh_items), page))
            } else {
                None
            };
            let has_more = next.is_some();
            let previous_token = std::mem::replace(&mut *lock(&refresh_next_token), next);
            *lock(&refresh_has_more) = has_more;
            if should_replace {
                refresh_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    sender_name: "TokenPagedComposition".to_string(),
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
            drop(commit);
            drop(previous_token);
            drop(previous_items);
        });

        Self {
            id,
            items,
            next_token,
            has_more,
            hub,
            load_more_command,
            refresh_command,
            lifecycle,
        }
    }

    /// Returns this pager's stable sender identity.
    pub fn id(&self) -> usize {
        self.id
    }

    /// Returns a snapshot of all items accumulated so far.
    pub fn items(&self) -> Vec<T> {
        lock(&self.items).clone()
    }

    /// Returns the continuation token for the next page.
    pub fn current_token(&self) -> Option<Token> {
        lock(&self.next_token).clone()
    }

    /// Reports whether the loader supplied another continuation token.
    pub fn has_more(&self) -> bool {
        *lock(&self.has_more)
    }

    /// Reports whether another page can currently be loaded.
    pub fn can_load_more(&self) -> bool {
        self.load_more_command.can_execute()
    }

    /// Returns the command that appends the next page.
    pub fn load_more_command(&self) -> RelayCommand {
        self.load_more_command.clone()
    }

    /// Returns the command that reloads from the initial token.
    pub fn refresh_command(&self) -> RelayCommand {
        self.refresh_command.clone()
    }

    /// Returns the hub used for collection reset messages.
    pub fn hub(&self) -> MessageHub {
        self.hub.clone()
    }

    /// Executes the configured refresh command.
    pub fn refresh(&self) {
        if self.lifecycle.is_terminal() {
            return;
        }
        self.refresh_command.execute();
    }

    /// Appends one page from an ad hoc loader and updates continuation state.
    pub fn load_more<F>(&self, loader: F)
    where
        F: FnOnce(Option<Token>) -> (Vec<T>, Option<Token>),
    {
        if self.lifecycle.is_terminal() {
            return;
        }
        let token = lock(&self.next_token).clone();
        if self.lifecycle.is_terminal() {
            return;
        }
        let (items, next_token) = loader(token);
        let Some(commit) = self.lifecycle.begin_commit() else {
            return;
        };
        if !commit.is_allowed() {
            return;
        }
        let changed = !items.is_empty();
        if changed {
            lock(&self.items).extend(items);
        }
        let has_more = next_token.is_some();
        let previous_token = std::mem::replace(&mut *lock(&self.next_token), next_token);
        *lock(&self.has_more) = has_more;
        if changed {
            self.hub
                .send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: self.id,
                    sender_name: "TokenPagedComposition".to_string(),
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
        }
        drop(commit);
        drop(previous_token);
    }

    /// Executes the configured next-page command.
    pub fn load_next(&self) {
        if self.lifecycle.is_terminal() {
            return;
        }
        self.load_more_command.execute();
    }

    /// Makes loading and refreshing terminally inert and disposes both commands.
    pub fn dispose(&self) {
        self.lifecycle.request_dispose();
        self.load_more_command.dispose();
        self.refresh_command.dispose();
    }
}

impl<T: VmNode, Token: Clone + Send + 'static> TokenPagedComposition<T, Token> {
    /// Creates a pager that constructs each loaded VM before publishing its reset.
    pub fn with_auto_construct_loader<F>(initial_token: Option<Token>, loader: F) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        let hub = MessageHub::new();
        let id = next_id();
        let items = Arc::new(Mutex::new(Vec::new()));
        let initial_token = Arc::new(Mutex::new(initial_token));
        let next_token = Arc::new(Mutex::new(None));
        let has_more = Arc::new(Mutex::new(true));
        let loader = Arc::new(loader);
        let lifecycle = Arc::new(TokenPagerLifecycle::new());

        let load_items = items.clone();
        let load_token = next_token.clone();
        let load_has_more = has_more.clone();
        let load_loader = loader.clone();
        let load_hub = hub.clone();
        let load_lifecycle = lifecycle.clone();
        let load_more_command = RelayCommand::new(move || {
            if load_lifecycle.is_terminal() {
                return;
            }
            let token = lock(&load_token).clone();
            if load_lifecycle.is_terminal() {
                return;
            }
            let (page, next) = load_loader(token);
            let Some(commit) = load_lifecycle.begin_commit() else {
                return;
            };
            for item in &page {
                let _ = item.construct();
            }
            if !commit.is_allowed() {
                return;
            }
            let changed = !page.is_empty();
            if changed {
                lock(&load_items).extend(page);
            }
            let has_more = next.is_some();
            let previous_token = std::mem::replace(&mut *lock(&load_token), next);
            *lock(&load_has_more) = has_more;
            if changed {
                load_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    sender_name: "TokenPagedComposition".to_string(),
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
            drop(commit);
            drop(previous_token);
        })
        .with_can_execute({
            let has_more = has_more.clone();
            move || *lock(&has_more)
        });

        let refresh_items = items.clone();
        let refresh_initial_token = initial_token.clone();
        let refresh_next_token = next_token.clone();
        let refresh_has_more = has_more.clone();
        let refresh_loader = loader.clone();
        let refresh_hub = hub.clone();
        let refresh_lifecycle = lifecycle.clone();
        let refresh_command = RelayCommand::new(move || {
            if refresh_lifecycle.is_terminal() {
                return;
            }
            let token = lock(&refresh_initial_token).clone();
            if refresh_lifecycle.is_terminal() {
                return;
            }
            let (page, next) = refresh_loader(token);
            let Some(commit) = refresh_lifecycle.begin_commit() else {
                return;
            };
            let should_replace = lock(&refresh_items).as_slice() != page.as_slice();
            if !commit.is_allowed() {
                return;
            }
            if should_replace {
                for item in &page {
                    let _ = item.construct();
                }
            }
            if !commit.is_allowed() {
                return;
            }
            let previous_items = if should_replace {
                Some(std::mem::replace(&mut *lock(&refresh_items), page))
            } else {
                None
            };
            let has_more = next.is_some();
            let previous_token = std::mem::replace(&mut *lock(&refresh_next_token), next);
            *lock(&refresh_has_more) = has_more;
            if should_replace {
                refresh_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    sender_name: "TokenPagedComposition".to_string(),
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
            drop(commit);
            drop(previous_token);
            drop(previous_items);
        });

        Self {
            id,
            items,
            next_token,
            has_more,
            hub,
            load_more_command,
            refresh_command,
            lifecycle,
        }
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::{TokenPagedComposition, TokenPagerLifecycle};
    use std::{
        sync::{
            atomic::{AtomicUsize, Ordering},
            mpsc, Arc, Mutex,
        },
        thread,
        time::Duration,
    };

    struct ReentrantItem {
        pager: Arc<Mutex<Option<TokenPagedComposition<ReentrantItem, usize>>>>,
    }

    impl Clone for ReentrantItem {
        fn clone(&self) -> Self {
            Self {
                pager: self.pager.clone(),
            }
        }
    }

    impl PartialEq for ReentrantItem {
        fn eq(&self, _other: &Self) -> bool {
            if let Some(pager) = self.pager.lock().expect("item pager").clone() {
                pager.dispose();
            }
            true
        }
    }

    struct ReentrantToken {
        pager: Arc<Mutex<Option<TokenPagedComposition<i32, ReentrantToken>>>>,
    }

    impl Clone for ReentrantToken {
        fn clone(&self) -> Self {
            if let Some(pager) = self.pager.lock().expect("token pager").clone() {
                pager.dispose();
            }
            Self {
                pager: self.pager.clone(),
            }
        }
    }

    #[test]
    fn nested_commits_keep_foreign_disposers_waiting_for_the_outer_guard() {
        let lifecycle = Arc::new(TokenPagerLifecycle::new());
        let outer = lifecycle.begin_commit().expect("outer commit");
        let inner = lifecycle.begin_commit().expect("nested commit");
        drop(inner);

        let (started_tx, started_rx) = mpsc::channel();
        let (finished_tx, finished_rx) = mpsc::channel();
        let first_disposer = {
            let lifecycle = lifecycle.clone();
            let started_tx = started_tx.clone();
            let finished_tx = finished_tx.clone();
            thread::spawn(move || {
                started_tx.send(()).expect("signal start");
                lifecycle.request_dispose();
                finished_tx.send(()).expect("signal finish");
            })
        };
        let second_disposer = {
            let lifecycle = lifecycle.clone();
            thread::spawn(move || {
                started_tx.send(()).expect("signal start");
                lifecycle.request_dispose();
                finished_tx.send(()).expect("signal finish");
            })
        };

        started_rx.recv().expect("disposer started");
        started_rx.recv().expect("second disposer started");
        assert!(finished_rx.recv_timeout(Duration::from_millis(50)).is_err());
        drop(outer);
        finished_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("first disposer finished after outer guard");
        finished_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("second disposer finished after outer guard");
        first_disposer.join().expect("first disposer thread");
        second_disposer.join().expect("second disposer thread");
        assert!(lifecycle.is_terminal());
    }

    #[test]
    fn reentrant_disposal_cancels_the_active_commit() {
        let lifecycle = Arc::new(TokenPagerLifecycle::new());
        let commit = lifecycle.begin_commit().expect("active commit");

        lifecycle.request_dispose();

        assert!(!commit.is_allowed());
        drop(commit);
        assert!(lifecycle.is_terminal());
    }

    #[test]
    fn equality_reentry_cannot_advance_refresh_state_after_disposal() {
        let holder = Arc::new(Mutex::new(None));
        let loaded = ReentrantItem {
            pager: holder.clone(),
        };
        let calls = Arc::new(AtomicUsize::new(0));
        let pages = TokenPagedComposition::with_loader(None, {
            let calls = calls.clone();
            move |_| {
                let call = calls.fetch_add(1, Ordering::SeqCst);
                (vec![loaded.clone()], Some(call + 1))
            }
        });
        *holder.lock().expect("item holder") = Some(pages.clone());

        pages.load_next();
        pages.refresh();

        assert_eq!(pages.current_token(), Some(1));
        assert!(pages.has_more());
    }

    #[test]
    fn token_clone_reentry_prevents_the_loader_from_starting() {
        let holder = Arc::new(Mutex::new(None));
        let calls = Arc::new(AtomicUsize::new(0));
        let pages = TokenPagedComposition::with_loader(
            Some(ReentrantToken {
                pager: holder.clone(),
            }),
            {
                let calls = calls.clone();
                move |_| {
                    calls.fetch_add(1, Ordering::SeqCst);
                    (vec![1], None)
                }
            },
        );
        *holder.lock().expect("token holder") = Some(pages.clone());

        pages.refresh();

        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert!(pages.items().is_empty());
    }
}
