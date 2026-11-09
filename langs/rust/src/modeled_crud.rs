//! Create, update, and delete commands bound to a current modeled value.
//!
//! Spec: `spec/06-composite-vm.md` §Modeled CRUD commands; ADR-0016, ADR-0210.

use super::{
    Arc, AsyncValue, Command, ConfirmationDecoratorCommand, Message, MessageHub, RelayCommand,
    Subscription,
};

/// An absent confirmation gate for [`ModeledCrudCommands::with_options`],
/// usable where `None` would need a type annotation.
pub const NO_CONFIRM: Option<fn() -> AsyncValue<bool>> = None;

/// A coordinated command set for CRUD operations on an optional current value.
///
/// Create is always executable. Update and delete are executable only while a
/// current value exists, and each execution obtains a fresh current snapshot.
///
/// The update and delete commands are returned as `Arc<dyn Command>`. A
/// command built with a confirmation gate is a [`ConfirmationDecoratorCommand`]
/// around the plain [`RelayCommand`]; a command built without one is the plain
/// relay (spec `06-composite-vm.md` §7, ADR-0210).
///
/// `Command` has no downcast, so the concrete gated commands are also
/// returned by [`update_confirmation`](Self::update_confirmation) and
/// [`delete_confirmation`](Self::delete_confirmation), which reach their
/// error streams and `execute_async`. [`dispose`](Self::dispose) disposes
/// every command the helper built, as the helper's `Dispose` does in the
/// other flavors.
pub struct ModeledCrudCommands<VM: Clone + Send + 'static> {
    create_new_command: RelayCommand,
    update_relay: RelayCommand,
    delete_relay: RelayCommand,
    update_confirmation: Option<ConfirmationDecoratorCommand<RelayCommand>>,
    delete_confirmation: Option<ConfirmationDecoratorCommand<RelayCommand>>,
    update_current_command: Arc<dyn Command>,
    delete_current_command: Arc<dyn Command>,
    current_changed_subscription: Option<Subscription>,
    _phantom: std::marker::PhantomData<VM>,
}

