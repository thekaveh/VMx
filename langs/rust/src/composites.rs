//! Selectable composite view models, filtered projections, and builders.
//!
//! Spec: `spec/06-composite-vm.md`.

use super::{
    begin_membership_transaction, begin_parent_transfer, finish_with_first_error, lock,
    retain_first_error, Arc, AtomicBool, ComponentCore, ConstructionStatus, Dispatcher, HashSet,
    LifecycleOperation, MembershipDisposeDisposition, MembershipTransactionControl,
    MembershipTransactionGuard, MessageHub, Mutex, NullDispatcher, ObservableList, Ordering,
    ParentHandle, ParentRegistration, ParentTransfer, PropertyChangedStream, TreeNode, VmNode,
    VmxError, VmxResult,
};

type CurrentChangedCallback<T> = Arc<dyn Fn(Option<T>) + Send + Sync>;
type CurrentSelector<T> = Arc<dyn Fn(Vec<T>) -> Option<T> + Send + Sync>;

struct CurrentAssignmentContext<'a, T: VmNode, D: Dispatcher> {
    core: &'a ComponentCore<D>,
    items: &'a ObservableList<T>,
    current: &'a Arc<Mutex<Option<T>>>,
    async_selection: &'a Arc<Mutex<bool>>,
    on_current_changed: &'a Arc<Mutex<Option<CurrentChangedCallback<T>>>>,
    membership_gate: &'a Arc<Mutex<()>>,
    membership_transaction_active: &'a Arc<AtomicBool>,
    membership_transaction_control: &'a Arc<MembershipTransactionControl>,
}

fn same_node<T: VmNode>(left: &T, right: &T) -> bool {
    left.id() == right.id()
}

fn same_optional_node<T: VmNode>(left: Option<&T>, right: Option<&T>) -> bool {
    match (left, right) {
        (Some(left), Some(right)) => same_node(left, right),
        (None, None) => true,
        _ => false,
    }
}

fn assign_current_state<T: VmNode, D: Dispatcher>(
    core: &ComponentCore<D>,
    current: &Arc<Mutex<Option<T>>>,
    on_current_changed: &Arc<Mutex<Option<CurrentChangedCallback<T>>>>,
    next: Option<T>,
) {
    let previous = {
        let mut current = lock(current);
        if same_optional_node(current.as_ref(), next.as_ref()) {
            return;
        }
        let previous = current.clone();
        *current = next.clone();
        previous
    };
    if let Some(previous) = previous {
        previous.set_current_flag(false);
    }
    if let Some(next_current) = next.clone() {
        next_current.set_current_flag(true);
    }
    core.notify_property_changed("current");
    if let Some(callback) = lock(on_current_changed).clone() {
        callback(next);
    }
}

fn assign_current_maybe_async<T: VmNode, D: Dispatcher>(
    context: CurrentAssignmentContext<'_, T, D>,
    next: Option<T>,
    require_constructed: bool,
    expected_current_id: Option<usize>,
) -> VmxResult<()> {
    let CurrentAssignmentContext {
        core,
        items,
        current,
        async_selection,
        on_current_changed,
        membership_gate,
        membership_transaction_active,
        membership_transaction_control,
    } = context;
    let validate = |next: Option<&T>| {
        next.is_none_or(|next| {
            items.to_vec().iter().any(|item| item.id() == next.id())
                && (!require_constructed || next.status() == ConstructionStatus::Constructed)
        })
    };
    if *lock(async_selection) {
        let transaction = begin_membership_transaction(
            membership_transaction_active,
            membership_transaction_control,
        )?;
        let valid = {
            let _gate = lock(membership_gate);
            validate(next.as_ref())
                && expected_current_id.is_none_or(|expected| {
                    lock(current)
                        .as_ref()
                        .is_some_and(|current| current.id() == expected)
                })
        };
        drop(transaction);
        if !valid {
            return Err(if expected_current_id.is_some() {
                VmxError::NotCurrent
            } else {
                VmxError::NonChild
            });
        }
        let core_for_action = core.clone();
        let items = items.clone();
        let current = Arc::clone(current);
        let on_current_changed = Arc::clone(on_current_changed);
        let membership_gate = Arc::clone(membership_gate);
        let membership_transaction_active = Arc::clone(membership_transaction_active);
        let membership_transaction_control = Arc::clone(membership_transaction_control);
        core.dispatch(Box::new(move || {
            let Ok(transaction) = begin_membership_transaction(
                &membership_transaction_active,
                &membership_transaction_control,
            ) else {
                return;
            };
            let valid = {
                let _gate = lock(&membership_gate);
                next.as_ref().is_none_or(|next| {
                    items.to_vec().iter().any(|item| item.id() == next.id())
                        && (!require_constructed
                            || next.status() == ConstructionStatus::Constructed)
                }) && expected_current_id.is_none_or(|expected| {
                    lock(&current)
                        .as_ref()
                        .is_some_and(|current| current.id() == expected)
                })
            };
            if valid {
                assign_current_state(&core_for_action, &current, &on_current_changed, next);
            }
            let _ = transaction.finish();
        }));
    } else {
        let transaction = begin_membership_transaction(
            membership_transaction_active,
            membership_transaction_control,
        )?;
        let valid = {
            let _gate = lock(membership_gate);
            validate(next.as_ref())
                && expected_current_id.is_none_or(|expected| {
                    lock(current)
                        .as_ref()
                        .is_some_and(|current| current.id() == expected)
                })
        };
        if !valid {
            return Err(if expected_current_id.is_some() {
                VmxError::NotCurrent
            } else {
                VmxError::NonChild
            });
        }
        assign_current_state(core, current, on_current_changed, next);
        return transaction.finish();
    }
    Ok(())
}

