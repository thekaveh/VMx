//! Synchronous and asynchronous commands, builders, and decorators.
//!
//! Spec: `spec/07-commands.md`.

use super::*;

/// A parameterless action with queryable execution eligibility.
pub trait Command: Send + Sync {
    /// Reports whether execution is currently permitted.
    fn can_execute(&self) -> bool;
    /// Executes the command when its implementation admits the call.
    fn execute(&self);
    /// Returns the hub that announces eligibility changes.
    fn can_execute_changed(&self) -> MessageHub {
        NullMessageHub::hub()
    }
}

/// A parameterized action with parameter-sensitive execution eligibility.
pub trait CommandOf<T>: Send + Sync {
    /// Reports whether execution is permitted for `parameter`.
    fn can_execute(&self, parameter: &T) -> bool;
    /// Executes the command with `parameter` when admitted.
    fn execute(&self, parameter: T);
}

type CommandAction = Arc<Mutex<dyn FnMut() + Send + 'static>>;
type CommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
/// A cloneable synchronous command backed by an optional action and predicate.
///
/// Predicate panics are treated as not executable. Disposal makes the command
/// inert and completes its eligibility-change hub.
pub struct RelayCommand {
    action: Option<CommandAction>,
    predicate: Option<CommandPredicate>,
    disposed: Arc<Mutex<bool>>,
    can_execute_changed: MessageHub,
    _trigger_subscriptions: Arc<Vec<Subscription>>,
}

impl RelayCommand {
    /// Creates a command that invokes `action` when executable.
    pub fn new<F>(action: F) -> Self
    where
        F: FnMut() + Send + 'static,
    {
        Self {
            action: Some(Arc::new(Mutex::new(action))),
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
            _trigger_subscriptions: Arc::new(Vec::new()),
        }
    }

    /// Creates an executable command with no action.
    pub fn noop() -> Self {
        Self {
            action: None,
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
            _trigger_subscriptions: Arc::new(Vec::new()),
        }
    }

    /// Returns this command with an execution predicate.
    pub fn with_can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    /// Publishes one eligibility-change message unless disposed.
    pub fn raise_can_execute_changed(&self) {
        if *lock(&self.disposed) {
            return;
        }
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }

    /// Publishes one eligibility-change message unless disposed.
    pub fn trigger_can_execute_changed(&self) {
        self.raise_can_execute_changed();
    }

    /// Returns the eligibility-change hub.
    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    /// Returns a fluent relay-command builder.
    pub fn builder() -> RelayCommandBuilder {
        RelayCommandBuilder::default()
    }

    /// Makes the command inert and disposes its eligibility-change hub.
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
        if should_dispose {
            self.can_execute_changed.dispose();
        }
    }

    /// Wraps the command with an asynchronous confirmation gate.
    pub fn confirm<F>(self, confirm: F) -> ConfirmationDecoratorCommand<Self>
    where
        F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        ConfirmationDecoratorCommand::new(self, confirm)
    }

    /// Returns a composite that runs `other` before this command.
    pub fn precede_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CompositeCommand::new(vec![Arc::new(other), Arc::new(self)])
    }

    /// Returns a composite that runs `other` after this command.
    pub fn succeed_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CompositeCommand::new(vec![Arc::new(self), Arc::new(other)])
    }

    /// Wraps this command with optional predicate, pre-, and post-actions.
    pub fn wrap_with<FPre, FPost, FPred>(
        self,
        predicate: Option<FPred>,
        pre: Option<FPre>,
        post: Option<FPost>,
    ) -> DecoratorCommand<Self>
    where
        FPre: Fn() + Send + Sync + 'static,
        FPost: Fn() + Send + Sync + 'static,
        FPred: Fn() -> bool + Send + Sync + 'static,
    {
        DecoratorCommand::new(self, predicate, pre, post)
    }
}

impl Command for RelayCommand {
    fn can_execute(&self) -> bool {
        !*lock(&self.disposed)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(action) = &self.action {
            (lock(action))();
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }
}

type ParameterizedCommandAction<T> = Arc<Mutex<dyn FnMut(T) + Send + 'static>>;
type ParameterizedCommandPredicate<T> = Arc<dyn Fn(&T) -> bool + Send + Sync + 'static>;

#[derive(Clone)]
/// A cloneable synchronous command whose predicate and action receive a value.
pub struct RelayCommandOf<T: Clone + Send + 'static> {
    action: Option<ParameterizedCommandAction<T>>,
    predicate: Option<ParameterizedCommandPredicate<T>>,
    disposed: Arc<Mutex<bool>>,
    can_execute_changed: MessageHub,
}

