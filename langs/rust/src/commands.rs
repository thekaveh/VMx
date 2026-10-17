//! Synchronous and asynchronous commands, builders, and decorators.
//!
//! Spec: `spec/04-commands.md`.

use super::{
    catch_unwind, evaluate_command_predicate, lock, resume_unwind, spawn_worker, thread, Arc,
    AssertUnwindSafe, AsyncValue, AtomicBool, AtomicU64, Context, Future, Message, MessageHub,
    Mutex, NullMessageHub, Ordering, Pin, Poll, Subscription, ThreadId, ValueStream,
    ValueSubscription, VmxError, VmxResult, Weak,
};

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

    /// Returns this command's awaitable entry point, or `None` for a
    /// synchronous command.
    ///
    /// Calling the returned closure makes one execution attempt through the
    /// command's awaitable path and returns an [`AsyncValue`] that settles
    /// when that attempt completes, not when it starts: with `Ok(())`, with
    /// the operation's [`VmxError`], or as panicked with the original panic
    /// payload. An attempt the command does not admit, because it is busy,
    /// disabled, or disposed, settles `Ok(())` at once. As with any awaited
    /// call, a failure is returned to the caller and is not published on the
    /// command's error stream.
    ///
    /// The default is `None`. [`AsyncRelayCommand`] and
    /// [`ConfirmationDecoratorCommand`] return an entry point, and a
    /// confirmation decorator uses it to await an asynchronous inner command
    /// (spec `04-commands.md` §8.3.2, ADR-0145). An `Arc<T>` forwards to `T`.
    ///
    /// ```
    /// use vmx::{AsyncRelayCommand, AsyncValue, Command, CommandExt, RelayCommand, VmxError};
    ///
    /// let save = AsyncRelayCommand::new(|_token| Err(VmxError::Other("offline".into())));
    /// let start = save.as_async().expect("an async command has an entry point");
    /// assert_eq!(start().wait(), Err(VmxError::Other("offline".into())));
    ///
    /// // A confirmation decorator is asynchronous too, and awaits its inner.
    /// let confirmed = save.confirm(|| AsyncValue::ready(true));
    /// let start = confirmed.as_async().expect("a confirmation has an entry point");
    /// assert_eq!(start().wait(), Err(VmxError::Other("offline".into())));
    ///
    /// assert!(RelayCommand::noop().as_async().is_none());
    /// ```
    fn as_async(&self) -> Option<Box<dyn FnOnce() -> AsyncValue<VmxResult<()>> + Send>> {
        None
    }
}

/// Shared commands are commands: an `Arc<T>` delegates to `T`.
///
/// This lets a command that is not `Clone`, or a `dyn Command` trait object,
/// use [`CommandExt`] through an `Arc` without implementing `Clone` itself.
impl<T: Command + ?Sized> Command for Arc<T> {
    fn can_execute(&self) -> bool {
        (**self).can_execute()
    }

    fn execute(&self) {
        (**self).execute();
    }

    fn can_execute_changed(&self) -> MessageHub {
        (**self).can_execute_changed()
    }

    fn as_async(&self) -> Option<Box<dyn FnOnce() -> AsyncValue<VmxResult<()>> + Send>> {
        (**self).as_async()
    }
}

/// An absent `wrap_with` pre- or post-action, usable where `None` would need a
/// type annotation.
pub const NO_HOOK: Option<fn()> = None;

/// An absent `wrap_with` predicate, usable where `None` would need a type
/// annotation.
pub const NO_PREDICATE: Option<fn() -> bool> = None;