/// Shared ordered, observable child-collection capability without selection.
pub trait VmCollection<T: VmNode> {
    /// Returns an ordered snapshot of all children.
    fn items(&self) -> Vec<T>;
    /// Returns the child at `index`, if present.
    fn get(&self, index: usize) -> Option<T>;
    /// Returns the number of children.
    fn len(&self) -> usize;
    /// Reports whether the collection has no children.
    fn is_empty(&self) -> bool;
    /// Appends a child and establishes ownership.
    fn add(&self, item: T) -> VmxResult<()>;
    /// Inserts a child at `index` and establishes ownership.
    fn insert(&self, index: usize, item: T) -> VmxResult<()>;
    /// Removes a child by node identity.
    fn remove(&self, item: &T) -> VmxResult<()>;
    /// Removes and returns the child at `index`.
    fn remove_at(&self, index: usize) -> VmxResult<T>;
    /// Replaces and returns the child at `index`.
    fn replace(&self, index: usize, item: T) -> VmxResult<T>;
    /// Removes all children.
    fn clear(&self);
    /// Moves a child between valid indices.
    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()>;
    /// Coalesces notifications produced by `action`.
    fn batch_update<F>(&self, action: F)
    where
        F: FnOnce();
}

/// VM collection that additionally owns a current-child selection slot.
pub trait SelectableVmCollection<T: VmNode>: VmCollection<T> {
    /// Returns the current child, if one is selected.
    fn current(&self) -> Option<T>;
    /// Assigns a current child or clears selection.
    fn set_current(&self, item: Option<T>) -> VmxResult<()>;
    /// Selects a constructed child.
    fn select_component(&self, item: &T) -> VmxResult<()>;
    /// Deselects the current child.
    fn deselect_component(&self, item: &T) -> VmxResult<()>;
    /// Reports whether `item` is a selectable constructed child.
    fn can_select_component(&self, item: &T) -> bool;
}

#[derive(Clone)]
/// A lifecycle-aware, parent-owning child collection with current selection.
///
/// Membership transfers are atomic, selection is restricted to constructed
/// children, and lifecycle transitions propagate through the child snapshot.
pub struct CompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
    ownership: ParentRegistration,
    current: Arc<Mutex<Option<T>>>,
    auto_construct_on_add: Arc<Mutex<bool>>,
    async_selection: Arc<Mutex<bool>>,
    current_selector: Arc<Mutex<Option<CurrentSelector<T>>>>,
    on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>>,
    dispose_requested: Arc<AtomicBool>,
    membership_gate: Arc<Mutex<()>>,
    membership_transaction_active: Arc<AtomicBool>,
    membership_transaction_control: Arc<MembershipTransactionControl>,
}

impl<T: VmNode> CompositeVm<T, NullDispatcher> {
    /// Creates an empty composite with null services.
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<T: VmNode, D: Dispatcher> CompositeVm<T, D> {
    /// Creates an empty composite with explicit services.
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        let core = ComponentCore::new(name, hub.clone(), dispatcher);
        let items: ObservableList<T> = ObservableList::new(core.id(), hub);
        let current = Arc::new(Mutex::new(None));
        let async_selection = Arc::new(Mutex::new(false));
        let current_selector = Arc::new(Mutex::new(None));
        let on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>> =
            Arc::new(Mutex::new(None));
        let dispose_requested = Arc::new(AtomicBool::new(false));
        let membership_gate = Arc::new(Mutex::new(()));
        let membership_transaction_active = Arc::new(AtomicBool::new(false));
        let membership_transaction_control = Arc::new(MembershipTransactionControl::new());
        let ownership = ParentRegistration::new_selectable(
            core.id(),
            {
                let core = core.clone();
                move || core.parent_handle()
            },
            {
                let items = items.clone();
                move |child_id| items.to_vec().iter().any(|item| item.id() == child_id)
            },
            {
                let core = core.clone();
                let items = items.clone();
                let current = Arc::clone(&current);
                let on_current_changed = Arc::clone(&on_current_changed);
                let detach_gate = Arc::clone(&membership_gate);
                let detach_disposed = Arc::clone(&dispose_requested);
                let detach_transaction = Arc::clone(&membership_transaction_active);
                let detach_control = Arc::clone(&membership_transaction_control);
                move |child_id, owner_handle| {
                    let transaction =
                        begin_membership_transaction(&detach_transaction, &detach_control)?;
                    let _gate = lock(&detach_gate);
                    if detach_disposed.load(Ordering::Acquire)
                        || detach_control.has_deferred_dispose()
                    {
                        return Err(VmxError::Disposed);
                    }
                    let index = items
                        .to_vec()
                        .iter()
                        .position(|item| item.id() == child_id)
                        .ok_or(VmxError::InconsistentParent)?;
                    let removed = items
                        .remove_at_silent(index)
                        .ok_or(VmxError::InconsistentParent)?;
                    let was_current = lock(&current)
                        .as_ref()
                        .is_some_and(|item: &T| item.id() == child_id);
                    let commit_items = items.clone();
                    let commit_current = Arc::clone(&current);
                    let commit_callback = Arc::clone(&on_current_changed);
                    let commit_core = core.clone();
                    let commit_removed = removed.clone();
                    let rollback_items = items.clone();
                    let rollback_gate = Arc::clone(&detach_gate);
                    let rollback_disposed = Arc::clone(&detach_disposed);
                    let commit_transaction = Arc::clone(&detach_transaction);
                    let rollback_transaction = Arc::clone(&detach_transaction);
                    let commit_control = Arc::clone(&detach_control);
                    let rollback_control = Arc::clone(&detach_control);
                    transaction.defer();
                    Ok(ParentTransfer::new(
                        move || {
                            let transaction = MembershipTransactionGuard::release_on_drop(
                                commit_transaction,
                                commit_control,
                            );
                            if was_current {
                                *lock(&commit_current) = None;
                                commit_removed.set_current_flag(false);
                                commit_core.notify_property_changed("current");
                                if let Some(callback) = lock(&commit_callback).clone() {
                                    callback(None);
                                }
                            }
                            commit_items.publish_remove(index);
                            transaction.finish()
                        },
                        move || {
                            let transaction = MembershipTransactionGuard::release_on_drop(
                                rollback_transaction,
                                rollback_control,
                            );
                            let _gate = lock(&rollback_gate);
                            if rollback_disposed.load(Ordering::Acquire) {
                                removed.set_parent_handle(None);
                                drop(_gate);
                                let _ = transaction.finish();
                                return Ok(());
                            }
                            let _ = rollback_items
                                .insert_silent(index.min(rollback_items.len()), removed.clone());
                            removed.set_parent_handle(Some(owner_handle));
                            drop(_gate);
                            let _ = transaction.finish();
                            Ok(())
                        },
                    ))
                }
            },
            {
                let current = Arc::clone(&current);
                move |child_id| {
                    lock(&current)
                        .as_ref()
                        .is_some_and(|item: &T| item.id() == child_id)
                }
            },
            {
                let core = core.clone();
                let items = items.clone();
                let current = Arc::clone(&current);
                let async_selection = Arc::clone(&async_selection);
                let on_current_changed = Arc::clone(&on_current_changed);
                let selection_gate = Arc::clone(&membership_gate);
                let selection_transaction = Arc::clone(&membership_transaction_active);
                let selection_control = Arc::clone(&membership_transaction_control);
                move |child_id| {
                    let item = items
                        .to_vec()
                        .into_iter()
                        .find(|item| item.id() == child_id)
                        .filter(|item| item.status() == ConstructionStatus::Constructed)
                        .ok_or(VmxError::NonChild)?;
                    assign_current_maybe_async(
                        CurrentAssignmentContext {
                            core: &core,
                            items: &items,
                            current: &current,
                            async_selection: &async_selection,
                            on_current_changed: &on_current_changed,
                            membership_gate: &selection_gate,
                            membership_transaction_active: &selection_transaction,
                            membership_transaction_control: &selection_control,
                        },
                        Some(item),
                        true,
                        None,
                    )
                }
            },
            {
                let core = core.clone();
                let current = Arc::clone(&current);
                let async_selection = Arc::clone(&async_selection);
                let on_current_changed = Arc::clone(&on_current_changed);
                let selection_items = items.clone();
                let selection_gate = Arc::clone(&membership_gate);
                let selection_transaction = Arc::clone(&membership_transaction_active);
                let selection_control = Arc::clone(&membership_transaction_control);
                move |child_id| {
                    assign_current_maybe_async(
                        CurrentAssignmentContext {
                            core: &core,
                            items: &selection_items,
                            current: &current,
                            async_selection: &async_selection,
                            on_current_changed: &on_current_changed,
                            membership_gate: &selection_gate,
                            membership_transaction_active: &selection_transaction,
                            membership_transaction_control: &selection_control,
                        },
                        None,
                        false,
                        Some(child_id),
                    )
                }
            },
        );
        Self {
            core,
            items,
            ownership,
            current,
            auto_construct_on_add: Arc::new(Mutex::new(false)),
            async_selection,
            current_selector,
            on_current_changed,
            dispose_requested,
            membership_gate,
            membership_transaction_active,
            membership_transaction_control,
        }
    }