impl<T: Clone + Send + 'static> RelayCommandOf<T> {
    /// Creates a parameterized command backed by `action`.
    pub fn new<F>(action: F) -> Self
    where
        F: FnMut(T) + Send + 'static,
    {
        Self {
            action: Some(Arc::new(Mutex::new(action))),
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
        }
    }

    /// Creates an executable parameterized command with no action.
    pub fn noop() -> Self {
        Self {
            action: None,
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
        }
    }

    /// Returns this command with a parameter-sensitive predicate.
    pub fn with_can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    /// Publishes one eligibility-change message unless disposed.
    pub fn raise_can_execute_changed(&self) {
        if *lock(&self.disposed) {
            return;
        }
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }

    /// Publishes one eligibility-change message unless disposed.
    pub fn trigger_can_execute_changed(&self) {
        self.raise_can_execute_changed();
    }

    /// Returns the eligibility-change hub.
    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    /// Makes the command inert.
    pub fn dispose(&self) {
        *lock(&self.disposed) = true;
    }

    /// Reports whether `parameter` is currently executable.
    pub fn can_execute(&self, parameter: &T) -> bool {
        <Self as CommandOf<T>>::can_execute(self, parameter)
    }

    /// Executes the command with `parameter` when admitted.
    pub fn execute(&self, parameter: T) {
        <Self as CommandOf<T>>::execute(self, parameter);
    }
}

impl<T: Clone + Send + 'static> CommandOf<T> for RelayCommandOf<T> {
    fn can_execute(&self, parameter: &T) -> bool {
        !*lock(&self.disposed)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate(parameter)))
                .unwrap_or(true)
    }

    fn execute(&self, parameter: T) {
        if !self.can_execute(&parameter) {
            return;
        }
        if let Some(action) = &self.action {
            (lock(action))(parameter);
        }
    }
}

#[derive(Clone, Default)]
/// A thread-safe cooperative cancellation signal.
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    /// Creates a token in the non-cancelled state.
    pub fn new() -> Self {
        Self::default()
    }

    /// Permanently marks the token as cancelled.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    /// Reports whether cancellation has been requested.
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
}

type AsyncCommandAction = Arc<dyn Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static>;
type AsyncCommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
/// A single-flight command that runs cancellable work on a worker thread.
///
/// Eligibility is false while work is running or after disposal. Fire-and-
/// forget execution routes non-cancellation failures to [`errors`](Self::errors).
pub struct AsyncRelayCommand {
    action: Option<AsyncCommandAction>,
    predicate: Option<AsyncCommandPredicate>,
    disposed: Arc<AtomicBool>,
    executing: Arc<AtomicBool>,
    active_token: Arc<Mutex<Option<CancellationToken>>>,
    cancel_pending: Arc<AtomicBool>,
    can_execute_changed: MessageHub,
    errors: MessageHub,
    throw_on_cancel: bool,
    trigger_subscriptions: Arc<Mutex<Vec<Subscription>>>,
}

struct AsyncExecutionGuard {
    executing: Arc<AtomicBool>,
    active_token: Arc<Mutex<Option<CancellationToken>>>,
    cancel_pending: Arc<AtomicBool>,
    can_execute_changed: MessageHub,
    disposed: Arc<AtomicBool>,
}

impl Drop for AsyncExecutionGuard {
    fn drop(&mut self) {
        let mut active_token = lock(&self.active_token);
        self.executing.store(false, Ordering::SeqCst);
        *active_token = None;
        self.cancel_pending.store(false, Ordering::SeqCst);
        drop(active_token);
        if !self.disposed.load(Ordering::SeqCst) {
            self.can_execute_changed.send(Message::Custom {
                sender_id: 0,
                name: "can_execute_changed".to_string(),
            });
        }
    }
}