/// Fluent composition helpers for every cloneable command (spec §9, ADR-0027).
///
/// The trait is implemented for every `Command + Clone + 'static`, so the
/// command a helper returns chains further. Each helper moves the receiver
/// into the returned wrapper; clones of VMx commands share their state, so
/// keep a clone to keep using the receiver directly. Wrap a command that is
/// not `Clone` in an [`Arc`] to use the helpers. Import the trait with
/// `use vmx::CommandExt;`; `RelayCommand` also keeps the same methods as
/// inherent methods, so existing calls need no import.
///
/// ```
/// use std::sync::{Arc, Mutex};
/// use vmx::{AsyncValue, Command, CommandExt, RelayCommand, NO_HOOK};
///
/// let log = Arc::new(Mutex::new(Vec::new()));
/// let save = RelayCommand::new({
///     let log = log.clone();
///     move || log.lock().unwrap().push("save")
/// });
/// let audit = RelayCommand::new({
///     let log = log.clone();
///     move || log.lock().unwrap().push("audit")
/// });
/// let command = save
///     .confirm(|| AsyncValue::ready(true))
///     .wrap_with(Some(|| true), NO_HOOK, NO_HOOK)
///     .succeed_with(audit);
///
/// command.execute();
/// assert_eq!(*log.lock().unwrap(), vec!["save", "audit"]);
/// ```
pub trait CommandExt: Command + Clone + Sized + 'static {
    /// Wraps the command with an asynchronous confirmation gate.
    fn confirm<F>(self, confirm: F) -> ConfirmationDecoratorCommand<Self>
    where
        F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        ConfirmationDecoratorCommand::new(self, confirm)
    }

    /// Returns a composite that runs `other` before this command.
    fn precede_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CompositeCommand::new(vec![Arc::new(other), Arc::new(self)])
    }

    /// Returns a composite that runs `other` after this command.
    fn succeed_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CompositeCommand::new(vec![Arc::new(self), Arc::new(other)])
    }

    /// Wraps this command with optional predicate, pre-, and post-actions.
    ///
    /// Pass [`NO_PREDICATE`] or [`NO_HOOK`] for an absent argument.
    fn wrap_with<FPre, FPost, FPred>(
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

impl<C: Command + Clone + 'static> CommandExt for C {}

/// A parameterized action with parameter-sensitive execution eligibility.
pub trait CommandOf<T>: Send + Sync {
    /// Reports whether execution is permitted for `parameter`.
    fn can_execute(&self, parameter: &T) -> bool;
    /// Executes the command with `parameter` when admitted.
    fn execute(&self, parameter: T);
}

/// How a relay command runs an admitted execution.
///
/// The other flavors hold no lock while a relay command's action runs, so an
/// `execute` made from inside the action evaluates `can_execute` and, when
/// admitted, runs at once (spec `04-commands.md` §3). A shared `Fn` action
/// does the same here. Rust cannot call an `FnMut` action again while it is
/// running, so an exclusive action defers such a call instead of blocking its
/// own thread (see [`ExclusiveAction`]).
enum RelayAction<P> {
    /// Runs with no lock held, so nested and concurrent executions run at once.
    Shared(Arc<dyn Fn(P) + Send + Sync + 'static>),
    /// Runs on one thread at a time.
    Exclusive(Arc<ExclusiveAction<P>>),
}

impl<P> Clone for RelayAction<P> {
    fn clone(&self) -> Self {
        match self {
            Self::Shared(action) => Self::Shared(Arc::clone(action)),
            Self::Exclusive(action) => Self::Exclusive(Arc::clone(action)),
        }
    }
}

impl<P> RelayAction<P> {
    fn shared<F>(action: F) -> Self
    where
        F: Fn(P) + Send + Sync + 'static,
    {
        Self::Shared(Arc::new(action))
    }

    fn exclusive<F>(action: F) -> Self
    where
        F: FnMut(P) + Send + 'static,
    {
        Self::Exclusive(Arc::new(ExclusiveAction {
            body: Mutex::new(Box::new(action)),
            turn: Mutex::new(ExclusiveTurn {
                owner: None,
                deferred: Vec::new(),
            }),
        }))
    }

    /// Runs an execution that `can_execute` admitted. `live` reports that
    /// the command is not disposed.
    fn execute(&self, parameter: P, live: impl Fn() -> bool) {
        match self {
            Self::Shared(action) => action(parameter),
            Self::Exclusive(action) => action.execute(parameter, live),
        }
    }
}

/// An `FnMut` relay action, which runs on one thread at a time.
///
/// An admitted execution from another thread waits until the action is free.
/// One made on the thread that is running the action, from the action or from
/// an observer it notifies, cannot wait for it without deadlocking, and cannot
/// run inline because the action is already borrowed. It is deferred: it runs
/// after the running action returns, before the outermost `execute` returns.
/// Deferred executions start in the order inline recursion would start them.
/// An execution that waited, for either reason, does not run once the command
/// is disposed.
struct ExclusiveAction<P> {
    body: Mutex<Box<dyn FnMut(P) + Send + 'static>>,
    turn: Mutex<ExclusiveTurn<P>>,
}

/// The thread running an [`ExclusiveAction`], and the executions it deferred.
struct ExclusiveTurn<P> {
    owner: Option<ThreadId>,
    deferred: Vec<P>,
}

impl<P> ExclusiveAction<P> {
    fn execute(&self, parameter: P, live: impl Fn() -> bool) {
        let current = thread::current().id();
        {
            let mut turn = lock(&self.turn);
            if turn.owner == Some(current) {
                // This thread is running the action further up its stack.
                turn.deferred.push(parameter);
                return;
            }
        }
        // A stack, so nested executions start in inline-recursion order.
        let mut pending = vec![parameter];
        while let Some(parameter) = pending.pop() {
            let mut body = lock(&self.body);
            if !live() {
                // Disposal is final: no waiting execution runs.
                return;
            }
            let run = ExclusiveRun::claim(&self.turn, current);
            body(parameter);
            let deferred = run.end();
            drop(body);
            pending.extend(deferred.into_iter().rev());
        }
    }
}

/// Marks the current thread as running an [`ExclusiveAction`] while its body
/// lock is held. If the action panics, dropping the mark clears it and
/// discards the executions deferred during the run.
struct ExclusiveRun<'a, P> {
    turn: Option<&'a Mutex<ExclusiveTurn<P>>>,
}

impl<'a, P> ExclusiveRun<'a, P> {
    fn claim(turn: &'a Mutex<ExclusiveTurn<P>>, owner: ThreadId) -> Self {
        lock(turn).owner = Some(owner);
        Self { turn: Some(turn) }
    }

    /// Ends the run and returns the executions deferred during it.
    fn end(mut self) -> Vec<P> {
        self.turn.take().map(Self::release).unwrap_or_default()
    }

    fn release(turn: &Mutex<ExclusiveTurn<P>>) -> Vec<P> {
        let mut turn = lock(turn);
        turn.owner = None;
        std::mem::take(&mut turn.deferred)
    }
}

impl<P> Drop for ExclusiveRun<'_, P> {
    fn drop(&mut self) {
        if let Some(turn) = self.turn.take() {
            drop(Self::release(turn));
        }
    }
}

type CommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
/// A cloneable synchronous command backed by an optional action and predicate.
///
/// Predicate panics are treated as not executable. Disposal makes the command
/// inert and completes its eligibility-change hub.
///
/// # Nested execution
///
/// Every `execute` evaluates `can_execute` when it is called, as in the other
/// flavors, and no lock is held while the predicate runs or while the command
/// notifies observers. The action is an `FnMut`, so it runs on one thread at a
/// time: an admitted `execute` from another thread waits until the running
/// action returns. Rust cannot call an `FnMut` again while it is running, so
/// an admitted `execute` made on the same thread while the action runs, from
/// the action itself or from an observer it notifies, cannot run inline as it
/// does in the other flavors. It is deferred instead: it runs after the
/// running action returns and before the outermost `execute` returns. Nested
/// executions start in the order inline recursion would start them. An
/// execution that waited does not run once the command is disposed.
///
/// ```
/// use std::sync::{Arc, Mutex};
/// use vmx::{Command, RelayCommand};
///
/// let log = Arc::new(Mutex::new(Vec::new()));
/// let slot = Arc::new(Mutex::new(None::<RelayCommand>));
/// let command = RelayCommand::new({
///     let (log, slot) = (log.clone(), slot.clone());
///     move || {
///         log.lock().unwrap().push("start");
///         let command = slot.lock().unwrap().clone().unwrap();
///         command.execute(); // runs once this run returns
///         log.lock().unwrap().push("end");
///     }
/// })
/// .with_can_execute({
///     let log = log.clone();
///     move || log.lock().unwrap().len() < 3
/// });
/// *slot.lock().unwrap() = Some(command.clone());
///
/// command.execute();
///
/// // The nested call made by the second run finds `can_execute` false.
/// assert_eq!(*log.lock().unwrap(), ["start", "end", "start", "end"]);
/// ```
pub struct RelayCommand {
    action: Option<RelayAction<()>>,
    predicate: Option<CommandPredicate>,
    disposed: Arc<Mutex<bool>>,
    can_execute_changed: MessageHub,
    _trigger_subscriptions: Arc<Vec<Subscription>>,
}

impl RelayCommand {
    /// Creates a command that invokes `action` when executable.
    ///
    /// See [Nested execution](Self#nested-execution) for an `execute` made
    /// while `action` runs.
    pub fn new<F>(mut action: F) -> Self
    where
        F: FnMut() + Send + 'static,
    {
        Self::with_action(Some(RelayAction::exclusive(move |()| action())))
    }

    /// Creates a command whose shared `action` runs with no lock held, so a
    /// nested or concurrent `execute` runs at once, as in the other flavors.
    pub(crate) fn new_shared<F>(action: F) -> Self
    where
        F: Fn() + Send + Sync + 'static,
    {
        Self::with_action(Some(RelayAction::shared(move |()| action())))
    }

    /// Creates an executable command with no action.
    pub fn noop() -> Self {
        Self::with_action(None)
    }

