//! Create, update, and delete commands bound to a current modeled value.
//!
//! Spec: `spec/09-groups-and-modeled-crud.md`.

use super::*;

/// A coordinated command set for CRUD operations on an optional current value.
///
/// Create is always executable. Update and delete are executable only while a
/// current value exists, and each execution obtains a fresh current snapshot.
pub struct ModeledCrudCommands<VM: Clone + Send + 'static> {
    create_new_command: RelayCommand,
    update_current_command: RelayCommand,
    delete_current_command: RelayCommand,
    _current_changed_subscription: Option<Subscription>,
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
        Self::with_current_changed(current, create_new, update_current, delete_current, None)
    }

    /// Creates CRUD commands and observes a current-value change signal.
    ///
    /// Each signal publishes `can_execute_changed` through both the update and
    /// delete commands so consumers can refresh their enabled state.
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
        let current = Arc::new(current);
        let create_new = Arc::new(create_new);
        let update_current = Arc::new(update_current);
        let delete_current = Arc::new(delete_current);
        Self::build(
            current,
            create_new,
            update_current,
            delete_current,
            None,
            current_changed,
        )
    }

    /// Creates CRUD commands whose delete action requires confirmation.
    ///
    /// A rejected confirmation leaves the current value and delete callback
    /// untouched.
    pub fn with_confirm_delete<C, Create, Update, Delete, Confirm>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
        confirm_delete: Confirm,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
        Confirm: Fn() -> bool + Send + Sync + 'static,
    {
        Self::build(
            Arc::new(current),
            Arc::new(create_new),
            Arc::new(update_current),
            Arc::new(delete_current),
            Some(Arc::new(confirm_delete)),
            None,
        )
    }

    fn build(
        current: Arc<dyn Fn() -> Option<VM> + Send + Sync>,
        create_new: Arc<dyn Fn() + Send + Sync>,
        update_current: Arc<dyn Fn(VM) + Send + Sync>,
        delete_current: Arc<dyn Fn(VM) + Send + Sync>,
        confirm_delete: Option<Arc<dyn Fn() -> bool + Send + Sync>>,
        current_changed: Option<MessageHub>,
    ) -> Self {
        let create_new_command = RelayCommand::new(move || create_new());
        let update_provider = current.clone();
        let update_predicate = current.clone();
        let update_current_command = RelayCommand::new(move || {
            if let Some(current) = update_provider() {
                update_current(current);
            }
        })
        .with_can_execute(move || update_predicate().is_some());
        let delete_provider = current.clone();
        let delete_predicate = current.clone();
        let confirm_delete = confirm_delete.unwrap_or_else(|| Arc::new(|| true));
        let delete_current_command = RelayCommand::new(move || {
            if confirm_delete() {
                if let Some(current) = delete_provider() {
                    delete_current(current);
                }
            }
        })
        .with_can_execute(move || delete_predicate().is_some());
        let subscription = current_changed.map(|trigger| {
            let update_hub = update_current_command.can_execute_changed();
            let delete_hub = delete_current_command.can_execute_changed();
            trigger.subscribe(move |_| {
                update_hub.send(Message::Custom {
                    sender_id: 0,
                    name: "can_execute_changed".to_string(),
                });
                delete_hub.send(Message::Custom {
                    sender_id: 0,
                    name: "can_execute_changed".to_string(),
                });
            })
        });
        Self {
            create_new_command,
            update_current_command,
            delete_current_command,
            _current_changed_subscription: subscription,
            _phantom: std::marker::PhantomData,
        }
    }

    /// Returns the command that creates a new value.
    pub fn create_new_command(&self) -> RelayCommand {
        self.create_new_command.clone()
    }

    /// Returns the command that updates the current value.
    pub fn update_current_command(&self) -> RelayCommand {
        self.update_current_command.clone()
    }

    /// Returns the command that deletes the current value.
    pub fn delete_current_command(&self) -> RelayCommand {
        self.delete_current_command.clone()
    }
}