impl AsyncRelayCommand {
    /// Creates an asynchronous command backed by `action`.
    pub fn new<F>(action: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static,
    {
        Self::from_parts(Some(Arc::new(action)), None, Vec::new(), false)
    }

    /// Creates an asynchronous command with no action.
    pub fn noop() -> Self {
        Self::from_parts(None, None, Vec::new(), false)
    }

    fn from_parts(
        action: Option<AsyncCommandAction>,
        predicate: Option<AsyncCommandPredicate>,
        triggers: Vec<MessageHub>,
        throw_on_cancel: bool,
    ) -> Self {
        let command = Self {
            action,
            predicate,
            disposed: Arc::new(AtomicBool::new(false)),
            executing: Arc::new(AtomicBool::new(false)),
            active_token: Arc::new(Mutex::new(None)),
            cancel_pending: Arc::new(AtomicBool::new(false)),
            can_execute_changed: MessageHub::new(),
            errors: MessageHub::new(),
            throw_on_cancel,
            trigger_subscriptions: Arc::new(Mutex::new(Vec::new())),
        };
        let subscriptions = triggers
            .into_iter()
            .map(|trigger| {
                let observed = command.clone();
                trigger.subscribe(move |_| observed.raise_can_execute_changed())
            })
            .collect();
        *lock(&command.trigger_subscriptions) = subscriptions;
        command
    }

    /// Returns this command with an additional execution predicate.
    pub fn with_can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    /// Reports whether a new execution can be admitted.
    pub fn can_execute(&self) -> bool {
        !self.disposed.load(Ordering::SeqCst)
            && !self.executing.load(Ordering::SeqCst)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
    }

    /// Starts fire-and-forget execution and routes failures to the error hub.
    pub fn execute(&self) {
        let _ = self.start_execution(true);
    }

    /// Starts execution and returns a handle for its result.
    pub fn execute_async(&self) -> std::thread::JoinHandle<VmxResult<()>> {
        self.start_execution(false)
    }

    fn start_execution(
        &self,
        route_fire_and_forget_errors: bool,
    ) -> std::thread::JoinHandle<VmxResult<()>> {
        if self.disposed.load(Ordering::SeqCst)
            || !self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
            || self
                .executing
                .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
                .is_err()
        {
            return std::thread::spawn(|| Ok(()));
        }
        if self.disposed.load(Ordering::SeqCst) {
            self.executing.store(false, Ordering::SeqCst);
            return std::thread::spawn(|| Ok(()));
        }
        let token = CancellationToken::new();
        {
            let mut active_token = lock(&self.active_token);
            *active_token = Some(token.clone());
            if self.cancel_pending.swap(false, Ordering::SeqCst) {
                token.cancel();
            }
        }
        if self.disposed.load(Ordering::SeqCst) {
            token.cancel();
            *lock(&self.active_token) = None;
            self.executing.store(false, Ordering::SeqCst);
            return std::thread::spawn(|| Ok(()));
        }
        self.raise_can_execute_changed();
        let action = self.action.clone();
        let errors = self.errors.clone();
        let throw_on_cancel = self.throw_on_cancel;
        let disposed = self.disposed.clone();
        let guard = AsyncExecutionGuard {
            executing: self.executing.clone(),
            active_token: self.active_token.clone(),
            cancel_pending: self.cancel_pending.clone(),
            can_execute_changed: self.can_execute_changed.clone(),
            disposed: self.disposed.clone(),
        };
        std::thread::spawn(move || {
            let _guard = guard;
            let result = action.map(|action| action(token.clone())).unwrap_or(Ok(()));
            let result = match (token.is_cancelled(), result) {
                (true, Ok(())) | (true, Err(VmxError::Cancelled)) => {
                    if throw_on_cancel {
                        Err(VmxError::Cancelled)
                    } else {
                        Ok(())
                    }
                }
                (_, result) => result,
            };

            if route_fire_and_forget_errors {
                if result.is_err()
                    && !matches!(&result, Err(VmxError::Cancelled))
                    && !disposed.load(Ordering::SeqCst)
                {
                    errors.send(Message::Custom {
                        sender_id: 0,
                        name: "error".to_string(),
                    });
                }
                Ok(())
            } else {
                result
            }
        })
    }

    /// Requests cancellation of the admitted execution, if any.
    pub fn cancel(&self) {
        if !self.executing.load(Ordering::SeqCst) {
            return;
        }
        let active_token = lock(&self.active_token);
        if !self.executing.load(Ordering::SeqCst) {
            return;
        }
        if let Some(token) = active_token.as_ref() {
            token.cancel();
        } else {
            self.cancel_pending.store(true, Ordering::SeqCst);
        }
    }

    /// Reports whether an execution is currently admitted.
    pub fn is_executing(&self) -> bool {
        self.executing.load(Ordering::SeqCst)
    }

    /// Cancels active work and disposes command-owned notification hubs.
    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::SeqCst) {
            return;
        }
        self.cancel();
        lock(&self.trigger_subscriptions).clear();
        self.can_execute_changed.dispose();
        self.errors.dispose();
    }

    /// Returns the eligibility-change hub.
    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    /// Returns the fire-and-forget error hub.
    pub fn errors(&self) -> MessageHub {
        self.errors.clone()
    }

    /// Returns a fluent asynchronous-command builder.
    pub fn builder() -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder::default()
    }

    /// Publishes one eligibility-change message unless disposed.
    pub fn raise_can_execute_changed(&self) {
        if self.disposed.load(Ordering::SeqCst) {
            return;
        }
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }
}