    fn with_action(action: Option<RelayAction<()>>) -> Self {
        Self {
            action,
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
            sender_name: "RelayCommand".to_string(),
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
            self.can_execute_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "RelayCommand".to_string(),
                name: "can_execute_changed".to_string(),
            });
            self.can_execute_changed.dispose();
        }
    }

    /// Wraps the command with an asynchronous confirmation gate.
    ///
    /// Delegates to [`CommandExt::confirm`].
    pub fn confirm<F>(self, confirm: F) -> ConfirmationDecoratorCommand<Self>
    where
        F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        CommandExt::confirm(self, confirm)
    }

    /// Returns a composite that runs `other` before this command.
    ///
    /// Delegates to [`CommandExt::precede_with`].
    pub fn precede_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CommandExt::precede_with(self, other)
    }

    /// Returns a composite that runs `other` after this command.
    ///
    /// Delegates to [`CommandExt::succeed_with`].
    pub fn succeed_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CommandExt::succeed_with(self, other)
    }

    /// Wraps this command with optional predicate, pre-, and post-actions.
    ///
    /// Delegates to [`CommandExt::wrap_with`].
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
        CommandExt::wrap_with(self, predicate, pre, post)
    }
}

impl Command for RelayCommand {
    fn can_execute(&self) -> bool {
        if *lock(&self.disposed) {
            return false;
        }
        let allowed = self
            .predicate
            .as_ref()
            .map(|predicate| evaluate_command_predicate(|| predicate()))
            .unwrap_or(true);
        allowed && !*lock(&self.disposed)
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(action) = &self.action {
            action.execute((), || !*lock(&self.disposed));
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }
}

type ParameterizedCommandPredicate<T> = Arc<dyn Fn(&T) -> bool + Send + Sync + 'static>;

#[derive(Clone)]
/// A cloneable synchronous command whose predicate and action receive a value.
///
/// Nested execution follows [`RelayCommand`]'s rules: an admitted `execute`
/// made on the thread running the action is deferred, with its parameter,
/// until the running action returns (see
/// [Nested execution](RelayCommand#nested-execution)).
pub struct RelayCommandOf<T: Clone + Send + 'static> {
    action: Option<RelayAction<T>>,
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
            action: Some(RelayAction::exclusive(action)),
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
            sender_name: "RelayCommandOf".to_string(),
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
            self.can_execute_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "RelayCommandOf".to_string(),
                name: "can_execute_changed".to_string(),
            });
            self.can_execute_changed.dispose();
        }
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
        if *lock(&self.disposed) {
            return false;
        }
        let allowed = self
            .predicate
            .as_ref()
            .map(|predicate| evaluate_command_predicate(|| predicate(parameter)))
            .unwrap_or(true);
        allowed && !*lock(&self.disposed)
    }

    fn execute(&self, parameter: T) {
        if !self.can_execute(&parameter) {
            return;
        }
        if let Some(action) = &self.action {
            action.execute(parameter, || !*lock(&self.disposed));
        }
    }
}

#[derive(Clone, Default)]
/// A thread-safe cooperative cancellation signal.
pub struct CancellationToken {
    state: Arc<CancellationState>,
}

type CancellationListener = Arc<dyn Fn() + Send + Sync + 'static>;

#[derive(Default)]
struct CancellationState {
    cancelled: AtomicBool,
    listeners: Mutex<CancellationListeners>,
}

#[derive(Default)]
struct CancellationListeners {
    next_id: u64,
    entries: Vec<(u64, CancellationListener)>,
}

impl CancellationToken {
    /// Creates a token in the non-cancelled state.
    pub fn new() -> Self {
        Self::default()
    }

    /// Permanently marks the token as cancelled.
    pub fn cancel(&self) {
        if self.state.cancelled.swap(true, Ordering::SeqCst) {
            return;
        }
        let listeners = std::mem::take(&mut lock(&self.state.listeners).entries);
        for (_, listener) in listeners {
            let _ = catch_unwind(AssertUnwindSafe(|| listener()));
        }
    }

    /// Reports whether cancellation has been requested.
    pub fn is_cancelled(&self) -> bool {
        self.state.cancelled.load(Ordering::SeqCst)
    }

    /// Runs `listener` once, on the cancelling thread, when the token is
    /// cancelled. Returns `None` without keeping the listener when the token
    /// is already cancelled; dropping the registration removes the listener.
    pub(crate) fn on_cancel(
        &self,
        listener: CancellationListener,
    ) -> Option<CancellationRegistration> {
        let mut listeners = lock(&self.state.listeners);
        if self.is_cancelled() {
            return None;
        }
        let id = listeners.next_id;
        listeners.next_id += 1;
        listeners.entries.push((id, listener));
        Some(CancellationRegistration {
            state: Arc::downgrade(&self.state),
            id,
        })
    }
}

/// Removes a [`CancellationToken`] listener when dropped.
pub(crate) struct CancellationRegistration {
    state: Weak<CancellationState>,
    id: u64,
}

impl Drop for CancellationRegistration {
    fn drop(&mut self) {
        let Some(state) = self.state.upgrade() else {
            return;
        };
        let removed = {
            let mut listeners = lock(&state.listeners);
            listeners
                .entries
                .iter()
                .position(|(id, _)| *id == self.id)
                .map(|index| listeners.entries.remove(index))
        };
        drop(removed);
    }
}

#[derive(Clone)]
/// A hot typed stream of a command's fire-and-forget failures.
///
/// Each failure reaches the subscribers present when it is published, once,
/// as the original [`VmxError`]. Late subscribers do not receive earlier
/// failures, cancellations never appear, and the stream completes when its
/// command is disposed (spec `04-commands.md` §8.3.1 and §10.4, ADR-0137).
/// Subscriber panics are isolated from the command and other subscribers.
pub struct CommandErrorStream {
    stream: ValueStream<Option<VmxError>>,
}

impl CommandErrorStream {
    fn new() -> Self {
        Self {
            stream: ValueStream::hot(None),
        }
    }

    /// Subscribes to failures published after this call.
    pub fn subscribe<F>(&self, handler: F) -> ValueSubscription
    where
        F: Fn(VmxError) + Send + Sync + 'static,
    {
        self.stream.subscribe(move |error| {
            if let Some(error) = error {
                handler(error);
            }
        })
    }

    /// Subscribes to failures and receives one callback when the command is disposed.
    pub fn subscribe_with_completion<F, C>(&self, handler: F, completion: C) -> ValueSubscription
    where
        F: Fn(VmxError) + Send + Sync + 'static,
        C: Fn() + Send + Sync + 'static,
    {
        self.stream.subscribe_with_completion(
            move |error| {
                if let Some(error) = error {
                    handler(error);
                }
            },
            completion,
        )
    }

    fn publish(&self, error: VmxError) {
        self.stream.send(Some(error));
    }

    fn dispose(&self) {
        self.stream.dispose();
    }
}

/// Describes a caught panic as a [`VmxError`]. A panic payload is not a
/// clonable error, so only its message travels (ADR-0137).
fn panic_error(payload: &(dyn std::any::Any + Send)) -> VmxError {
    let message = payload
        .downcast_ref::<&str>()
        .map(|message| (*message).to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned());
    VmxError::Other(match message {
        Some(message) => format!("command panicked: {message}"),
        None => "command panicked".to_string(),
    })
}

