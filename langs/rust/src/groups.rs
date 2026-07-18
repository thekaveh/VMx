//! Group view models with managed child membership and selection.
//!
//! Spec: `spec/07-group-vm.md`.

use super::{
    begin_membership_transaction, begin_parent_transfer, finish_with_first_error, lock,
    retain_first_error, Arc, AtomicBool, ComponentCore, ConstructionStatus, Dispatcher, HashSet,
    LifecycleOperation, MembershipDisposeDisposition, MembershipTransactionControl,
    MembershipTransactionGuard, MessageHub, Mutex, NullDispatcher, ObservableList, Ordering,
    ParentHandle, ParentRegistration, ParentTransfer, PropertyChangedStream, RelayCommand,
    VmCollection, VmNode, VmxError, VmxResult,
};

type ChildrenFactory<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;

#[derive(Clone)]
/// A lifecycle-aware, parent-owning collection of view-model children.
///
/// Membership operations transfer each child's parent registration atomically.
/// Lifecycle transitions propagate to the current children, and optional
/// auto-construction constructs children added to an already-constructed group.
pub struct GroupVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
    ownership: ParentRegistration,
    auto_construct_on_add: Arc<Mutex<bool>>,
    dispose_requested: Arc<AtomicBool>,
    membership_gate: Arc<Mutex<()>>,
    membership_transaction_active: Arc<AtomicBool>,
    membership_transaction_control: Arc<MembershipTransactionControl>,
}

impl<T: VmNode> GroupVm<T, NullDispatcher> {
    /// Creates an empty group with null services.
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<T: VmNode, D: Dispatcher> GroupVm<T, D> {
    /// Creates an empty group with explicit message and dispatch services.
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        let core = ComponentCore::new(name, hub.clone(), dispatcher);
        let items: ObservableList<T> = ObservableList::new(core.id(), hub);
        let dispose_requested = Arc::new(AtomicBool::new(false));
        let membership_gate = Arc::new(Mutex::new(()));
        let membership_transaction_active = Arc::new(AtomicBool::new(false));
        let membership_transaction_control = Arc::new(MembershipTransactionControl::new());
        let ownership = ParentRegistration::new(
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
                let items = items.clone();
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
                    let commit_items = items.clone();
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
        );
        Self {
            core,
            items,
            ownership,
            auto_construct_on_add: Arc::new(Mutex::new(false)),
            dispose_requested,
            membership_gate,
            membership_transaction_active,
            membership_transaction_control,
        }
    }

    /// Returns this group's property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the message hub used by the group and its collection.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers cleanup work that runs when the group is disposed.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.core.own(cleanup);
    }

    /// Publishes a property-change message for `property_name`.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Returns the stable identity of this group.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns a snapshot of the current children in collection order.
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

    /// Reports whether the group has no children.
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// Appends a child, transferring it from any previous parent atomically.
    ///
    /// When auto-construction is active on a constructed group, construction
    /// failure rolls back both membership and the previous-parent transfer.
    pub fn add(&self, item: T) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let original_status = item.status();
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
            let compensation_error = if original_status == ConstructionStatus::Destructed
                && item.status() == ConstructionStatus::Constructed
            {
                item.destruct().err()
            } else {
                None
            };
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            return Err(compensation_error.unwrap_or(error));
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

    /// Inserts a child at `index` with the same ownership rules as [`add`](Self::add).
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let original_status = item.status();
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
            let compensation_error = if original_status == ConstructionStatus::Destructed
                && item.status() == ConstructionStatus::Constructed
            {
                item.destruct().err()
            } else {
                None
            };
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            return Err(compensation_error.unwrap_or(error));
        }
        let mut commit_error = transfer.and_then(|transfer| transfer.commit().err());
        self.items.publish_add(index);
        retain_first_error(&mut commit_error, transaction.finish());
        finish_with_first_error(commit_error)
    }

    /// Removes `item` and clears this group as its parent.
    ///
    /// Returns [`VmxError::NonChild`] when the item is not a member.
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
                .position(|candidate| candidate.id() == item.id())
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
        self.items.publish_remove(index);
        transaction.finish()
    }

    /// Removes and returns the child at `index`, clearing its parent link.
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
        self.items.publish_remove(index);
        transaction.finish()?;
        Ok(removed)
    }

    /// Replaces and returns the child at `index` using atomic parent transfer.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let original_status = item.status();
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
            drop(_gate);
            let compensation_error = if original_status == ConstructionStatus::Destructed
                && item.status() == ConstructionStatus::Constructed
            {
                item.destruct().err()
            } else {
                None
            };
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            return Err(compensation_error.unwrap_or(error));
        }
        let mut commit_error = transfer.and_then(|transfer| transfer.commit().err());
        old.set_parent_handle(None);
        self.items.publish_replace(index);
        retain_first_error(&mut commit_error, transaction.finish());
        match commit_error {
            Some(error) => Err(error),
            None => Ok(old),
        }
    }

    /// Moves a child between collection indices without changing ownership.
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

    /// Removes all children and clears their links to this parent.
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
            }
            self.items.clear_silent()
        };
        if changed {
            self.items.publish_reset();
        }
    }

    /// Controls whether new children are constructed in a constructed group.
    pub fn set_auto_construct_on_add(&self, enabled: bool) {
        *lock(&self.auto_construct_on_add) = enabled;
    }

    /// Coalesces collection notifications produced by `action`.
    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        self.items.batch_update(action);
    }

    /// Constructs the group and each current child in collection order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                for item in self.items() {
                    item.construct()?;
                }
                Ok(())
            })
    }

    /// Destructs the group and each current child in collection order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            for item in self.items() {
                item.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes all children and the group, returning the first encountered error.
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

    /// Marks the group as selected.
    pub fn select(&self) {
        self.core.select();
    }

    /// Marks the group as not selected.
    pub fn deselect(&self) {
        self.core.deselect();
    }

    /// Reports whether the group is selected.
    pub fn is_selected(&self) -> bool {
        self.core.is_selected()
    }

    /// Creates a command enabled while the group is not selected.
    pub fn select_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new({
            let vm = vm.clone();
            move || vm.select()
        })
        .with_can_execute(move || !vm.is_selected())
    }

    /// Creates a command enabled while the group is selected.
    pub fn deselect_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new({
            let vm = vm.clone();
            move || vm.deselect()
        })
        .with_can_execute(move || vm.is_selected())
    }
}