#[derive(Clone, Default)]
/// A fluent builder for [`AsyncRelayCommand`].
pub struct AsyncRelayCommandBuilder {
    action: Option<AsyncCommandAction>,
    predicate: Option<AsyncCommandPredicate>,
    triggers: Vec<MessageHub>,
    throw_on_cancel: bool,
}

impl AsyncRelayCommandBuilder {
    /// Sets the optional cancellable task.
    pub fn task<F>(mut self, action: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static,
    {
        self.action = Some(Arc::new(action));
        self
    }

    /// Sets the optional execution predicate.
    pub fn predicate<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    /// Adds a hub whose messages raise eligibility changes.
    pub fn trigger(mut self, trigger: MessageHub) -> Self {
        self.triggers.push(trigger);
        self
    }

    /// Configures awaited cancellation to return [`VmxError::Cancelled`].
    pub fn throw_on_cancel(mut self) -> Self {
        self.throw_on_cancel = true;
        self
    }

    /// Creates an asynchronous command from this immutable configuration.
    pub fn build(self) -> AsyncRelayCommand {
        AsyncRelayCommand::from_parts(
            self.action,
            self.predicate,
            self.triggers,
            self.throw_on_cancel,
        )
    }
}

#[derive(Clone, Default)]
/// A fluent builder for [`RelayCommand`].
pub struct RelayCommandBuilder {
    action: Option<CommandAction>,
    predicate: Option<CommandPredicate>,
    triggers: Vec<MessageHub>,
}

impl RelayCommandBuilder {
    /// Sets the optional command action.
    pub fn action<F>(mut self, action: F) -> Self
    where
        F: FnMut() + Send + 'static,
    {
        self.action = Some(Arc::new(Mutex::new(action)));
        self
    }

    /// Sets the optional execution predicate.
    pub fn can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    /// Adds a hub whose messages raise eligibility changes.
    pub fn trigger(mut self, trigger: MessageHub) -> Self {
        self.triggers.push(trigger);
        self
    }

    /// Returns the number of configured trigger hubs.
    pub fn trigger_count(&self) -> usize {
        self.triggers.len()
    }

    /// Creates a command and attaches every configured trigger.
    pub fn build(self) -> RelayCommand {
        let command = RelayCommand {
            action: self.action,
            predicate: self.predicate,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
            _trigger_subscriptions: Arc::new(Vec::new()),
        };
        let subscriptions = self
            .triggers
            .into_iter()
            .map(|trigger| {
                let hub = command.can_execute_changed.clone();
                trigger.subscribe(move |_| {
                    hub.send(Message::Custom {
                        sender_id: 0,
                        name: "can_execute_changed".to_string(),
                    });
                })
            })
            .collect::<Vec<_>>();
        RelayCommand {
            _trigger_subscriptions: Arc::new(subscriptions),
            ..command
        }
    }
}

#[derive(Clone)]
/// A command that coordinates an ordered set of child commands.
///
/// It is executable when any child is executable and invokes only executable
/// children in source order.
pub struct CompositeCommand {
    commands: Vec<Arc<dyn Command>>,
    can_execute_changed: MessageHub,
    _subscriptions: Arc<Vec<Subscription>>,
}

impl CompositeCommand {
    /// Creates a composite from dynamically dispatched child commands.
    pub fn new(commands: Vec<Arc<dyn Command>>) -> Self {
        let can_execute_changed = MessageHub::new();
        let subscriptions = commands
            .iter()
            .map(|command| {
                let hub = can_execute_changed.clone();
                command.can_execute_changed().subscribe(move |_| {
                    hub.send(Message::Custom {
                        sender_id: 0,
                        name: "can_execute_changed".to_string(),
                    });
                })
            })
            .collect::<Vec<_>>();
        Self {
            commands,
            can_execute_changed,
            _subscriptions: Arc::new(subscriptions),
        }
    }