    /// Returns the stable composite identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns the immutable composite name.
    pub fn name(&self) -> String {
        self.core.name()
    }

    /// Returns the immutable presentation hint.
    pub fn hint(&self) -> Option<String> {
        self.core.hint()
    }

    /// Returns the local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the injected message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers cleanup work that runs on disposal.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.core.own(cleanup);
    }

    /// Publishes a change for an application-defined property.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Returns an ordered child snapshot.
    pub fn items(&self) -> Vec<T> {
        self.items.to_vec()
    }

    /// Returns the child at `index`, if present.
    pub fn get(&self, index: usize) -> Option<T> {
        self.items.get(index)
    }

    /// Returns the number of children.
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Reports whether the composite has no children.
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// Appends a child, atomically transferring it from any previous parent.
    pub fn add(&self, item: T) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let index = {
            let _gate = lock(&self.membership_gate);
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                if let Some(transfer) = transfer {
                    let _ = transfer.rollback();
                }
                return Err(VmxError::Disposed);
            }
            let index = self.len();
            item.set_parent_handle(Some(self.ownership.handle()));
            self.items.insert_silent(index, item.clone())?;
            index
        };
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        let admission = (if should_construct {
            item.construct()
        } else {
            Ok(())
        })
        .and_then(|()| {
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                Err(VmxError::Disposed)
            } else {
                Ok(())
            }
        });
        if let Err(error) = admission {
            let _gate = lock(&self.membership_gate);
            if let Some(index) = self
                .items()
                .iter()
                .position(|child| child.id() == item.id())
            {
                let _ = self.items.remove_at_silent(index);
            }
            if item
                .parent_handle()
                .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
            {
                item.set_parent_handle(None);
            }
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            return Err(error);
        }
        let mut commit_error = transfer.and_then(|transfer| transfer.commit().err());
        self.items.publish_add(index);
        retain_first_error(&mut commit_error, transaction.finish());
        finish_with_first_error(commit_error)
    }

    fn attach_population(
        &self,
        candidates: Vec<T>,
        construct: bool,
        on_committed: impl FnOnce(),
    ) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let mut identities = HashSet::with_capacity(candidates.len());
        if !candidates.iter().all(|child| identities.insert(child.id())) {
            return Err(VmxError::DuplicateChild);
        }
        let mut transfers = Vec::with_capacity(candidates.len());
        let mut original_statuses = Vec::with_capacity(candidates.len());
        let result = (|| {
            for child in &candidates {
                let transfer = begin_parent_transfer(child, &self.ownership.handle())?;
                transfers.push(transfer);
                original_statuses.push(child.status());
            }
            {
                let _gate = lock(&self.membership_gate);
                if self.disposal_pending() {
                    return Err(VmxError::Disposed);
                }
                for child in &candidates {
                    child.set_parent_handle(Some(self.ownership.handle()));
                    self.items.insert_silent(self.len(), child.clone())?;
                }
            }
            // Make the entire snapshot visible before any child hook runs.
            if construct {
                for child in &candidates {
                    if child.status() != ConstructionStatus::Constructed {
                        child.construct()?;
                    }
                }
            }
            Ok(())
        })();
        if let Err(error) = result {
            let mut compensation_error = None;
            let _gate = lock(&self.membership_gate);
            for child in candidates.iter().rev() {
                if let Some(index) = self.items().iter().position(|item| item.id() == child.id()) {
                    let _ = self.items.remove_at_silent(index);
                }
            }
            drop(_gate);
            for (child, original_status) in candidates
                .iter()
                .zip(&original_statuses)
                .take(transfers.len())
                .rev()
            {
                if *original_status == ConstructionStatus::Destructed
                    && child.status() == ConstructionStatus::Constructed
                {
                    if let Err(error) = child.destruct() {
                        compensation_error.get_or_insert(error);
                    }
                }
                if child
                    .parent_handle()
                    .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
                {
                    child.set_parent_handle(None);
                }
            }
            for transfer in transfers.into_iter().rev().flatten() {
                let _ = transfer.rollback();
            }
            return Err(compensation_error.unwrap_or(error));
        }

        let mut commit_error = None;
        for transfer in transfers.into_iter().flatten() {
            retain_first_error(&mut commit_error, transfer.commit());
        }
        on_committed();
        for child in &candidates {
            if let Some(index) = self
                .items
                .to_vec()
                .iter()
                .position(|candidate| candidate.id() == child.id())
            {
                self.items.publish_add(index);
            }
        }
        retain_first_error(&mut commit_error, transaction.finish());
        finish_with_first_error(commit_error)
    }

    /// Inserts a child at `index` with atomic ownership transfer.
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        {
            let _gate = lock(&self.membership_gate);
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                if let Some(transfer) = transfer {
                    let _ = transfer.rollback();
                }
                return Err(VmxError::Disposed);
            }
            if index > self.len() {
                if let Some(transfer) = transfer {
                    let _ = transfer.rollback();
                }
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            item.set_parent_handle(Some(self.ownership.handle()));
            self.items.insert_silent(index, item.clone())?;
        }
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        let admission = (if should_construct {
            item.construct()
        } else {
            Ok(())
        })
        .and_then(|()| {
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                Err(VmxError::Disposed)
            } else {
                Ok(())
            }
        });
        if let Err(error) = admission {
            let _gate = lock(&self.membership_gate);
            if let Some(position) = self
                .items()
                .iter()
                .position(|child| child.id() == item.id())
            {
                let _ = self.items.remove_at_silent(position);
            }
            if item
                .parent_handle()
                .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
            {
                item.set_parent_handle(None);
            }
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            return Err(error);
        }
        let mut commit_error = transfer.and_then(|transfer| transfer.commit().err());
        self.items.publish_add(index);
        retain_first_error(&mut commit_error, transaction.finish());
        finish_with_first_error(commit_error)
    }

    /// Removes a child, clearing ownership and current selection if needed.
    pub fn remove(&self, item: &T) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let (index, removed) = {
            let _gate = lock(&self.membership_gate);
            let index = self
                .items()
                .iter()
                .position(|candidate| same_node(candidate, item))
                .ok_or(VmxError::NonChild)?;
            let removed = self.items.remove_at_silent(index).expect("index checked");
            (index, removed)
        };
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        if lock(&self.current)
            .as_ref()
            .is_some_and(|current| same_node(current, &removed))
        {
            self.assign_current(None);
        }
        self.items.publish_remove(index);
        transaction.finish()
    }

    /// Removes and returns the child at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let removed = {
            let _gate = lock(&self.membership_gate);
            self.items
                .remove_at_silent(index)
                .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?
        };
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        if lock(&self.current)
            .as_ref()
            .is_some_and(|current| same_node(current, &removed))
        {
            self.assign_current(None);
        }
        self.items.publish_remove(index);
        transaction.finish()?;
        Ok(removed)
    }

    /// Replaces and returns a child using atomic ownership transfer.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let old = {
            let _gate = lock(&self.membership_gate);
            if self.disposal_pending() {
                if let Some(transfer) = transfer {
                    let _ = transfer.rollback();
                }
                return Err(VmxError::Disposed);
            }
            item.set_parent_handle(Some(self.ownership.handle()));
            match self.items.replace_silent(index, item.clone()) {
                Ok(old) => old,
                Err(error) => {
                    item.set_parent_handle(None);
                    drop(_gate);
                    if let Some(transfer) = transfer {
                        let _ = transfer.rollback();
                    }
                    return Err(error);
                }
            }
        };
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        let admission = (if should_construct {
            item.construct()
        } else {
            Ok(())
        })
        .and_then(|()| {
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                Err(VmxError::Disposed)
            } else {
                Ok(())
            }
        });
        if let Err(error) = admission {
            let _gate = lock(&self.membership_gate);
            if !self.disposal_pending() {
                if let Some(attached) = self
                    .items()
                    .iter()
                    .position(|candidate| candidate.id() == item.id())
                {
                    let _ = self.items.replace_silent(attached, old.clone());
                    old.set_parent_handle(Some(self.ownership.handle()));
                    item.set_parent_handle(None);
                }
            }
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            return Err(error);
        }
        let mut commit_error = transfer.and_then(|transfer| transfer.commit().err());
        old.set_parent_handle(None);
        if lock(&self.current)
            .as_ref()
            .is_some_and(|current| same_node(current, &old))
        {
            self.assign_current(None);
        }
        self.items.publish_replace(index);
        retain_first_error(&mut commit_error, transaction.finish());
        match commit_error {
            Some(error) => Err(error),
            None => Ok(old),
        }
    }

    /// Moves a child without changing its ownership or selection state.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let changed = {
            let _gate = lock(&self.membership_gate);
            self.items.move_item_silent(from_index, to_index)?
        };
        if changed {
            self.items.publish_move(from_index, to_index);
        }
        transaction.finish()
    }

    /// Clears all children, ownership links, and current selection.
    pub fn clear(&self) {
        let Ok(_transaction) = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        ) else {
            return;
        };
        let changed = {
            let _gate = lock(&self.membership_gate);
            for item in self.items() {
                if item
                    .parent_handle()
                    .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
                {
                    item.set_parent_handle(None);
                }
                item.set_current_flag(false);
            }
            self.items.clear_silent()
        };
        self.assign_current(None);
        if changed {
            self.items.publish_reset();
        }
    }

    /// Returns the current child, if selected.
    pub fn current(&self) -> Option<T> {
        lock(&self.current).clone()
    }

    /// Assigns a child as current or clears selection.
    ///
    /// Returns [`VmxError::NonChild`] for values outside this composite.
    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        self.assign_current_maybe_async(item, false, None)
    }

    /// Selects a constructed child.
    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        self.assign_current_maybe_async(Some(item.clone()), true, None)
    }

    /// Deselects `item`, rejecting values that are not current.
    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        self.assign_current_maybe_async(None, false, Some(item.id()))
    }

    /// Reports whether `item` belongs here and is constructed.
    pub fn can_select_component(&self, item: &T) -> bool {
        if self.membership_transaction_active.load(Ordering::Acquire) {
            return false;
        }
        let _gate = lock(&self.membership_gate);
        self.items()
            .iter()
            .any(|candidate| same_node(candidate, item))
            && item.status() == ConstructionStatus::Constructed
    }

    /// Controls construction of additions to a constructed composite.
    pub fn set_auto_construct_on_add(&self, enabled: bool) {
        *lock(&self.auto_construct_on_add) = enabled;
    }

    /// Controls whether selection assignments use the dispatcher.
    pub fn set_async_selection(&self, enabled: bool) {
        *lock(&self.async_selection) = enabled;
    }

    /// Sets the selector applied after children construct.
    pub fn set_current_selector<F>(&self, selector: F)
    where
        F: Fn(Vec<T>) -> Option<T> + Send + Sync + 'static,
    {
        *lock(&self.current_selector) = Some(Arc::new(selector));
    }

    /// Sets the callback invoked after effective current changes.
    pub fn on_current_changed<F>(&self, callback: F)
    where
        F: Fn(Option<T>) + Send + Sync + 'static,
    {
        *lock(&self.on_current_changed) = Some(Arc::new(callback));
    }

    /// Coalesces child-collection notifications produced by `action`.
    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        self.items.batch_update(action);
    }

    /// Constructs children before completing the composite transition.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                for item in self.items() {
                    item.construct()?;
                }
                if let Some(selector) = lock(&self.current_selector).clone() {
                    if let Some(selected) = selector(self.items()) {
                        if self
                            .items()
                            .iter()
                            .any(|candidate| same_node(candidate, &selected))
                        {
                            self.assign_current(selected.into());
                        }
                    }
                }
                Ok(())
            })
    }

    /// Clears selection and destructs all children.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            self.assign_current(None);
            for item in self.items() {
                item.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes all children and returns the first encountered error.
    pub fn dispose(&self) -> VmxResult<()> {
        let snapshot = loop {
            let _gate = lock(&self.membership_gate);
            match self.membership_transaction_control.dispose_disposition() {
                MembershipDisposeDisposition::Owned => {
                    let deferred = self.clone();
                    self.membership_transaction_control
                        .defer_dispose(move || deferred.dispose());
                    return Ok(());
                }
                MembershipDisposeDisposition::Foreign => {
                    drop(_gate);
                    self.membership_transaction_control.wait_until_inactive();
                    continue;
                }
                MembershipDisposeDisposition::Inactive => {
                    break if self.dispose_requested.swap(true, Ordering::AcqRel) {
                        None
                    } else {
                        Some(self.items())
                    };
                }
            }
        };
        let Some(snapshot) = snapshot else {
            return self.core.transition(LifecycleOperation::Dispose);
        };
        let mut first_error = None;
        for item in snapshot {
            retain_first_error(&mut first_error, item.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    fn disposal_pending(&self) -> bool {
        self.dispose_requested.load(Ordering::Acquire)
            || self.membership_transaction_control.has_deferred_dispose()
    }

    /// Returns the current lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }

    /// Destructs and then constructs the composite.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.destruct()?;
        self.construct()
    }

    /// Reports whether the composite is constructed.
    pub fn is_constructed(&self) -> bool {
        self.status() == ConstructionStatus::Constructed
    }

    /// Returns the current parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    fn assign_current(&self, next: Option<T>) {
        assign_current_state(&self.core, &self.current, &self.on_current_changed, next);
    }

    fn assign_current_maybe_async(
        &self,
        next: Option<T>,
        require_constructed: bool,
        expected_current_id: Option<usize>,
    ) -> VmxResult<()> {
        assign_current_maybe_async(
            CurrentAssignmentContext {
                core: &self.core,
                items: &self.items,
                current: &self.current,
                async_selection: &self.async_selection,
                on_current_changed: &self.on_current_changed,
                membership_gate: &self.membership_gate,
                membership_transaction_active: &self.membership_transaction_active,
                membership_transaction_control: &self.membership_transaction_control,
            },
            next,
            require_constructed,
            expected_current_id,
        )
    }
}

impl<T: VmNode, D: Dispatcher> VmCollection<T> for CompositeVm<T, D> {
    fn items(&self) -> Vec<T> {
        CompositeVm::items(self)
    }
    fn get(&self, index: usize) -> Option<T> {
        CompositeVm::get(self, index)
    }
    fn len(&self) -> usize {
        CompositeVm::len(self)
    }
    fn is_empty(&self) -> bool {
        CompositeVm::is_empty(self)
    }
    fn add(&self, item: T) -> VmxResult<()> {
        CompositeVm::add(self, item)
    }
    fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        CompositeVm::insert(self, index, item)
    }
    fn remove(&self, item: &T) -> VmxResult<()> {
        CompositeVm::remove(self, item)
    }
    fn remove_at(&self, index: usize) -> VmxResult<T> {
        CompositeVm::remove_at(self, index)
    }
    fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        CompositeVm::replace(self, index, item)
    }
    fn clear(&self) {
        CompositeVm::clear(self);
    }
    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        CompositeVm::move_item(self, from_index, to_index)
    }
    fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        CompositeVm::batch_update(self, action);
    }
}