impl<T: VmNode, D: Dispatcher> VmCollection<T> for GroupVm<T, D> {
    fn items(&self) -> Vec<T> {
        GroupVm::items(self)
    }
    fn get(&self, index: usize) -> Option<T> {
        GroupVm::get(self, index)
    }
    fn len(&self) -> usize {
        GroupVm::len(self)
    }
    fn is_empty(&self) -> bool {
        GroupVm::is_empty(self)
    }
    fn add(&self, item: T) -> VmxResult<()> {
        GroupVm::add(self, item)
    }
    fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        GroupVm::insert(self, index, item)
    }
    fn remove(&self, item: &T) -> VmxResult<()> {
        GroupVm::remove(self, item)
    }
    fn remove_at(&self, index: usize) -> VmxResult<T> {
        GroupVm::remove_at(self, index)
    }
    fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        GroupVm::replace(self, index, item)
    }
    fn clear(&self) {
        GroupVm::clear(self);
    }
    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        GroupVm::move_item(self, from_index, to_index)
    }
    fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        GroupVm::batch_update(self, action);
    }
}

impl<T: VmNode, D: Dispatcher> VmNode for GroupVm<T, D> {
    fn id(&self) -> usize {
        GroupVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        GroupVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        GroupVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
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

impl<T: VmNode, D: Dispatcher> PartialEq for GroupVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T: VmNode, D: Dispatcher> Eq for GroupVm<T, D> {}

#[derive(Clone)]
/// A fluent builder for [`GroupVm`] instances and initial populations.
pub struct GroupVmBuilder<T: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children: Option<ChildrenFactory<T>>,
    auto_construct_on_add: bool,
}

impl<T: VmNode> Default for GroupVmBuilder<T, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            children: None,
            auto_construct_on_add: false,
        }
    }
}

impl<T: VmNode, D: Dispatcher> GroupVmBuilder<T, D> {
    /// Sets the required group name.
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

    /// Supplies the required factory for the initial child snapshot.
    pub fn children<F>(mut self, children: F) -> Self
    where
        F: Fn() -> Vec<T> + Send + Sync + 'static,
    {
        self.children = Some(Arc::new(children));
        self
    }

    /// Configures automatic construction of children added after construction.
    pub fn auto_construct_on_add(mut self, enabled: bool) -> Self {
        self.auto_construct_on_add = enabled;
        self
    }

    /// Validates the configuration and creates the populated group.
    ///
    /// The initial population is attached atomically without being constructed.
    pub fn build(self) -> VmxResult<GroupVm<T, D>> {
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
        let vm = GroupVm::with_services(name, hub, dispatcher);
        if let Some(hint) = self.hint {
            vm.core.set_hint(Some(hint));
        }
        vm.set_auto_construct_on_add(self.auto_construct_on_add);
        vm.attach_population(children(), false, || {})?;
        Ok(vm)
    }
}

impl<T: VmNode> GroupVm<T, NullDispatcher> {
    /// Returns a builder configured for null dispatch services.
    pub fn builder() -> GroupVmBuilder<T, NullDispatcher> {
        GroupVmBuilder::default()
    }

    /// Creates a group from an options value.
    pub fn create(options: GroupVmOptions<T>) -> VmxResult<Self> {
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

/// Options for creating a null-dispatcher [`GroupVm`].
pub struct GroupVmOptions<T: VmNode> {
    /// Optional group name; validation fails when omitted.
    pub name: Option<String>,
    /// Optional presentation hint.
    pub hint: Option<String>,
    /// Message hub shared with the group collection.
    pub hub: MessageHub,
    /// Dispatcher used for lifecycle and property work.
    pub dispatcher: NullDispatcher,
    /// Optional initial children; validation fails when omitted.
    pub children: Option<Vec<T>>,
    /// Whether later additions auto-construct in a constructed group.
    pub auto_construct_on_add: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ComponentVm;

    #[test]
    fn population_surfaces_lifecycle_compensation_failure() {
        let first =
            ComponentVm::with_model("first", "first", MessageHub::new(), NullDispatcher::new());
        first.on_destruct(|| Err(VmxError::Other("compensation failed".to_string())));
        let failing = ComponentVm::with_model(
            "failing",
            "failing",
            MessageHub::new(),
            NullDispatcher::new(),
        );
        failing.on_construct(|| Err(VmxError::Other("construction failed".to_string())));
        let group = GroupVm::new("group");

        assert_eq!(
            group.attach_population(vec![first.clone(), failing], true, || {}),
            Err(VmxError::Other("compensation failed".to_string()))
        );
        assert_eq!(first.status(), ConstructionStatus::Constructed);
        assert!(group.is_empty());
    }
}