    /// Creates a composite from a homogeneous command vector.
    pub fn from_commands<C>(commands: Vec<C>) -> Self
    where
        C: Command + Clone + 'static,
    {
        Self::new(
            commands
                .into_iter()
                .map(|command| Arc::new(command) as Arc<dyn Command>)
                .collect(),
        )
    }
}

impl Command for CompositeCommand {
    fn can_execute(&self) -> bool {
        self.commands
            .iter()
            .any(|command| evaluate_command_predicate(|| command.can_execute()))
    }

    fn execute(&self) {
        for command in &self.commands {
            if evaluate_command_predicate(|| command.can_execute()) {
                command.execute();
            }
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }
}

#[derive(Clone)]
/// A command decorator with optional additional predicate and side actions.
pub struct DecoratorCommand<C: Command + Clone> {
    inner: C,
    predicate: Option<Arc<dyn Fn() -> bool + Send + Sync>>,
    pre: Option<Arc<dyn Fn() + Send + Sync>>,
    post: Option<Arc<dyn Fn() + Send + Sync>>,
}

impl<C: Command + Clone> DecoratorCommand<C> {
    /// Wraps `inner` with optional predicate, pre-action, and post-action.
    pub fn new<FPre, FPost, FPred>(
        inner: C,
        predicate: Option<FPred>,
        pre: Option<FPre>,
        post: Option<FPost>,
    ) -> Self
    where
        FPre: Fn() + Send + Sync + 'static,
        FPost: Fn() + Send + Sync + 'static,
        FPred: Fn() -> bool + Send + Sync + 'static,
    {
        Self {
            inner,
            predicate: predicate.map(|p| Arc::new(p) as Arc<dyn Fn() -> bool + Send + Sync>),
            pre: pre.map(|p| Arc::new(p) as Arc<dyn Fn() + Send + Sync>),
            post: post.map(|p| Arc::new(p) as Arc<dyn Fn() + Send + Sync>),
        }
    }
}

impl<C: Command + Clone> Command for DecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        evaluate_command_predicate(|| self.inner.can_execute())
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(pre) = &self.pre {
            pre();
        }
        self.inner.execute();
        if let Some(post) = &self.post {
            post();
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
    }
}

#[derive(Clone)]
/// A command decorator that executes only after asynchronous confirmation.
///
/// Panics from confirmed fire-and-forget execution are isolated and announced
/// through [`errors`](Self::errors).
pub struct ConfirmationDecoratorCommand<C: Command + Clone> {
    inner: C,
    confirm: Arc<dyn Fn() -> AsyncValue<bool> + Send + Sync>,
    errors: MessageHub,
}

impl<C: Command + Clone + 'static> ConfirmationDecoratorCommand<C> {
    /// Creates a confirmation gate around `inner`.
    pub fn new<F>(inner: C, confirm: F) -> Self
    where
        F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        Self {
            inner,
            confirm: Arc::new(confirm),
            errors: MessageHub::new(),
        }
    }

    /// Returns the hub that announces isolated execution failures.
    pub fn errors(&self) -> MessageHub {
        self.errors.clone()
    }

    /// Waits for confirmation on a worker thread and executes when approved.
    pub fn execute_async(&self) -> std::thread::JoinHandle<()> {
        let decision = (self.confirm)();
        let command = self.clone();
        std::thread::spawn(move || {
            if decision.wait() {
                command.inner.execute();
            }
        })
    }

    fn execute_after(&self, confirmed: bool) {
        if !confirmed {
            return;
        }
        let result = catch_unwind(AssertUnwindSafe(|| self.inner.execute()));
        if result.is_err() {
            self.errors.send(Message::Custom {
                sender_id: 0,
                name: "error".to_string(),
            });
        }
    }
}

impl<C: Command + Clone + 'static> Command for ConfirmationDecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        evaluate_command_predicate(|| self.inner.can_execute())
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        let decision = (self.confirm)();
        if let Some(confirmed) = decision.try_get() {
            self.execute_after(confirmed);
        } else {
            let command = self.clone();
            std::thread::spawn(move || command.execute_after(decision.wait()));
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
    }
}