type AsyncCommandAction = Arc<dyn Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static>;
type AsyncCommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
/// A single-flight command that runs cancellable work on a worker thread.
///
/// Eligibility is false while work is running or after disposal. Fire-and-
/// forget execution publishes each non-cancellation failure on
/// [`error_stream`](Self::error_stream).
pub struct AsyncRelayCommand {
    action: Option<AsyncCommandAction>,
    predicate: Option<AsyncCommandPredicate>,
    disposed: Arc<AtomicBool>,
    execution_epoch: Arc<AtomicU64>,
    active_token: Arc<Mutex<Option<CancellationToken>>>,
    cancel_pending: Arc<AtomicBool>,
    can_execute_changed: MessageHub,
    errors: MessageHub,
    error_stream: CommandErrorStream,
    throw_on_cancel: bool,
    trigger_subscriptions: Arc<Mutex<Vec<Subscription>>>,
    #[cfg(test)]
    test_executions: Arc<Mutex<Option<Arc<test_execution::Collector>>>>,
}

/// Where an admitted [`AsyncRelayCommand`] execution reports its result.
enum ExecutionReport {
    /// Fire-and-forget: publish a non-cancellation failure on the error stream.
    ErrorStream,
    /// Return the result through the worker's join handle.
    JoinHandle,
    /// Settle this completion once the execution has released admission.
    Completion(AsyncValue<VmxResult<()>>),
}

struct AsyncExecutionGuard {
    execution_epoch: Arc<AtomicU64>,
    active_token: Arc<Mutex<Option<CancellationToken>>>,
    cancel_pending: Arc<AtomicBool>,
    can_execute_changed: MessageHub,
    disposed: Arc<AtomicBool>,
}

impl Drop for AsyncExecutionGuard {
    fn drop(&mut self) {
        let mut active_token = lock(&self.active_token);
        self.execution_epoch.fetch_add(1, Ordering::SeqCst);
        *active_token = None;
        self.cancel_pending.store(false, Ordering::SeqCst);
        drop(active_token);
        if !self.disposed.load(Ordering::SeqCst) {
            self.can_execute_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "AsyncRelayCommand".to_string(),
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
            execution_epoch: Arc::new(AtomicU64::new(0)),
            active_token: Arc::new(Mutex::new(None)),
            cancel_pending: Arc::new(AtomicBool::new(false)),
            can_execute_changed: MessageHub::new(),
            errors: MessageHub::new(),
            error_stream: CommandErrorStream::new(),
            throw_on_cancel,
            trigger_subscriptions: Arc::new(Mutex::new(Vec::new())),
            #[cfg(test)]
            test_executions: Arc::new(Mutex::new(None)),
        };
        let subscriptions = triggers
            .into_iter()
            .map(|trigger| {
                // Capture only what the signal needs. A full command clone
                // would make the trigger hub own the command that owns this
                // subscription, so a dropped command would never be freed.
                let disposed = command.disposed.clone();
                let can_execute_changed = command.can_execute_changed.clone();
                trigger.subscribe(move |_| {
                    if !disposed.load(Ordering::SeqCst) {
                        can_execute_changed.send(async_can_execute_changed_message());
                    }
                })
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
        let epoch = self.execution_epoch.load(Ordering::SeqCst);
        epoch.is_multiple_of(2)
            && !self.disposed.load(Ordering::SeqCst)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
            && !self.disposed.load(Ordering::SeqCst)
            && self.execution_epoch.load(Ordering::SeqCst) == epoch
    }

    /// Starts fire-and-forget execution and routes failures to the error hub.
    ///
    /// An admitted execution runs its task on one worker thread. A rejected
    /// call (no action, an execution already running, a false predicate, or
    /// a disposed command) returns without starting a thread.
    pub fn execute(&self) {
        let Some(handle) = self.start_execution(ExecutionReport::ErrorStream) else {
            return;
        };
        #[cfg(test)]
        if let Some(collector) = lock(&self.test_executions).clone() {
            collector.register(handle);
            return;
        }
        drop(handle);
    }

    /// Starts execution and returns a handle for its result.
    ///
    /// A rejected call returns a handle whose thread completes with `Ok(())`
    /// at once. `JoinHandle` can only come from a spawned thread, so that
    /// handle still costs one short-lived thread; use [`execute`](Self::execute)
    /// when the result is not needed.
    pub fn execute_async(&self) -> std::thread::JoinHandle<VmxResult<()>> {
        self.start_execution(ExecutionReport::JoinHandle)
            .unwrap_or_else(|| spawn_worker(|| Ok(())))
    }

    /// Runs an admitted execution and waits for its result, or returns
    /// `Ok(Ok(()))` at once, without a thread, for a rejected call.
    pub(crate) fn execute_and_join(&self) -> std::thread::Result<VmxResult<()>> {
        self.start_execution(ExecutionReport::JoinHandle)
            .map_or(Ok(Ok(())), std::thread::JoinHandle::join)
    }

    /// The awaitable entry point behind [`Command::as_async`]: an admitted
    /// execution runs on the command's own worker, which settles the result
    /// after releasing admission; a rejected call settles `Ok(())` at once,
    /// without a thread.
    fn execute_awaitable(&self) -> AsyncValue<VmxResult<()>> {
        let completion = AsyncValue::pending();
        if self
            .start_execution(ExecutionReport::Completion(completion.clone()))
            .is_none()
        {
            completion.resolve(Ok(()));
        }
        completion
    }

    fn start_execution(
        &self,
        report: ExecutionReport,
    ) -> Option<std::thread::JoinHandle<VmxResult<()>>> {
        let epoch = self.execution_epoch.load(Ordering::SeqCst);
        if self.action.is_none() || !epoch.is_multiple_of(2) || self.disposed.load(Ordering::SeqCst)
        {
            return None;
        }
        let allowed = self
            .predicate
            .as_ref()
            .map(|predicate| evaluate_command_predicate(|| predicate()))
            .unwrap_or(true);
        if !allowed
            || self.disposed.load(Ordering::SeqCst)
            || self
                .execution_epoch
                .compare_exchange(epoch, epoch + 1, Ordering::SeqCst, Ordering::SeqCst)
                .is_err()
        {
            return None;
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
            self.execution_epoch.fetch_add(1, Ordering::SeqCst);
            return None;
        }
        self.raise_can_execute_changed();
        let action = self.action.clone();
        let errors = self.errors.clone();
        let error_stream = self.error_stream.clone();
        let throw_on_cancel = self.throw_on_cancel;
        let disposed = self.disposed.clone();
        let guard = AsyncExecutionGuard {
            execution_epoch: self.execution_epoch.clone(),
            active_token: self.active_token.clone(),
            cancel_pending: self.cancel_pending.clone(),
            can_execute_changed: self.can_execute_changed.clone(),
            disposed: self.disposed.clone(),
        };
        #[cfg(test)]
        let collector = lock(&self.test_executions).clone();
        let route_fire_and_forget_errors = matches!(report, ExecutionReport::ErrorStream);
        let completion = match report {
            ExecutionReport::Completion(completion) => Some(completion),
            ExecutionReport::ErrorStream | ExecutionReport::JoinHandle => None,
        };
        let run = move || {
            let _guard = guard;
            let result = action
                .map(|action| {
                    if route_fire_and_forget_errors {
                        // A fire-and-forget fault must not be lost (spec/04
                        // §10.4); a panic travels as its message (ADR-0137).
                        catch_unwind(AssertUnwindSafe(|| action(token.clone())))
                            .unwrap_or_else(|payload| Err(panic_error(&*payload)))
                    } else {
                        action(token.clone())
                    }
                })
                .unwrap_or(Ok(()));
            #[cfg(test)]
            if let Some(collector) = collector {
                collector.record(result.clone());
            }
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
                if let Err(error) = &result {
                    if !matches!(error, VmxError::Cancelled) && !disposed.load(Ordering::SeqCst) {
                        error_stream.publish(error.clone());
                        errors.send(Message::Custom {
                            sender_id: 0,
                            sender_name: "AsyncRelayCommand".to_string(),
                            name: "error".to_string(),
                        });
                    }
                }
                Ok(())
            } else {
                result
            }
        };
        Some(spawn_worker(move || match completion {
            None => run(),
            // `run` drops the guard, releasing admission, before the awaiter
            // observes the outcome; a panicking task settles it as panicked.
            Some(completion) => {
                match catch_unwind(AssertUnwindSafe(run)) {
                    Ok(result) => completion.resolve(result),
                    Err(payload) => completion.settle_panicked(payload),
                };
                Ok(())
            }
        }))
    }

    /// Requests cancellation of the admitted execution, if any.
    pub fn cancel(&self) {
        if !self.is_executing() {
            return;
        }
        let active_token = lock(&self.active_token);
        if !self.is_executing() {
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
        !self
            .execution_epoch
            .load(Ordering::SeqCst)
            .is_multiple_of(2)
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
        self.error_stream.dispose();
    }

    /// Returns the eligibility-change hub.
    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    /// Returns the fire-and-forget error hub.
    ///
    /// Each failure arrives as a `Message::Custom` named `"error"` with no
    /// payload. Use [`error_stream`](Self::error_stream) to receive the
    /// original [`VmxError`].
    #[deprecated(
        since = "0.31.0",
        note = "carries only an \"error\" marker; use `error_stream()`, which delivers the original `VmxError`"
    )]
    pub fn errors(&self) -> MessageHub {
        self.errors.clone()
    }