impl<T: VmNode, D: Dispatcher> SelectableVmCollection<T> for CompositeVm<T, D> {
    fn current(&self) -> Option<T> {
        CompositeVm::current(self)
    }
    fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        CompositeVm::set_current(self, item)
    }
    fn select_component(&self, item: &T) -> VmxResult<()> {
        CompositeVm::select_component(self, item)
    }
    fn deselect_component(&self, item: &T) -> VmxResult<()> {
        CompositeVm::deselect_component(self, item)
    }
    fn can_select_component(&self, item: &T) -> bool {
        CompositeVm::can_select_component(self, item)
    }
}

impl<T: VmNode, D: Dispatcher> VmNode for CompositeVm<T, D> {
    fn id(&self) -> usize {
        CompositeVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        CompositeVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        CompositeVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.core.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.core.parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.core.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.core.is_selected()
    }
}

impl<T: TreeNode, D: Dispatcher> TreeNode for CompositeVm<T, D> {
    fn children_nodes(&self) -> Vec<Self> {
        Vec::new()
    }
}

impl<T: TreeNode, D: Dispatcher> CompositeVm<T, D> {
    /// Returns children as tree nodes.
    pub fn child_nodes(&self) -> Vec<T> {
        self.items()
    }

    /// Reports whether traversal should enter this composite.
    pub fn is_expanded_for_walk(&self) -> bool {
        self.core.is_expanded()
    }
}

