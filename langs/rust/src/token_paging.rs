//! Accumulating forward-only token paging.
//!
//! Spec: `spec/21-collections.md`; ADR-0033.

use super::*;

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

        let load_more_items = items.clone();
        let load_more_token = next_token.clone();
        let load_more_has_more = has_more.clone();
        let load_more_loader = loader.clone();
        let load_more_hub = hub.clone();
        let load_more_command = RelayCommand::new(move || {
            let token = lock(&load_more_token).clone();
            let (page, next) = load_more_loader(token);
            let mut changed = false;
            if !page.is_empty() {
                lock(&load_more_items).extend(page);
                changed = true;
            }
            *lock(&load_more_token) = next.clone();
            *lock(&load_more_has_more) = next.is_some();
            if changed {
                load_more_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
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
        let refresh_command = RelayCommand::new(move || {
            let token = lock(&refresh_initial_token).clone();
            let (page, next) = refresh_loader(token);
            let changed = {
                let mut items = lock(&refresh_items);
                if items.iter().take(page.len()).eq(page.iter()) {
                    false
                } else {
                    *items = page;
                    true
                }
            };
            *lock(&refresh_next_token) = next.clone();
            *lock(&refresh_has_more) = next.is_some();
            if changed {
                refresh_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
        });

        Self {
            id,
            items,
            next_token,
            has_more,
            hub,
            load_more_command,
            refresh_command,
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
        self.refresh_command.execute();
    }

    /// Appends one page from an ad hoc loader and updates continuation state.
    pub fn load_more<F>(&self, loader: F)
    where
        F: FnOnce(Option<Token>) -> (Vec<T>, Option<Token>),
    {
        let token = lock(&self.next_token).clone();
        let (items, next_token) = loader(token);
        let changed = !items.is_empty();
        if changed {
            lock(&self.items).extend(items);
        }
        *lock(&self.next_token) = next_token.clone();
        *lock(&self.has_more) = next_token.is_some();
        if changed {
            self.hub
                .send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: self.id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
        }
    }

    /// Executes the configured next-page command.
    pub fn load_next(&self) {
        self.load_more_command.execute();
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

        let load_items = items.clone();
        let load_token = next_token.clone();
        let load_has_more = has_more.clone();
        let load_loader = loader.clone();
        let load_hub = hub.clone();
        let load_more_command = RelayCommand::new(move || {
            let token = lock(&load_token).clone();
            let (page, next) = load_loader(token);
            let changed = !page.is_empty();
            if changed {
                for item in &page {
                    let _ = item.construct();
                }
                lock(&load_items).extend(page);
            }
            *lock(&load_token) = next.clone();
            *lock(&load_has_more) = next.is_some();
            if changed {
                load_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
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
        let refresh_command = RelayCommand::new(move || {
            let token = lock(&refresh_initial_token).clone();
            let (page, next) = refresh_loader(token);
            let changed = {
                let mut items = lock(&refresh_items);
                if items.iter().take(page.len()).eq(page.iter()) {
                    false
                } else {
                    for item in &page {
                        let _ = item.construct();
                    }
                    *items = page;
                    true
                }
            };
            *lock(&refresh_next_token) = next.clone();
            *lock(&refresh_has_more) = next.is_some();
            if changed {
                refresh_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
        });

        Self {
            id,
            items,
            next_token,
            has_more,
            hub,
            load_more_command,
            refresh_command,
        }
    }
}