    /// Returns the typed stream of fire-and-forget failures.
    ///
    /// [`execute`](Self::execute) publishes each non-cancellation failure here
    /// as the original [`VmxError`]; an awaited
    /// [`execute_async`](Self::execute_async) returns it instead and publishes
    /// nothing.
    pub fn error_stream(&self) -> CommandErrorStream {
        self.error_stream.clone()
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
        self.can_execute_changed
            .send(async_can_execute_changed_message());
    }
}

fn async_can_execute_changed_message() -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "AsyncRelayCommand".to_string(),
        name: "can_execute_changed".to_string(),
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
    action: Option<RelayAction<()>>,
    predicate: Option<CommandPredicate>,
    triggers: Vec<MessageHub>,
}

impl RelayCommandBuilder {
    /// Sets the optional command action.
    ///
    /// See [Nested execution](RelayCommand#nested-execution) for an `execute`
    /// made while `action` runs.
    pub fn action<F>(mut self, mut action: F) -> Self
    where
        F: FnMut() + Send + 'static,
    {
        self.action = Some(RelayAction::exclusive(move |()| action()));
        self
    }

    /// Sets a shared action that runs with no lock held, so a nested or
    /// concurrent `execute` runs at once, as in the other flavors.
    pub(crate) fn shared_action<F>(mut self, action: F) -> Self
    where
        F: Fn() + Send + Sync + 'static,
    {
        self.action = Some(RelayAction::shared(move |()| action()));
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
                        sender_name: "RelayCommandBuilder".to_string(),
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

impl Command for AsyncRelayCommand {
    /// Same admission check as the inherent [`AsyncRelayCommand::can_execute`].
    fn can_execute(&self) -> bool {
        AsyncRelayCommand::can_execute(self)
    }

    /// Starts fire-and-forget execution and returns without waiting for the
    /// async body; failures are routed to [`AsyncRelayCommand::errors`], as
    /// with the inherent [`AsyncRelayCommand::execute`].
    fn execute(&self) {
        AsyncRelayCommand::execute(self);
    }

    /// Returns the same eligibility hub as the inherent method.
    fn can_execute_changed(&self) -> MessageHub {
        AsyncRelayCommand::can_execute_changed(self)
    }

    /// Returns the awaitable entry point. Each call makes one attempt with
    /// the same admission as [`AsyncRelayCommand::execute_async`]: an admitted
    /// task runs on the command's own worker thread, and the returned value
    /// settles after the execution has released admission, with the task's
    /// result (cancellation normalized as for `execute_async`) or as panicked
    /// with the task's panic payload. Nothing is published on
    /// [`error_stream`](AsyncRelayCommand::error_stream). A rejected attempt
    /// settles `Ok(())` at once without starting a thread.
    fn as_async(&self) -> Option<Box<dyn FnOnce() -> AsyncValue<VmxResult<()>> + Send>> {
        let command = self.clone();
        Some(Box::new(move || command.execute_awaitable()))
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
    subscriptions: Arc<Mutex<Vec<Subscription>>>,
    disposed: Arc<AtomicBool>,
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
                        sender_name: "CompositeCommand".to_string(),
                        name: "can_execute_changed".to_string(),
                    });
                })
            })
            .collect::<Vec<_>>();
        Self {
            commands,
            can_execute_changed,
            subscriptions: Arc::new(Mutex::new(subscriptions)),
            disposed: Arc::new(AtomicBool::new(false)),
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

    /// Makes the composite inert (spec §8.4, ADR-0134).
    ///
    /// Idempotent and shared by clones. The child commands stay owned by their
    /// creator; the composite releases its subscriptions to their change hubs,
    /// announces the change once, and completes its own hub.
    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::SeqCst) {
            return;
        }
        let subscriptions = std::mem::take(&mut *lock(&self.subscriptions));
        drop(subscriptions);
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            sender_name: "CompositeCommand".to_string(),
            name: "can_execute_changed".to_string(),
        });
        self.can_execute_changed.dispose();
    }

    fn is_disposed(&self) -> bool {
        self.disposed.load(Ordering::SeqCst)
    }
}

impl Command for CompositeCommand {
    fn can_execute(&self) -> bool {
        !self.is_disposed()
            && self
                .commands
                .iter()
                .any(|command| evaluate_command_predicate(|| command.can_execute()))
            && !self.is_disposed()
    }