impl<T: VmNode, D: Dispatcher> PartialEq for CompositeVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T: VmNode, D: Dispatcher> Eq for CompositeVm<T, D> {}

type FilterPredicate<T> = Arc<dyn Fn(&T) -> bool + Send + Sync>;
type ScorePredicate<T> = Arc<dyn Fn(&T) -> Option<i32> + Send + Sync>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Policy applied when filtering hides the current item.
pub enum FilteredCursorPolicy {
    /// Clear the filtered current item.
    Clear,
    /// Select the first remaining visible item.
    SnapToFirst,
}

#[derive(Clone)]
/// A filtered or scored projection over a source [`CompositeVm`].
///
/// Predicate projections preserve source order. Scored projections order by
/// descending score with stable source-order ties. Disposal freezes a snapshot.
pub struct FilteredCompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    source: CompositeVm<T, D>,
    predicate: Arc<Mutex<FilterPredicate<T>>>,
    scorer: Arc<Mutex<Option<ScorePredicate<T>>>>,
    current: Arc<Mutex<Option<T>>>,
    cursor_policy: Arc<Mutex<FilteredCursorPolicy>>,
    disposed: Arc<Mutex<bool>>,
    frozen: Arc<Mutex<Vec<T>>>,
}

impl<T: VmNode, D: Dispatcher> FilteredCompositeVm<T, D> {
    /// Creates a predicate-filtered projection.
    pub fn new<F>(source: CompositeVm<T, D>, predicate: F) -> Self
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        Self {
            source,
            predicate: Arc::new(Mutex::new(Arc::new(predicate))),
            scorer: Arc::new(Mutex::new(None)),
            current: Arc::new(Mutex::new(None)),
            cursor_policy: Arc::new(Mutex::new(FilteredCursorPolicy::Clear)),
            disposed: Arc::new(Mutex::new(false)),
            frozen: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Returns the source composite's message hub.
    pub fn hub(&self) -> MessageHub {
        self.source.hub()
    }

    /// Creates a projection that includes scored items in descending order.
    pub fn scored<F>(source: CompositeVm<T, D>, scorer: F) -> Self
    where
        F: Fn(&T) -> Option<i32> + Send + Sync + 'static,
    {
        Self {
            source,
            predicate: Arc::new(Mutex::new(Arc::new(|_| true))),
            scorer: Arc::new(Mutex::new(Some(Arc::new(scorer)))),
            current: Arc::new(Mutex::new(None)),
            cursor_policy: Arc::new(Mutex::new(FilteredCursorPolicy::Clear)),
            disposed: Arc::new(Mutex::new(false)),
            frozen: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Returns the current visible projection or the frozen disposed snapshot.
    pub fn visible(&self) -> Vec<T> {
        if *lock(&self.disposed) {
            return lock(&self.frozen).clone();
        }
        let predicate = lock(&self.predicate).clone();
        let scorer = lock(&self.scorer).clone();
        let mut indexed = self
            .source
            .items()
            .into_iter()
            .enumerate()
            .filter(|(_, item)| predicate(item))
            .filter_map(|(index, item)| match &scorer {
                Some(score) => score(&item).map(|score| (index, Some(score), item)),
                None => Some((index, None, item)),
            })
            .collect::<Vec<_>>();
        if scorer.is_some() {
            indexed.sort_by(
                |(left_index, left_score, _), (right_index, right_score, _)| {
                    right_score
                        .cmp(left_score)
                        .then_with(|| left_index.cmp(right_index))
                },
            );
        }
        indexed.into_iter().map(|(_, _, item)| item).collect()
    }

    /// Returns the number of visible items.
    pub fn visible_count(&self) -> usize {
        self.visible().len()
    }

    /// Returns the current visible item.
    pub fn current(&self) -> Option<T> {
        lock(&self.current).clone()
    }

    /// Assigns a visible current item or clears it.
    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        if let Some(item) = item.as_ref() {
            if !self
                .visible()
                .iter()
                .any(|candidate| same_node(candidate, item))
            {
                return Err(VmxError::NonChild);
            }
        }
        *lock(&self.current) = item;
        Ok(())
    }

    /// Replaces the predicate and reconciles current selection.
    pub fn set_predicate<F>(&self, predicate: F)
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        *lock(&self.predicate) = Arc::new(predicate);
        self.reconcile_current();
    }

    /// Sets the policy for a current item hidden by filtering.
    pub fn set_cursor_policy(&self, policy: FilteredCursorPolicy) {
        *lock(&self.cursor_policy) = policy;
    }

    /// Re-evaluates visibility and reconciles current selection.
    pub fn refresh(&self) {
        self.reconcile_current();
    }

    /// Re-evaluates scores and reconciles current selection.
    pub fn refresh_scores(&self) {
        self.reconcile_current();
    }

    /// Advances current within the visible projection, clamped at the end.
    pub fn move_next_visible(&self) {
        let visible = self.visible();
        if visible.is_empty() {
            *lock(&self.current) = None;
            return;
        }
        let next_index = self
            .current()
            .and_then(|current| visible.iter().position(|item| same_node(item, &current)))
            .map(|index| (index + 1).min(visible.len() - 1))
            .unwrap_or(0);
        *lock(&self.current) = Some(visible[next_index].clone());
    }

    /// Moves current backward within the visible projection.
    pub fn move_previous_visible(&self) {
        let visible = self.visible();
        if visible.is_empty() {
            *lock(&self.current) = None;
            return;
        }
        let previous_index = self
            .current()
            .and_then(|current| visible.iter().position(|item| same_node(item, &current)))
            .map(|index| index.saturating_sub(1))
            .unwrap_or(0);
        *lock(&self.current) = Some(visible[previous_index].clone());
    }

    /// Freezes the current visible projection for subsequent reads.
    pub fn dispose(&self) {
        *lock(&self.frozen) = self.visible();
        *lock(&self.disposed) = true;
    }

    fn reconcile_current(&self) {
        let visible = self.visible();
        let current_is_visible = self
            .current()
            .map(|current| visible.iter().any(|item| same_node(item, &current)))
            .unwrap_or(true);
        if current_is_visible {
            return;
        }
        let next = match *lock(&self.cursor_policy) {
            FilteredCursorPolicy::Clear => None,
            FilteredCursorPolicy::SnapToFirst => visible.first().cloned(),
        };
        *lock(&self.current) = next;
    }
}

type ChildrenFactory<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;

#[derive(Clone)]
/// A fluent builder for [`CompositeVm`] instances and initial children.
pub struct CompositeVmBuilder<T: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children: Option<ChildrenFactory<T>>,
    auto_construct_on_add: bool,
    async_selection: bool,
    current_selector: Option<CurrentSelector<T>>,
}