impl<VM: Clone + Send + 'static> ModeledCrudCommands<VM> {
    /// Creates CRUD commands over the supplied current-value provider.
    pub fn new<C, Create, Update, Delete>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
    {
        Self::with_options(
            current,
            create_new,
            update_current,
            delete_current,
            NO_CONFIRM,
            NO_CONFIRM,
            None,
        )
    }

    /// Creates CRUD commands and observes a current-value change signal.
    ///
    /// Each signal publishes `can_execute_changed` through both the update and
    /// delete commands so consumers can refresh their enabled state. Use
    /// [`with_options`](Self::with_options) to add confirmation gates too.
    pub fn with_current_changed<C, Create, Update, Delete>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
        current_changed: Option<MessageHub>,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
    {
        Self::with_options(
            current,
            create_new,
            update_current,
            delete_current,
            NO_CONFIRM,
            NO_CONFIRM,
            current_changed,
        )
    }

    /// Creates CRUD commands with optional confirmation gates and an optional
    /// current-value change signal.
    ///
    /// A supplied `confirm_update` or `confirm_delete` gate wraps that command
    /// in a [`ConfirmationDecoratorCommand`]: execution resolves the gate
    /// first, and only a `true` result runs the action with a fresh current
    /// value. A `false` result leaves the action uncalled. Pass
    /// [`NO_CONFIRM`] for an absent gate.
    ///
    /// Each `current_changed` message publishes `can_execute_changed` through
    /// the update and delete commands, also when they are gated, so consumers
    /// can refresh their enabled state (spec `06-composite-vm.md` §7,
    /// ADR-0049, ADR-0210).
    ///
    /// ```
    /// use std::sync::{Arc, Mutex};
    /// use vmx::{AsyncValue, Command, ModeledCrudCommands, NO_CONFIRM};
    ///
    /// let deleted = Arc::new(Mutex::new(Vec::new()));
    /// let crud = ModeledCrudCommands::with_options(
    ///     || Some(7),
    ///     || {},
    ///     |_| {},
    ///     {
    ///         let deleted = deleted.clone();
    ///         move |item| deleted.lock().unwrap().push(item)
    ///     },
    ///     NO_CONFIRM,
    ///     Some(|| AsyncValue::ready(true)),
    ///     None,
    /// );
    ///
    /// // Await the gated execution through the awaitable entry point.
    /// let start = crud.delete_current_command().as_async().expect("gated");
    /// start().wait().unwrap();
    /// assert_eq!(*deleted.lock().unwrap(), vec![7]);
    /// ```
    pub fn with_options<C, Create, Update, Delete, ConfirmUpdate, ConfirmDelete>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
        confirm_update: Option<ConfirmUpdate>,
        confirm_delete: Option<ConfirmDelete>,
        current_changed: Option<MessageHub>,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
        ConfirmUpdate: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
        ConfirmDelete: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        let current: Arc<dyn Fn() -> Option<VM> + Send + Sync> = Arc::new(current);
        let create_new_command = RelayCommand::new_shared(create_new);
        let update = Self::current_command(current.clone(), update_current);
        let delete = Self::current_command(current, delete_current);
        let subscription = current_changed.map(|trigger| {
            let update_hub = update.can_execute_changed();
            let delete_hub = delete.can_execute_changed();
            trigger.subscribe(move |_| {
                update_hub.send(can_execute_changed_message());
                delete_hub.send(can_execute_changed_message());
            })
        });
        let update_confirmation = confirm_update
            .map(|confirm| ConfirmationDecoratorCommand::new(update.clone(), confirm));
        let delete_confirmation = confirm_delete
            .map(|confirm| ConfirmationDecoratorCommand::new(delete.clone(), confirm));
        Self {
            create_new_command,
            update_current_command: public_command(&update, &update_confirmation),
            delete_current_command: public_command(&delete, &delete_confirmation),
            update_relay: update,
            delete_relay: delete,
            update_confirmation,
            delete_confirmation,
            current_changed_subscription: subscription,
            _phantom: std::marker::PhantomData,
        }
    }

    /// Builds a command that runs `action` with a fresh current value and is
    /// executable only while one exists.
    fn current_command<A>(
        current: Arc<dyn Fn() -> Option<VM> + Send + Sync>,
        action: A,
    ) -> RelayCommand
    where
        A: Fn(VM) + Send + Sync + 'static,
    {
        let predicate = current.clone();
        RelayCommand::new_shared(move || {
            if let Some(current) = current() {
                action(current);
            }
        })
        .with_can_execute(move || predicate().is_some())
    }

    /// Returns the command that creates a new value.
    pub fn create_new_command(&self) -> RelayCommand {
        self.create_new_command.clone()
    }

    /// Returns the command that updates the current value.
    ///
    /// With a `confirm_update` gate it is a [`ConfirmationDecoratorCommand`],
    /// whose [`Command::as_async`] entry point awaits the gate and the action.
    pub fn update_current_command(&self) -> Arc<dyn Command> {
        self.update_current_command.clone()
    }

    /// Returns the command that deletes the current value.
    ///
    /// With a `confirm_delete` gate it is a [`ConfirmationDecoratorCommand`],
    /// whose [`Command::as_async`] entry point awaits the gate and the action.
    pub fn delete_current_command(&self) -> Arc<dyn Command> {
        self.delete_current_command.clone()
    }

    /// Returns the gated update command, or `None` without a `confirm_update`
    /// gate.
    ///
    /// It is the same command that
    /// [`update_current_command`](Self::update_current_command) returns, with
    /// its concrete type. Use it to observe the
    /// [`error_stream`](ConfirmationDecoratorCommand::error_stream), where a
    /// fire-and-forget `execute()` reports a panicking gate or action, or to
    /// call [`execute_async`](ConfirmationDecoratorCommand::execute_async).
    pub fn update_confirmation(&self) -> Option<ConfirmationDecoratorCommand<RelayCommand>> {
        self.update_confirmation.clone()
    }

    /// Returns the gated delete command, or `None` without a `confirm_delete`
    /// gate.
    ///
    /// It is the same command that
    /// [`delete_current_command`](Self::delete_current_command) returns, with
    /// its concrete type. Use it to observe the
    /// [`error_stream`](ConfirmationDecoratorCommand::error_stream), where a
    /// fire-and-forget `execute()` reports a panicking gate or action, or to
    /// call [`execute_async`](ConfirmationDecoratorCommand::execute_async).
    ///
    /// ```
    /// use std::{sync::mpsc, time::Duration};
    /// use vmx::{AsyncValue, Command, ModeledCrudCommands, NO_CONFIRM, VmxError};
    ///
    /// let crud = ModeledCrudCommands::with_options(
    ///     || Some(7),
    ///     || {},
    ///     |_: i32| {},
    ///     |_| panic!("delete failed"),
    ///     NO_CONFIRM,
    ///     Some(|| AsyncValue::ready(true)),
    ///     None,
    /// );
    /// assert!(crud.update_confirmation().is_none());
    ///
    /// let (sender, failures) = mpsc::channel();
    /// let sender = std::sync::Mutex::new(sender);
    /// let _failures = crud
    ///     .delete_confirmation()
    ///     .expect("delete is gated")
    ///     .error_stream()
    ///     .subscribe(move |error| sender.lock().unwrap().send(error).unwrap());
    ///
    /// // A fire-and-forget execution reports the panicking action here.
    /// crud.delete_current_command().execute();
    /// assert_eq!(
    ///     failures.recv_timeout(Duration::from_secs(5)).unwrap(),
    ///     VmxError::Other("command panicked: delete failed".into())
    /// );
    ///
    /// // Disposal makes every command inert.
    /// crud.dispose();
    /// assert!(!crud.delete_current_command().can_execute());
    /// ```
    pub fn delete_confirmation(&self) -> Option<ConfirmationDecoratorCommand<RelayCommand>> {
        self.delete_confirmation.clone()
    }

    /// Disposes the commands this helper built. Idempotent.
    ///
    /// It detaches the `current_changed` trigger, disposes any confirmation
    /// decorators, which completes their error streams, and disposes the
    /// create, update and delete relays, which makes them inert. This matches
    /// the helper's `Dispose` in the other flavors (ADR-0210).
    pub fn dispose(&self) {
        if let Some(subscription) = &self.current_changed_subscription {
            subscription.dispose();
        }
        for confirmation in [&self.update_confirmation, &self.delete_confirmation]
            .into_iter()
            .flatten()
        {
            confirmation.dispose();
        }
        for relay in [
            &self.create_new_command,
            &self.update_relay,
            &self.delete_relay,
        ] {
            relay.dispose();
        }
    }
}