    fn execute(&self) {
        // A child may dispose the composite; no later child runs once disposal
        // is observed (spec §8.4, ADR-0134).
        for command in &self.commands {
            if self.is_disposed() {
                return;
            }
            if evaluate_command_predicate(|| command.can_execute()) && !self.is_disposed() {
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
    disposed: Arc<AtomicBool>,
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
            disposed: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Makes the decorator inert (spec §8.4, ADR-0134).
    ///
    /// Idempotent and shared by clones. The inner command stays owned by its
    /// creator, and the decorator's change hub remains the inner command's.
    pub fn dispose(&self) {
        self.disposed.store(true, Ordering::SeqCst);
    }

    fn is_disposed(&self) -> bool {
        self.disposed.load(Ordering::SeqCst)
    }
}

impl<C: Command + Clone> Command for DecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        // The inner and extra predicates may dispose the decorator.
        !self.is_disposed()
            && evaluate_command_predicate(|| self.inner.can_execute())
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
            && !self.is_disposed()
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(pre) = &self.pre {
            pre();
        }
        // The pre-action may dispose the decorator: skip the inner command but
        // keep the admitted pre/post pair balanced (spec §8.4, ADR-0134).
        if !self.is_disposed() {
            self.inner.execute();
        }
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
/// Panics from fire-and-forget confirmation or confirmed execution are
/// isolated and published on [`error_stream`](Self::error_stream).
///
/// An inner command whose [`Command::as_async`] returns an entry point, such
/// as an [`AsyncRelayCommand`] or another confirmation decorator, is
/// asynchronous: an awaited [`execute_async`](Self::execute_async) completes
/// when the inner operation completes, while a fire-and-forget
/// [`execute`](Command::execute) starts it through the inner's own `execute`,
/// so the inner reports its failures on its own error stream (spec
/// `04-commands.md` §8.3.2, ADR-0145). The decorator never cancels or
/// disposes the inner command.
pub struct ConfirmationDecoratorCommand<C: Command + Clone> {
    inner: C,
    confirm: Arc<dyn Fn() -> AsyncValue<bool> + Send + Sync>,
    errors: MessageHub,
    error_stream: CommandErrorStream,
    disposed: Arc<AtomicBool>,
}

/// Executor-neutral completion returned by
/// [`ConfirmationDecoratorCommand::execute_async`].
///
/// The handle implements [`Future`] and exposes blocking [`join`](Self::join)
/// plus non-blocking [`is_finished`](Self::is_finished) conveniences without
/// creating a native worker thread.
///
/// A failed execution ends with a payload: the original panic payload when
/// `confirm` or the inner command panicked, or the original [`VmxError`] when
/// an asynchronous inner operation failed. [`join`](Self::join) returns that
/// payload as `Err`, and `.await` resumes it as a panic. Call the decorator's
/// [`Command::as_async`] entry point instead to receive an inner failure as a
/// [`VmxResult`].
///
/// # Migration from the pre-publication API
///
/// Before Rust 0.27.0, `execute_async` returned
/// `std::thread::JoinHandle<()>` and retained one operating-system thread for
/// every unresolved confirmation. Rust 0.27.0 intentionally changes that
/// concrete return type to `ConfirmationExecution`. Inferred callers using
/// `.join()` keep the same call shape; callers that named `JoinHandle<()>`
/// should use this type and may also `.await` it. `is_finished()` is retained
/// as a truthful compatibility-shaped poll. There is no `thread()` accessor
/// because no native worker exists.
pub struct ConfirmationExecution {
    completion: AsyncValue<VmxResult<()>>,
}

impl ConfirmationExecution {
    /// Blocks until execution completes, returning the original panic payload
    /// or the asynchronous inner operation's [`VmxError`] as `Err`.
    pub fn join(self) -> std::thread::Result<()> {
        match self.completion.wait_result() {
            Ok(Ok(())) => Ok(()),
            Ok(Err(error)) => Err(Box::new(error)),
            Err(panic) => Err(panic
                .take_payload()
                .unwrap_or_else(|| Box::new(panic.message().to_string()))),
        }
    }

    /// Reports whether the confirmation flow has reached a terminal outcome.
    ///
    /// This mirrors the useful polling shape of `JoinHandle::is_finished`
    /// without implying that a native thread exists.
    pub fn is_finished(&self) -> bool {
        self.completion.try_result().is_some()
    }
}

impl Future for ConfirmationExecution {
    type Output = ();

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        // A panicked completion re-raises its original payload while polled.
        match Pin::new(&mut self.completion).poll(context) {
            Poll::Ready(Ok(())) => Poll::Ready(()),
            Poll::Ready(Err(error)) => resume_unwind(Box::new(error)),
            Poll::Pending => Poll::Pending,
        }
    }
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
            error_stream: CommandErrorStream::new(),
            disposed: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Returns the hub that announces isolated execution failures.
    ///
    /// Each failure arrives as a `Message::Custom` named `"error"` with no
    /// payload. Use [`error_stream`](Self::error_stream) to receive it as a
    /// [`VmxError`].
    #[deprecated(
        since = "0.31.0",
        note = "carries only an \"error\" marker; use `error_stream()`, which delivers a `VmxError`"
    )]
    pub fn errors(&self) -> MessageHub {
        self.errors.clone()
    }

    /// Returns the typed stream of isolated fire-and-forget failures.
    ///
    /// A panic from `confirm` or from the confirmed inner execution arrives as
    /// [`VmxError::Other`] carrying the panic message. The panic payload itself
    /// is not clonable, so it stays with
    /// [`execute_async`](Self::execute_async), whose
    /// [`join`](ConfirmationExecution::join) returns it unchanged (ADR-0137).
    ///
    /// An asynchronous inner command started by a fire-and-forget
    /// [`execute`](Command::execute) reports its own failures on its own error
    /// stream, and an awaited inner failure goes to the awaiter; neither
    /// appears here (spec `04-commands.md` §8.3.2).
    pub fn error_stream(&self) -> CommandErrorStream {
        self.error_stream.clone()
    }

    /// Runs the confirmation flow and returns an executor-neutral completion.
    ///
    /// The completion settles at once for a disabled or disposed decorator,
    /// when `confirm` resolves `false`, or when the decorator was disposed
    /// while the confirmation was pending; none of these invokes the inner
    /// command. After a `true` confirmation the inner command is invoked
    /// exactly once: an asynchronous inner through its [`Command::as_async`]
    /// entry point, so the completion settles when the inner operation
    /// finishes, and a synchronous inner through [`Command::execute`], so it
    /// settles when that call returns (spec `04-commands.md` §8.3.2,
    /// ADR-0145).
    ///
    /// The inner command keeps its own admission and cancellation: a busy
    /// [`AsyncRelayCommand`] drops the call and the completion settles at
    /// once, and cancelling the inner settles it with the inner's own
    /// outcome. Disposing the decorator after the inner has started neither
    /// cancels nor disposes it, and the completion still settles when the
    /// inner operation does.
    ///
    /// Failures go to the caller, never to
    /// [`error_stream`](Self::error_stream); see [`ConfirmationExecution`].
    pub fn execute_async(&self) -> ConfirmationExecution {
        ConfirmationExecution {
            completion: self.execute_awaitable(),
        }
    }