impl<T: VmNode> Default for CompositeVmBuilder<T, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            children: None,
            auto_construct_on_add: false,
            async_selection: false,
            current_selector: None,
        }
    }
}

impl<T: VmNode, D: Dispatcher> CompositeVmBuilder<T, D> {
    /// Sets the required composite name.
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    /// Sets the optional presentation hint.
    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    /// Supplies the required message hub and dispatcher.
    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
        self
    }

    /// Supplies the required initial-child factory.
    pub fn children<F>(mut self, children: F) -> Self
    where
        F: Fn() -> Vec<T> + Send + Sync + 'static,
    {
        self.children = Some(Arc::new(children));
        self
    }

    /// Configures construction of later additions.
    pub fn auto_construct_on_add(mut self, enabled: bool) -> Self {
        self.auto_construct_on_add = enabled;
        self
    }

    /// Configures dispatcher-based selection assignment.
    pub fn async_selection(mut self, enabled: bool) -> Self {
        self.async_selection = enabled;
        self
    }

    /// Supplies the selector applied after construction.
    pub fn current<F>(mut self, selector: F) -> Self
    where
        F: Fn(Vec<T>) -> Option<T> + Send + Sync + 'static,
    {
        self.current_selector = Some(Arc::new(selector));
        self
    }

    /// Validates required fields and creates the populated composite.
    pub fn build(self) -> VmxResult<CompositeVm<T, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let children = self
            .children
            .ok_or_else(|| VmxError::BuilderValidation("children is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let vm = CompositeVm::with_services(name, hub, dispatcher);
        if let Some(hint) = self.hint {
            vm.core.set_hint(Some(hint));
        }
        vm.set_auto_construct_on_add(self.auto_construct_on_add);
        vm.set_async_selection(self.async_selection);
        if let Some(selector) = self.current_selector {
            vm.set_current_selector(move |items| selector(items));
        }
        vm.attach_population(children(), false, || {})?;
        Ok(vm)
    }
}

