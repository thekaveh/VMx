//! Group view models with managed child membership and selection.
//!
//! Spec: `spec/09-groups-and-modeled-crud.md`.

use super::{
    begin_parent_transfer, finish_with_first_error, lock, retain_first_error, Arc, ComponentCore,
    ConstructionStatus, Dispatcher, LifecycleOperation, MessageHub, Mutex, NullDispatcher,
    ObservableList, ParentHandle, ParentRegistration, ParentTransfer, PropertyChangedStream,
    RelayCommand, VmCollection, VmNode, VmxError, VmxResult,
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
                move |child_id, owner_handle| {
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
                    Ok(ParentTransfer::new(
                        move || commit_items.publish_remove(index),
                        move || {
                            rollback_items
                                .insert_silent(index, removed.clone())
                                .expect("rollback index remains valid");
                            removed.set_parent_handle(Some(owner_handle));
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
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        item.set_parent_handle(Some(self.ownership.handle()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            if let Err(error) = item.construct() {
                item.set_parent_handle(None);
                if let Some(transfer) = transfer {
                    transfer.rollback();
                }
                return Err(error);
            }
        }
        if let Some(transfer) = transfer {
            transfer.commit();
        }
        self.items.push(item);
        Ok(())
    }

    fn attach_population(&self, candidates: Vec<T>, construct: bool) -> VmxResult<()> {
        let start = self.len();
        let mut transfers = Vec::with_capacity(candidates.len());
        let mut original_statuses = Vec::with_capacity(candidates.len());
        let result = (|| {
            for child in &candidates {
                let transfer = begin_parent_transfer(child, &self.ownership.handle())?;
                transfers.push(transfer);
                original_statuses.push(child.status());
                child.set_parent_handle(Some(self.ownership.handle()));
                self.items.insert_silent(self.len(), child.clone())?;
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
            while self.len() > start {
                let _ = self.items.remove_at_silent(self.len() - 1);
            }
            for (child, original_status) in candidates
                .iter()
                .zip(&original_statuses)
                .take(transfers.len())
                .rev()
            {
                if *original_status == ConstructionStatus::Destructed
                    && child.status() == ConstructionStatus::Constructed
                {
                    let _ = child.destruct();
                }
                if child
                    .parent_handle()
                    .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
                {
                    child.set_parent_handle(None);
                }
            }
            for transfer in transfers.into_iter().rev().flatten() {
                transfer.rollback();
            }
            return Err(error);
        }

        for transfer in transfers.into_iter().flatten() {
            transfer.commit();
        }
        for child in &candidates {
            if let Some(index) = self
                .items
                .to_vec()
                .iter()
                .position(|candidate| candidate.id() == child.id())
                .filter(|index| *index >= start)
            {
                self.items.publish_add(index);
            }
        }
        Ok(())
    }

    /// Inserts a child at `index` with the same ownership rules as [`add`](Self::add).
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        if index > self.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        item.set_parent_handle(Some(self.ownership.handle()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            if let Err(error) = item.construct() {
                item.set_parent_handle(None);
                if let Some(transfer) = transfer {
                    transfer.rollback();
                }
                return Err(error);
            }
        }
        if let Some(transfer) = transfer {
            transfer.commit();
        }
        self.items.insert(index, item)
    }

    /// Removes `item` and clears this group as its parent.
    ///
    /// Returns [`VmxError::NonChild`] when the item is not a member.
    pub fn remove(&self, item: &T) -> VmxResult<()> {
        let index = self
            .items()
            .iter()
            .position(|candidate| candidate.id() == item.id())
            .ok_or(VmxError::NonChild)?;
        let removed = self.items.remove_at(index).expect("index checked");
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        Ok(())
    }

    /// Removes and returns the child at `index`, clearing its parent link.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let removed = self
            .items
            .remove_at(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        Ok(removed)
    }

    /// Replaces and returns the child at `index` using atomic parent transfer.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let old = self
            .items
            .get(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        item.set_parent_handle(Some(self.ownership.handle()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            if let Err(error) = item.construct() {
                item.set_parent_handle(None);
                if let Some(transfer) = transfer {
                    transfer.rollback();
                }
                return Err(error);
            }
        }
        if let Some(transfer) = transfer {
            transfer.commit();
        }
        old.set_parent_handle(None);
        self.items.replace(index, item)?;
        Ok(old)
    }

    /// Moves a child between collection indices without changing ownership.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        self.items.move_item(from_index, to_index)
    }

    /// Removes all children and clears their links to this parent.
    pub fn clear(&self) {
        for item in self.items() {
            if item
                .parent_handle()
                .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
            {
                item.set_parent_handle(None);
            }
        }
        self.items.clear();
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
        let mut first_error = None;
        for item in self.items() {
            retain_first_error(&mut first_error, item.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
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
        vm.attach_population(children(), false)?;
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