    /// The awaited flow behind [`execute_async`](Self::execute_async) and the
    /// [`Command::as_async`] entry point.
    fn execute_awaitable(&self) -> AsyncValue<VmxResult<()>> {
        if self.disposed.load(Ordering::SeqCst) || !self.can_execute() {
            return AsyncValue::ready(Ok(()));
        }
        let decision = match catch_unwind(AssertUnwindSafe(|| (self.confirm)())) {
            Ok(decision) => decision,
            Err(payload) => return AsyncValue::panicked(payload),
        };
        let command = self.clone();
        // `and_then` runs on the thread that resolves the confirmation, with
        // no lock held. A panicked confirmation (ADR-0138) or a panicking
        // synchronous inner settles the result as panicked with its payload.
        decision.and_then(move |confirmed| {
            // Disposal while the confirmation was pending starts no inner
            // work (spec §8.4, ADR-0134).
            if !confirmed || command.disposed.load(Ordering::SeqCst) {
                return AsyncValue::ready(Ok(()));
            }
            match command.inner.as_async() {
                Some(start) => start(),
                None => {
                    command.inner.execute();
                    AsyncValue::ready(Ok(()))
                }
            }
        })
    }

    /// Makes the decorator inert and disposes its error hub and stream.
    pub fn dispose(&self) {
        if !self.disposed.swap(true, Ordering::SeqCst) {
            self.errors.dispose();
            self.error_stream.dispose();
        }
    }

    fn execute_after(&self, confirmed: bool) {
        if !confirmed || self.disposed.load(Ordering::SeqCst) {
            return;
        }
        if let Err(payload) = catch_unwind(AssertUnwindSafe(|| self.inner.execute())) {
            self.publish_error(panic_error(payload.as_ref()));
        }
    }

    fn publish_error(&self, error: VmxError) {
        if self.disposed.load(Ordering::SeqCst) {
            return;
        }
        self.error_stream.publish(error);
        self.errors.send(Message::Custom {
            sender_id: 0,
            sender_name: "ConfirmationDecoratorCommand".to_string(),
            name: "error".to_string(),
        });
    }
}

impl<C: Command + Clone + 'static> Command for ConfirmationDecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        !self.disposed.load(Ordering::SeqCst)
            && evaluate_command_predicate(|| self.inner.can_execute())
            && !self.disposed.load(Ordering::SeqCst)
    }

    fn execute(&self) {
        if self.disposed.load(Ordering::SeqCst) || !self.can_execute() {
            return;
        }
        let decision = match catch_unwind(AssertUnwindSafe(|| (self.confirm)())) {
            Ok(decision) => decision,
            Err(payload) => {
                self.publish_error(panic_error(payload.as_ref()));
                return;
            }
        };
        let command = self.clone();
        decision.when_settled(move |decision| match decision {
            Ok(confirmed) => command.execute_after(confirmed),
            Err(panic) => command.publish_error(VmxError::Other(format!(
                "command panicked: {}",
                panic.message()
            ))),
        });
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
    }

    /// Returns the awaitable entry point: each call runs the same flow as
    /// [`ConfirmationDecoratorCommand::execute_async`], and the returned value
    /// settles with `Ok(())`, with an asynchronous inner operation's
    /// [`VmxError`] unchanged, or as panicked with the payload of a panicking
    /// `confirm` or inner command. A wrapping confirmation decorator uses it
    /// to await this decorator's confirmation and inner operation.
    fn as_async(&self) -> Option<Box<dyn FnOnce() -> AsyncValue<VmxResult<()>> + Send>> {
        let command = self.clone();
        Some(Box::new(move || command.execute_awaitable()))
    }
}

#[cfg(test)]
pub(crate) mod test_execution {
    use super::{lock, Arc, AsyncRelayCommand, Mutex, VmxResult};
    use std::{sync::mpsc, thread::JoinHandle};

    #[derive(Default)]
    pub(crate) struct Collector {
        handles: Mutex<Vec<JoinHandle<VmxResult<()>>>>,
        results: Mutex<Vec<VmxResult<()>>>,
        registered: Mutex<Option<mpsc::Sender<()>>>,
    }

    impl Collector {
        pub(super) fn register(&self, handle: JoinHandle<VmxResult<()>>) {
            lock(&self.handles).push(handle);
            if let Some(sender) = lock(&self.registered).as_ref() {
                let _ = sender.send(());
            }
        }

        pub(super) fn record(&self, result: VmxResult<()>) {
            lock(&self.results).push(result);
        }
    }

    pub(crate) struct Registration {
        command: AsyncRelayCommand,
        collector: Arc<Collector>,
        pub(crate) registered: mpsc::Receiver<()>,
    }

    impl Registration {
        pub(crate) fn new(command: AsyncRelayCommand) -> Self {
            let (sender, registered) = mpsc::channel();
            let collector = Arc::new(Collector::default());
            *lock(&collector.registered) = Some(sender);
            {
                let mut slot = lock(&command.test_executions);
                assert!(slot.is_none(), "command already observed");
                *slot = Some(collector.clone());
            }
            Self {
                command,
                collector,
                registered,
            }
        }

        // Call after all execute callers exit. Join outside both locks, and do
        // not stop collecting failures when an earlier worker failed.
        pub(crate) fn join_all(&self) -> (usize, Vec<VmxResult<()>>, Vec<String>) {
            let handles = std::mem::take(&mut *lock(&self.collector.handles));
            let count = handles.len();
            let mut failures = Vec::new();
            for handle in handles {
                match handle.join() {
                    Ok(Ok(())) => {}
                    Ok(Err(error)) => failures.push(format!("worker error: {error:?}")),
                    Err(_) => failures.push("worker panicked".to_string()),
                }
            }
            (
                count,
                std::mem::take(&mut *lock(&self.collector.results)),
                failures,
            )
        }
    }

    #[test]
    fn collected_executions_retain_raw_errors_and_panics_and_are_scoped() {
        let cancelled = AsyncRelayCommand::new(|token| {
            token.cancel();
            Err(super::VmxError::Cancelled)
        });
        let registration = Registration::new(cancelled.clone());
        let unrelated = AsyncRelayCommand::new(|_| Ok(()));
        unrelated.execute_async().join().unwrap().unwrap();
        assert!(registration.registered.try_recv().is_err());
        cancelled.clone().execute();
        registration
            .registered
            .recv_timeout(std::time::Duration::from_secs(2))
            .unwrap();
        let (count, raw, failures) = registration.join_all();
        assert_eq!(count, 1);
        assert_eq!(raw, vec![Err(super::VmxError::Cancelled)]);
        assert!(
            failures.is_empty(),
            "normalized fire-and-forget result is Ok"
        );
        drop(registration);
        // Dropping registration removes the command-scoped observer.
        let replacement = Registration::new(cancelled);
        assert_eq!(replacement.join_all().0, 0);

        let panicking = AsyncRelayCommand::new(|_| panic!("action panic for collector test"));
        let registration = Registration::new(panicking.clone());
        panicking.execute();
        registration
            .registered
            .recv_timeout(std::time::Duration::from_secs(2))
            .unwrap();
        let (count, raw, failures) = registration.join_all();
        assert_eq!(count, 1);
        // A fire-and-forget panic becomes an error result (spec/04 §10.4).
        assert_eq!(
            raw,
            vec![Err(super::VmxError::Other(
                "command panicked: action panic for collector test".to_string()
            ))]
        );
        assert!(failures.is_empty(), "the worker no longer panics");
    }