impl<T: VmNode> CompositeVm<T, NullDispatcher> {
    /// Returns a composite builder configured for null dispatch.
    pub fn builder() -> CompositeVmBuilder<T, NullDispatcher> {
        CompositeVmBuilder::default()
    }

    /// Creates a composite from an options value.
    pub fn create(options: CompositeVmOptions<T>) -> VmxResult<Self> {
        let mut builder = Self::builder();
        if let Some(name) = options.name {
            builder = builder.name(name);
        }
        if let Some(hint) = options.hint {
            builder = builder.hint(hint);
        }
        if let Some(children) = options.children {
            builder = builder.children(move || children.clone());
        }
        builder
            .services(options.hub, options.dispatcher)
            .auto_construct_on_add(options.auto_construct_on_add)
            .build()
    }
}

/// Options for creating a null-dispatcher [`CompositeVm`].
pub struct CompositeVmOptions<T: VmNode> {
    /// Optional name; validation fails when omitted.
    pub name: Option<String>,
    /// Optional presentation hint.
    pub hint: Option<String>,
    /// Message hub shared with the child collection.
    pub hub: MessageHub,
    /// Dispatcher used for foreground work.
    pub dispatcher: NullDispatcher,
    /// Optional initial children; validation fails when omitted.
    pub children: Option<Vec<T>>,
    /// Whether later additions auto-construct.
    pub auto_construct_on_add: bool,
}

type ModelFactory<M> = Arc<dyn Fn() -> Vec<M> + Send + Sync>;
type ChildModelMapper<M, T> = Arc<dyn Fn(M) -> T + Send + Sync>;