/// Returns the gated command when one exists, else the plain relay.
fn public_command(
    relay: &RelayCommand,
    confirmation: &Option<ConfirmationDecoratorCommand<RelayCommand>>,
) -> Arc<dyn Command> {
    match confirmation {
        Some(confirmation) => Arc::new(confirmation.clone()),
        None => Arc::new(relay.clone()),
    }
}

fn can_execute_changed_message() -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "ModeledCrudCommands".to_string(),
        name: "can_execute_changed".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::{ModeledCrudCommands, NO_CONFIRM};
    use crate::{AsyncValue, Command, Message, MessageHub};
    use std::sync::{Arc, Mutex};

    // ADR-0210: a `confirm_update` gate runs the update action only after a
    // `true` answer, and each awaited execution completes after the answer.
    #[test]
    fn update_gate_runs_the_update_only_when_confirmed() {
        let updated = Arc::new(Mutex::new(Vec::new()));
        let decisions = Arc::new(Mutex::new(Vec::new()));
        let crud = {
            let updated = updated.clone();
            let decisions = decisions.clone();
            ModeledCrudCommands::with_options(
                || Some(5),
                || {},
                move |item| updated.lock().unwrap().push(item),
                |_| {},
                Some(move || {
                    let decision = AsyncValue::pending();
                    decisions.lock().unwrap().push(decision.clone());
                    decision
                }),
                NO_CONFIRM,
                None,
            )
        };
        let update = crud.update_current_command();

        for (answer, expected) in [(false, vec![]), (true, vec![5])] {
            let execution = update.as_async().expect("a gated command is awaitable")();
            assert_eq!(execution.try_get(), None, "the gate is still pending");
            assert!(
                updated.lock().unwrap().is_empty(),
                "nothing ran before the answer"
            );
            let decision = decisions.lock().unwrap().pop().expect("the gate ran");
            decision.resolve(answer);
            execution.wait().expect("the execution completed");
            assert_eq!(*updated.lock().unwrap(), expected, "answer = {answer}");
        }
    }

    // ADR-0210: `dispose` detaches the trigger, completes the gated
    // command's error stream, and makes every command inert, gated or not.
    #[test]
    fn dispose_releases_every_command_the_helper_built() {
        let trigger = MessageHub::new();
        let crud = ModeledCrudCommands::with_options(
            || Some(1),
            || {},
            |_| {},
            |_| {},
            NO_CONFIRM,
            Some(|| AsyncValue::ready(true)),
            Some(trigger.clone()),
        );
        let update_changes = crud
            .update_current_command()
            .can_execute_changed()
            .record(16);
        let completed = Arc::new(Mutex::new(0));
        let _errors = {
            let completed = completed.clone();
            crud.delete_confirmation()
                .expect("delete is gated")
                .error_stream()
                .subscribe_with_completion(|_| {}, move || *completed.lock().unwrap() += 1)
        };

        crud.dispose();
        crud.dispose();

        assert_eq!(
            *completed.lock().unwrap(),
            1,
            "the error stream completed once"
        );
        assert!(!crud.create_new_command().can_execute());
        assert!(!crud.update_current_command().can_execute());
        assert!(!crud.delete_current_command().can_execute());
        // The relay's own disposal announces a final eligibility change.
        let after_dispose = update_changes.messages().len();
        trigger.send(Message::Custom {
            sender_id: 0,
            sender_name: "selection".to_string(),
            name: "current_changed".to_string(),
        });
        assert_eq!(
            update_changes.messages().len(),
            after_dispose,
            "the trigger is detached"
        );
    }

    // ADR-0049, ADR-0210: the trigger reaches gated commands too.
    #[test]
    fn trigger_refreshes_both_gated_commands() {
        let trigger = MessageHub::new();
        let crud = ModeledCrudCommands::with_options(
            || Some(1),
            || {},
            |_| {},
            |_| {},
            Some(|| AsyncValue::ready(true)),
            Some(|| AsyncValue::ready(true)),
            Some(trigger.clone()),
        );
        let update_changes = crud
            .update_current_command()
            .can_execute_changed()
            .record(16);
        let delete_changes = crud
            .delete_current_command()
            .can_execute_changed()
            .record(16);
        let changed = |recorder: &crate::MessageRecorder| {
            recorder
                .messages()
                .into_iter()
                .filter(|message| {
                    matches!(message, Message::Custom { name, .. } if name == "can_execute_changed")
                })
                .count()
        };

        for sent in 1..=2 {
            trigger.send(Message::Custom {
                sender_id: 0,
                sender_name: "selection".to_string(),
                name: "current_changed".to_string(),
            });
            assert_eq!(changed(&update_changes), sent);
            assert_eq!(changed(&delete_changes), sent);
        }
    }
}