    impl Drop for Registration {
        fn drop(&mut self) {
            *lock(&self.command.test_executions) = None;
            let (_, results, failures) = self.join_all();
            if !failures.is_empty() || results.iter().any(Result::is_err) {
                eprintln!("test command cleanup failures: {failures:?}; raw results: {results:?}");
            }
        }
    }
}

#[cfg(test)]
mod worker_tests {
    use super::{AsyncRelayCommand, AsyncValue, Command, ConfirmationDecoratorCommand};
    use crate::runtime::worker_spawns;
    use std::sync::{mpsc, Mutex};
    use std::time::Duration;

    const CALLS: usize = 100;
    const BOUND: Duration = Duration::from_secs(5);

    fn workers_for_repeated_execute(command: &AsyncRelayCommand) -> usize {
        worker_spawns::counted(|| {
            for _ in 0..CALLS {
                command.execute();
            }
        })
        .1
    }

    #[test]
    fn rejected_fire_and_forget_execution_spawns_no_worker() {
        let missing_action = AsyncRelayCommand::noop();
        let false_predicate = AsyncRelayCommand::new(|_| Ok(())).with_can_execute(|| false);
        let disposed = AsyncRelayCommand::new(|_| Ok(()));
        disposed.dispose();

        assert_eq!(
            workers_for_repeated_execute(&missing_action),
            0,
            "missing action"
        );
        assert_eq!(
            workers_for_repeated_execute(&false_predicate),
            0,
            "false predicate"
        );
        assert_eq!(workers_for_repeated_execute(&disposed), 0, "disposed");
    }

    #[test]
    fn fire_and_forget_execution_while_busy_spawns_no_worker() {
        let (release, released) = mpsc::channel::<()>();
        let released = Mutex::new(released);
        let (started_sender, started) = mpsc::channel();
        let command = AsyncRelayCommand::new(move |_| {
            let _ = started_sender.send(());
            let _ = released.lock().unwrap().recv();
            Ok(())
        });

        let (running, admitted) = worker_spawns::counted(|| command.execute_async());
        started
            .recv_timeout(BOUND)
            .expect("the admitted body started");
        let busy = workers_for_repeated_execute(&command);
        release.send(()).unwrap();
        running.join().unwrap().unwrap();

        assert_eq!((admitted, busy), (1, 0));
        assert!(started.try_recv().is_err(), "a busy call ran the body");
    }

    #[test]
    fn accepted_fire_and_forget_execution_spawns_one_worker() {
        let (finished_sender, finished) = mpsc::channel();
        let command = AsyncRelayCommand::new(move |_| {
            let _ = finished_sender.send(());
            Ok(())
        });

        let ((), workers) = worker_spawns::counted(|| command.execute());
        finished.recv_timeout(BOUND).expect("the body ran");

        assert_eq!(workers, 1);
    }

    #[test]
    fn rejected_internal_awaited_execution_spawns_no_worker() {
        let command = AsyncRelayCommand::noop();

        let (result, workers) = worker_spawns::counted(|| command.execute_and_join());

        assert_eq!(result.unwrap(), Ok(()));
        assert_eq!(workers, 0);
    }

    #[test]
    fn rejected_awaited_execution_still_returns_a_completed_handle() {
        let command = AsyncRelayCommand::noop();

        let (handle, workers) = worker_spawns::counted(|| command.execute_async());

        assert_eq!(handle.join().unwrap(), Ok(()));
        assert_eq!(workers, 1, "JoinHandle can only come from a spawned thread");
    }

    #[test]
    fn rejected_awaitable_entry_point_spawns_no_worker() {
        let command = AsyncRelayCommand::noop();
        let start = command
            .as_async()
            .expect("an async command has an entry point");

        let (completion, workers) = worker_spawns::counted(start);

        assert_eq!(completion.try_get(), Some(Ok(())));
        assert_eq!(workers, 0);
    }

    // Spec §8.3.2: the decorator starts no task of its own to run or watch an
    // asynchronous inner, on either path; only the inner's worker runs.
    #[test]
    fn confirmation_over_an_async_inner_spawns_only_the_inner_worker() {
        let (finished_sender, finished) = mpsc::channel();
        let inner = AsyncRelayCommand::new(move |_| {
            let _ = finished_sender.send(());
            Ok(())
        });
        let decorator = ConfirmationDecoratorCommand::new(inner, || AsyncValue::ready(true));

        let (execution, awaited) = worker_spawns::counted(|| decorator.execute_async());
        execution.join().expect("the awaited execution succeeded");
        finished.recv_timeout(BOUND).expect("the awaited body ran");
        // The awaited execution settles after the inner released admission,
        // so the fire-and-forget call is admitted.
        let ((), fire_and_forget) = worker_spawns::counted(|| decorator.execute());
        finished
            .recv_timeout(BOUND)
            .expect("the fire-and-forget body ran");

        assert_eq!((awaited, fire_and_forget), (1, 1));
    }
}

#[cfg(test)]
mod cancellation_listener_tests {
    use super::CancellationToken;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    type Listener = Arc<dyn Fn() + Send + Sync>;

    fn counting_listener() -> (Arc<AtomicUsize>, Listener) {
        let calls = Arc::new(AtomicUsize::new(0));
        let counted = calls.clone();
        (
            calls,
            Arc::new(move || {
                counted.fetch_add(1, Ordering::SeqCst);
            }),
        )
    }

    #[test]
    fn a_listener_runs_once_when_the_token_is_cancelled() {
        let token = CancellationToken::new();
        let (calls, listener) = counting_listener();
        let _registration = token.on_cancel(listener).expect("registered");

        token.clone().cancel();
        token.cancel();

        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn an_already_cancelled_token_keeps_no_listener() {
        let token = CancellationToken::new();
        token.cancel();
        let (calls, listener) = counting_listener();

        assert!(token.on_cancel(listener.clone()).is_none());

        assert_eq!(Arc::strong_count(&listener), 1);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn dropping_the_registration_removes_the_listener() {
        let token = CancellationToken::new();
        let (calls, listener) = counting_listener();

        drop(token.on_cancel(listener.clone()));
        token.cancel();

        assert_eq!(Arc::strong_count(&listener), 1);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn a_panicking_listener_does_not_stop_the_others() {
        let token = CancellationToken::new();
        let _panicking = token.on_cancel(Arc::new(|| panic!("listener failed")));
        let (calls, listener) = counting_listener();
        let _counting = token.on_cancel(listener);

        token.cancel();

        assert!(token.is_cancelled());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