#[derive(Clone)]
/// A composite that materializes child view models from child models on first construction.
pub struct ModeledCompositeVm<
    M: Clone + PartialEq + Send + Sync + 'static,
    T: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    inner: CompositeVm<T, D>,
    children_models: ModelFactory<M>,
    child_model_to_child_view_model: ChildModelMapper<M, T>,
    loaded: Arc<Mutex<bool>>,
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher>
    ModeledCompositeVm<M, T, D>
{
    /// Creates a modeled composite from model and mapping factories.
    pub fn new<F, G>(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        children_models: F,
        child_model_to_child_view_model: G,
    ) -> Self
    where
        F: Fn() -> Vec<M> + Send + Sync + 'static,
        G: Fn(M) -> T + Send + Sync + 'static,
    {
        Self {
            inner: CompositeVm::with_services(name, hub, dispatcher),
            children_models: Arc::new(children_models),
            child_model_to_child_view_model: Arc::new(child_model_to_child_view_model),
            loaded: Arc::new(Mutex::new(false)),
        }
    }

    /// Returns a fluent modeled-composite builder.
    pub fn builder() -> ModeledCompositeVmBuilder<M, T, D> {
        ModeledCompositeVmBuilder::default()
    }

    /// Returns the materialized child snapshot.
    pub fn items(&self) -> Vec<T> {
        self.inner.items()
    }

    /// Returns the local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    /// Returns the injected message hub.
    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    /// Registers cleanup work that runs on disposal.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.own(cleanup);
    }

    /// Publishes a change for an application-defined property.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }

    /// Returns the child at `index`, if materialized.
    pub fn get(&self, index: usize) -> Option<T> {
        self.inner.get(index)
    }

    /// Returns the number of materialized children.
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Reports whether no children are materialized.
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Returns the current child, if selected.
    pub fn current(&self) -> Option<T> {
        self.inner.current()
    }

    /// Assigns a materialized child as current or clears selection.
    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        self.inner.set_current(item)
    }

    /// Selects a constructed materialized child.
    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        self.inner.select_component(item)
    }

    /// Materializes children once, constructs them, and constructs the composite.
    pub fn construct(&self) -> VmxResult<()> {
        let should_load = !*lock(&self.loaded);
        if should_load {
            let children = (self.children_models)()
                .into_iter()
                .map(|model| (self.child_model_to_child_view_model)(model))
                .collect();
            let loaded = Arc::clone(&self.loaded);
            self.inner
                .attach_population(children, true, move || *lock(&loaded) = true)?;
        }
        self.inner.construct()
    }

    /// Returns the current lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    /// Reconstructs the already-materialized composite.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.reconstruct()
    }

    /// Reports whether the composite is constructed.
    pub fn is_constructed(&self) -> bool {
        self.inner.is_constructed()
    }

    /// Returns the current parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> VmNode
    for ModeledCompositeVm<M, T, D>
{
    fn id(&self) -> usize {
        self.inner.id()
    }

    fn construct(&self) -> VmxResult<()> {
        ModeledCompositeVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.core.parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.inner.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.inner.is_current()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> PartialEq
    for ModeledCompositeVm<M, T, D>
{
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> Eq
    for ModeledCompositeVm<M, T, D>
{
}

#[derive(Clone)]
/// A fluent builder for [`ModeledCompositeVm`].
pub struct ModeledCompositeVmBuilder<
    M: Clone + PartialEq + Send + Sync + 'static,
    T: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    name: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children_models: Option<ModelFactory<M>>,
    child_model_to_child_view_model: Option<ChildModelMapper<M, T>>,
    async_selection: bool,
    current_selector: Option<CurrentSelector<T>>,
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> Default
    for ModeledCompositeVmBuilder<M, T, D>
{
    fn default() -> Self {
        Self {
            name: None,
            hub: None,
            dispatcher: None,
            children_models: None,
            child_model_to_child_view_model: None,
            async_selection: false,
            current_selector: None,
        }
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher>
    ModeledCompositeVmBuilder<M, T, D>
{
    /// Sets the required composite name.
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    /// Supplies the required message hub and dispatcher.
    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
        self
    }

    /// Supplies the required child-model factory.
    pub fn children_models<F>(mut self, children_models: F) -> Self
    where
        F: Fn() -> Vec<M> + Send + Sync + 'static,
    {
        self.children_models = Some(Arc::new(children_models));
        self
    }

    /// Supplies the required model-to-view-model mapper.
    pub fn child_model_to_child_view_model<G>(mut self, mapper: G) -> Self
    where
        G: Fn(M) -> T + Send + Sync + 'static,
    {
        self.child_model_to_child_view_model = Some(Arc::new(mapper));
        self
    }

    /// Configures dispatcher-based selection assignment.
    pub fn async_selection(mut self, enabled: bool) -> Self {
        self.async_selection = enabled;
        self
    }

    /// Supplies the selector applied after child construction.
    pub fn current<F>(mut self, selector: F) -> Self
    where
        F: Fn(Vec<T>) -> Option<T> + Send + Sync + 'static,
    {
        self.current_selector = Some(Arc::new(selector));
        self
    }

    /// Validates required fields and creates the modeled composite.
    pub fn build(self) -> VmxResult<ModeledCompositeVm<M, T, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let children_models = self.children_models.ok_or_else(|| {
            VmxError::BuilderValidation("children_models is required".to_string())
        })?;
        let child_model_to_child_view_model =
            self.child_model_to_child_view_model.ok_or_else(|| {
                VmxError::BuilderValidation(
                    "child_model_to_child_view_model is required".to_string(),
                )
            })?;
        let vm = ModeledCompositeVm {
            inner: CompositeVm::with_services(name, hub, dispatcher),
            children_models,
            child_model_to_child_view_model,
            loaded: Arc::new(Mutex::new(false)),
        };
        vm.inner.set_async_selection(self.async_selection);
        if let Some(selector) = self.current_selector {
            vm.inner.set_current_selector(move |items| selector(items));
        }
        Ok(vm)
    }
}
