//! Selectable composite view models, filtered projections, and builders.
//!
//! Spec: `spec/06-composite-vm.md`.

use super::{
    begin_membership_transaction, begin_parent_transfer, catch_unwind, compensate_auto_start,
    finish_with_first_error, lock, replace_locked, resume_unwind, retain_first_error,
    retain_first_failure, retain_parent_transfer_commit, rollback_error, Arc, AssertUnwindSafe,
    AtomicBool, ChildOrder, ComponentCore, ConstructionStatus, Dispatcher, HashSet, LateStarts,
    LifecycleOperation, MembershipDisposeDisposition, MembershipTransactionControl,
    MembershipTransactionGuard, MessageHub, Mutex, NullDispatcher, ObservableList, Ordering,
    ParentHandle, ParentRegistration, ParentTransfer, PropertyChangedStream, PublicationLease,
    RelayCommand, StartAttempt, TreeNode, TreeNodeRef, ViewModelType, VmNode, VmxError, VmxResult,
};
use crate::components::ComponentCommands;
use crate::{Message, Subscription, ValueStream};
use std::thread::{self, ThreadId};

type CurrentChangedCallback<T> = Arc<dyn Fn(Option<T>) + Send + Sync>;
type CurrentSelector<T> = Arc<dyn Fn(Vec<T>) -> Option<T> + Send + Sync>;

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

/// The membership changes a transaction can still roll back (spec/06 §4.3
/// rules 2 and 4): children that an add, insert, replacement or population
/// attached but has not admitted, and a transfer detach whose commit has not
/// run. `owner` is the thread whose transaction staged them.
#[derive(Default)]
struct UncommittedMembership {
    owner: Option<ThreadId>,
    staged: HashSet<usize>,
    detaching: bool,
}

impl UncommittedMembership {
    fn stage(&mut self, id: usize) {
        self.owner = Some(thread::current().id());
        self.staged.insert(id);
    }

    fn admit(&mut self, id: usize) {
        self.staged.remove(&id);
        self.release_if_committed();
    }

    fn begin_detach(&mut self) {
        self.owner = Some(thread::current().id());
        self.detaching = true;
    }

    fn end_detach(&mut self) {
        self.detaching = false;
        self.release_if_committed();
    }

    fn release_if_committed(&mut self) {
        if self.staged.is_empty() && !self.detaching {
            self.owner = None;
        }
    }

    /// Reports whether this thread owns a transaction that is still
    /// uncommitted (spec/06 §4.3 rule 4).
    fn owned_by_current_thread(&self) -> bool {
        (!self.staged.is_empty() || self.detaching) && self.owner == Some(thread::current().id())
    }
}

/// Children one admission staged. They stay unselectable until
/// [`StagedMembers::admit`] runs. Dropping the record, as on a panic, admits
/// what is left so no child stays unselectable.
struct StagedMembers {
    uncommitted: Arc<Mutex<UncommittedMembership>>,
    ids: Vec<usize>,
}

impl StagedMembers {
    /// Marks `id` attached but not admitted. Call under the membership gate
    /// that attaches it.
    fn stage(&mut self, id: usize) {
        lock(&self.uncommitted).stage(id);
        self.ids.push(id);
    }

    /// Clears the marks, on admission or on rollback. Call under the
    /// membership gate, before `CollectionChanged` publishes.
    fn admit(mut self) {
        self.release();
    }

    fn release(&mut self) {
        if self.ids.is_empty() {
            return;
        }
        let mut uncommitted = lock(&self.uncommitted);
        for id in self.ids.drain(..) {
            uncommitted.admit(id);
        }
    }
}

impl Drop for StagedMembers {
    fn drop(&mut self) {
        self.release();
    }
}

/// A committed `current` change that still has to publish. It holds the
/// current-publication lease until [`CompositeSelection::publish`] ends it.
struct CurrentCommit<T: VmNode> {
    value: Option<T>,
    previous: Option<T>,
    publish_previous: bool,
    publish_value: bool,
    lease: PublicationLease,
}

/// The state every selection path of a composite shares (spec/06 §4.3,
/// ADR-0173). No selection path opens, joins or waits for a membership
/// transaction. Each one validates and commits `current` and both current
/// flags under the membership gate, then publishes after releasing it while
/// it holds the current-publication lease. It holds no core, so a construct
/// walk that keeps it cannot keep the composite alive (#750).
struct CompositeSelection<T: VmNode> {
    items: ObservableList<T>,
    current: Arc<Mutex<Option<T>>>,
    on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>>,
    async_selection: Arc<Mutex<bool>>,
    gate: Arc<Mutex<()>>,
    dispose_requested: Arc<AtomicBool>,
    control: Arc<MembershipTransactionControl>,
    uncommitted: Arc<Mutex<UncommittedMembership>>,
}

impl<T: VmNode> Clone for CompositeSelection<T> {
    fn clone(&self) -> Self {
        Self {
            items: self.items.clone(),
            current: Arc::clone(&self.current),
            on_current_changed: Arc::clone(&self.on_current_changed),
            async_selection: Arc::clone(&self.async_selection),
            gate: Arc::clone(&self.gate),
            dispose_requested: Arc::clone(&self.dispose_requested),
            control: Arc::clone(&self.control),
            uncommitted: Arc::clone(&self.uncommitted),
        }
    }
}

impl<T: VmNode> CompositeSelection<T> {
    /// Requested or deferred disposal (spec/06 §4.3 rule 3).
    fn disposal_pending(&self) -> bool {
        self.dispose_requested.load(Ordering::Acquire) || self.control.disposal_deferred()
    }

    /// Starts recording the children one admission attaches.
    fn staging(&self) -> StagedMembers {
        StagedMembers {
            uncommitted: Arc::clone(&self.uncommitted),
            ids: Vec::new(),
        }
    }

    /// Reports whether this thread owns an uncommitted membership transaction
    /// of the composite (spec/06 §4.3 rule 4).
    fn in_own_uncommitted_transaction(&self) -> bool {
        lock(&self.uncommitted).owned_by_current_thread()
    }

    /// Committed membership (spec/06 §4.3 rule 2). A `Disposed` child is
    /// not a member for selection (ADR-0189). Call under the gate.
    fn is_selectable_member_locked(&self, item: &T) -> bool {
        self.items
            .to_vec()
            .iter()
            .any(|candidate| same_node(candidate, item))
            && !lock(&self.uncommitted).staged.contains(&item.id())
            && item.status() != ConstructionStatus::Disposed
    }

    /// Reports whether a selection that rules 2, 3 and 4 admit changes
    /// nothing because the composite is `Destructing` (spec/06 §4.3 rule 8,
    /// ADR-0188). The composite publishes `Destructing` before its destruct
    /// clear takes the gate, so a read under the gate is sound. A null
    /// clear is never refused. Call under the gate.
    fn destructing_refuses_locked<D: Dispatcher>(
        core: &ComponentCore<D>,
        next: Option<&T>,
    ) -> bool {
        next.is_some() && core.status() == ConstructionStatus::Destructing
    }

    /// Reports whether `select_component(item)` would succeed now.
    fn can_select(&self, item: &T) -> bool {
        let _gate = lock(&self.gate);
        !self.in_own_uncommitted_transaction()
            && !self.disposal_pending()
            && self.is_selectable_member_locked(item)
            && item.status() == ConstructionStatus::Constructed
    }

    /// Validates a selection call (spec/06 §4.3 rules 2, 3 and 4). Call
    /// under the gate.
    fn validate_locked(
        &self,
        next: Option<&T>,
        require_constructed: bool,
        expected_current_id: Option<usize>,
    ) -> VmxResult<()> {
        if self.in_own_uncommitted_transaction() {
            return Err(VmxError::OwnershipTransactionInProgress);
        }
        if let Some(next) = next {
            if self.disposal_pending() {
                return Err(VmxError::Disposed);
            }
            if !self.is_selectable_member_locked(next)
                || (require_constructed && next.status() != ConstructionStatus::Constructed)
            {
                return Err(VmxError::NonChild);
            }
        }
        if let Some(expected) = expected_current_id {
            if lock(&self.current)
                .as_ref()
                .is_none_or(|current| current.id() != expected)
            {
                return Err(VmxError::NotCurrent);
            }
        }
        Ok(())
    }

    /// Commits `next` and both current flags and begins the publication
    /// lease. Returns `None` when `next` is already current. Call under the
    /// gate.
    fn commit_locked(&self, next: Option<T>) -> Option<CurrentCommit<T>> {
        let previous = {
            let mut current = lock(&self.current);
            if same_optional_node(current.as_ref(), next.as_ref()) {
                return None;
            }
            std::mem::replace(&mut *current, next.clone())
        };
        let publish_previous = previous
            .as_ref()
            .is_some_and(|previous| previous.commit_current_flag(false));
        let publish_value = next
            .as_ref()
            .is_some_and(|next| next.commit_current_flag(true));
        Some(CurrentCommit {
            value: next,
            previous,
            publish_previous,
            publish_value,
            lease: self.control.begin_publication(),
        })
    }

    /// The detach clear (spec/06 §4.3 rule 6): clears `current` only while
    /// `removed` is still current. Call under the gate.
    fn clear_if_current_locked(&self, removed: &T) -> Option<CurrentCommit<T>> {
        self.clear_if_current_id_locked(removed.id())
    }

    fn clear_if_current_id_locked(&self, id: usize) -> Option<CurrentCommit<T>> {
        let is_current = lock(&self.current)
            .as_ref()
            .is_some_and(|current| current.id() == id);
        if is_current {
            self.commit_locked(None)
        } else {
            None
        }
    }

    /// The dispose clear (spec/06 §4.3 rule 9, ADR-0189): after the child
    /// `child_id` published `Disposed` from its own `dispose()`, clears
    /// `current` while that child is still current. It is not a selection
    /// call, so rules 3, 4 and 8 never refuse it. It does not run while
    /// disposal of the composite is pending or after it is `Disposed`, so
    /// the composite's own dispose cascade does not clear `current`.
    fn clear_for_disposed_child<D: Dispatcher>(
        &self,
        core: &ComponentCore<D>,
        child_id: usize,
    ) -> VmxResult<()> {
        let commit = {
            let _gate = lock(&self.gate);
            if self.disposal_pending() || core.status() == ConstructionStatus::Disposed {
                None
            } else {
                self.clear_if_current_id_locked(child_id)
            }
        };
        commit.map_or(Ok(()), |commit| self.publish(core, commit))
    }

    /// Publishes a committed change under its lease: the current flags, then
    /// `current`, then the callback. Ending the lease can run a disposal that
    /// a callback deferred; its result is returned.
    fn publish<D: Dispatcher>(
        &self,
        core: &ComponentCore<D>,
        commit: CurrentCommit<T>,
    ) -> VmxResult<()> {
        let CurrentCommit {
            value,
            previous,
            publish_previous,
            publish_value,
            lease,
        } = commit;
        if publish_previous {
            if let Some(previous) = &previous {
                previous.publish_current_flag(false);
            }
        }
        if publish_value {
            if let Some(value) = &value {
                value.publish_current_flag(true);
            }
        }
        core.notify_property_changed("current");
        // Clone in a `let` so the guard drops before the call: the callback may
        // replace itself or change the selection (#716).
        let callback = lock(&self.on_current_changed).clone();
        if let Some(callback) = callback {
            callback(value);
        }
        drop(previous);
        lease.finish()
    }

    /// The construct walk's `Current(selector)` assignment (spec/06 §3.2,
    /// ADR-0165). It is a silent no-op while disposal is pending, inside this
    /// thread's own uncommitted transaction, and for a value that is not a
    /// committed member.
    fn assign_selector_result<D: Dispatcher>(
        &self,
        core: &ComponentCore<D>,
        selected: &T,
    ) -> VmxResult<()> {
        let commit = {
            let _gate = lock(&self.gate);
            if self.disposal_pending()
                || self.in_own_uncommitted_transaction()
                || !self.is_selectable_member_locked(selected)
            {
                None
            } else {
                self.commit_locked(Some(selected.clone()))
            }
        };
        commit.map_or(Ok(()), |commit| self.publish(core, commit))
    }

    /// The destruct clear (spec/06 §5): no refusal, no wait, no skip.
    fn clear_for_destruct<D: Dispatcher>(&self, core: &ComponentCore<D>) -> VmxResult<()> {
        let commit = {
            let _gate = lock(&self.gate);
            self.commit_locked(None)
        };
        commit.map_or(Ok(()), |commit| self.publish(core, commit))
    }

    /// A selection call: the setter, `select_component`,
    /// `deselect_component`, and the child `select` and `deselect` paths
    /// (spec/06 §4.3). With async selection it validates now, and the
    /// delivery validates again and drops silently when no longer valid.
    /// While the composite is `Destructing`, a non-null selection that
    /// passes validation returns `Ok(())` and changes nothing; an async call
    /// schedules nothing (rule 8, ADR-0188).
    fn request<D: Dispatcher>(
        &self,
        core: &ComponentCore<D>,
        next: Option<T>,
        require_constructed: bool,
        expected_current_id: Option<usize>,
    ) -> VmxResult<()> {
        if core.status() == ConstructionStatus::Disposed {
            return Err(VmxError::Disposed);
        }
        if *lock(&self.async_selection) {
            {
                let _gate = lock(&self.gate);
                self.validate_locked(next.as_ref(), require_constructed, expected_current_id)?;
                if Self::destructing_refuses_locked(core, next.as_ref()) {
                    return Ok(());
                }
            }
            let selection = self.clone();
            let delivery_core = core.clone();
            core.dispatch(Box::new(move || {
                // A container disposed before the queued selection ran stays
                // inert (disposal contract).
                if delivery_core.status() == ConstructionStatus::Disposed {
                    return;
                }
                let commit = {
                    let _gate = lock(&selection.gate);
                    selection
                        .validate_locked(next.as_ref(), require_constructed, expected_current_id)
                        .ok()
                        .filter(|()| {
                            !Self::destructing_refuses_locked(&delivery_core, next.as_ref())
                        })
                        .and_then(|()| selection.commit_locked(next.clone()))
                };
                if let Some(commit) = commit {
                    let _ = selection.publish(&delivery_core, commit);
                }
            }));
            return Ok(());
        }
        let commit = {
            let _gate = lock(&self.gate);
            self.validate_locked(next.as_ref(), require_constructed, expected_current_id)?;
            if Self::destructing_refuses_locked(core, next.as_ref()) {
                return Ok(());
            }
            self.commit_locked(next)
        };
        commit.map_or(Ok(()), |commit| self.publish(core, commit))
    }
}

/// What a composite construct needs besides its core. None of it holds the
/// core, so a construct deferred behind a destruct, or a selector step queued
/// behind a background child, cannot keep the composite alive (#750).
struct CompositeConstruct<T: VmNode> {
    late: LateStarts,
    selector: Arc<Mutex<Option<CurrentSelector<T>>>>,
    selection: CompositeSelection<T>,
}

impl<T: VmNode> CompositeConstruct<T> {
    /// Constructs the composite on `core`: runs `populate` inside the
    /// admitted transition, after the construct hook, then constructs each
    /// child, then runs the selector once every child settled (spec/02 §6,
    /// spec/06 §1).
    fn run<D: Dispatcher>(
        self,
        core: &ComponentCore<D>,
        populate: impl FnOnce() -> VmxResult<()>,
    ) -> VmxResult<()> {
        core.transition_with(LifecycleOperation::Construct, || {
            populate()?;
            let members = self.selection.items.clone();
            let late = self.late.clone();
            core.construct_children(
                Arc::new(move || members.to_vec()),
                late,
                Box::new(move |core| {
                    // Clone in a `let` so the guard drops before the
                    // selector and the selection callbacks run (#716).
                    let selector = lock(&self.selector).clone();
                    if let Some(selector) = selector {
                        if let Some(selected) = selector(self.selection.items.to_vec()) {
                            return self.selection.assign_selector_result(core, &selected);
                        }
                    }
                    Ok(())
                }),
            )
        })
    }
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
    ///
    /// Returns [`VmxError::OwnershipTransactionInProgress`] and changes
    /// nothing while a membership transaction is open (ADR-0187).
    fn clear(&self) -> VmxResult<()>;
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
    commands: Arc<ComponentCommands>,
    items: ObservableList<T>,
    ownership: ParentRegistration,
    current: Arc<Mutex<Option<T>>>,
    auto_construct_on_add: Arc<Mutex<bool>>,
    /// The fixed order of the destruct and dispose walks (ADR-0161).
    destruct_order: ChildOrder,
    /// Decides who starts a child an auto-construct add attaches.
    late_starts: LateStarts,
    async_selection: Arc<Mutex<bool>>,
    current_selector: Arc<Mutex<Option<CurrentSelector<T>>>>,
    on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>>,
    dispose_requested: Arc<AtomicBool>,
    membership_gate: Arc<Mutex<()>>,
    membership_transaction_active: Arc<AtomicBool>,
    membership_transaction_control: Arc<MembershipTransactionControl>,
    /// The shared selection state (spec/06 §4.3).
    selection: CompositeSelection<T>,
    /// The builder's children factory until its first construct attaches
    /// the population (spec/06 §1, ADR-0204).
    population: Arc<Mutex<Option<ChildrenFactory<T>>>>,
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
        Self::with_destruct_order(name, hub, dispatcher, ChildOrder::Insertion)
    }

    /// Creates an empty composite with explicit services whose destruct and
    /// dispose walks use `destruct_order` (ADR-0161). The order is fixed for
    /// the composite's lifetime; [`Self::with_services`] uses
    /// [`ChildOrder::Insertion`].
    pub fn with_destruct_order(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        destruct_order: ChildOrder,
    ) -> Self {
        let core = ComponentCore::new(name, hub.clone(), dispatcher);
        let items: ObservableList<T> = ObservableList::with_owner_name(core.id(), core.name(), hub);
        let current = Arc::new(Mutex::new(None));
        let async_selection = Arc::new(Mutex::new(false));
        let current_selector: Arc<Mutex<Option<CurrentSelector<T>>>> = Arc::new(Mutex::new(None));
        let on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>> =
            Arc::new(Mutex::new(None));
        let dispose_requested = Arc::new(AtomicBool::new(false));
        let membership_gate = Arc::new(Mutex::new(()));
        let membership_transaction_active = Arc::new(AtomicBool::new(false));
        let membership_transaction_control = Arc::new(MembershipTransactionControl::new());
        let selection = CompositeSelection {
            items: items.clone(),
            current: Arc::clone(&current),
            on_current_changed: Arc::clone(&on_current_changed),
            async_selection: Arc::clone(&async_selection),
            gate: Arc::clone(&membership_gate),
            dispose_requested: Arc::clone(&dispose_requested),
            control: Arc::clone(&membership_transaction_control),
            uncommitted: Arc::new(Mutex::new(UncommittedMembership::default())),
        };
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
                let selection = selection.clone();
                let detach_gate = Arc::clone(&membership_gate);
                let detach_disposed = Arc::clone(&dispose_requested);
                let detach_transaction = Arc::clone(&membership_transaction_active);
                let detach_control = Arc::clone(&membership_transaction_control);
                move |child_id, owner_handle| {
                    let transaction =
                        begin_membership_transaction(&detach_transaction, &detach_control)?;
                    let _gate = lock(&detach_gate);
                    if detach_disposed.load(Ordering::Acquire) || detach_control.disposal_deferred()
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
                    // The detach stays uncommitted until the commit or the
                    // rollback runs (spec/06 §4.3 rule 4).
                    lock(&selection.uncommitted).begin_detach();
                    let commit_items = items.clone();
                    let commit_selection = selection.clone();
                    let commit_core = core.clone();
                    let commit_removed = removed.clone();
                    let rollback_items = items.clone();
                    let rollback_selection = selection.clone();
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
                            // Clear `current` only while the moved child is
                            // still current: a selection made after the
                            // detach stays (spec/06 §4.3 rule 6).
                            let cleared = {
                                let _gate = lock(&commit_selection.gate);
                                lock(&commit_selection.uncommitted).end_detach();
                                commit_selection.clear_if_current_locked(&commit_removed)
                            };
                            let Some(cleared) = cleared else {
                                commit_items.publish_remove(index);
                                return transaction.finish();
                            };
                            let published = catch_unwind(AssertUnwindSafe(|| {
                                commit_selection.publish(&commit_core, cleared)
                            }));
                            commit_items.publish_remove(index);
                            let result = transaction.finish();
                            match published {
                                Ok(published) => published.and(result),
                                Err(payload) => resume_unwind(payload),
                            }
                        },
                        move || {
                            let transaction = MembershipTransactionGuard::release_on_drop(
                                rollback_transaction,
                                rollback_control,
                            );
                            let _gate = lock(&rollback_gate);
                            lock(&rollback_selection.uncommitted).end_detach();
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
                let selection = selection.clone();
                move |child_id| {
                    let item = items
                        .to_vec()
                        .into_iter()
                        .find(|item| item.id() == child_id)
                        .ok_or(VmxError::NonChild)?;
                    selection.request(&core, Some(item), true, None)
                }
            },
            {
                let core = core.clone();
                let selection = selection.clone();
                move |child_id| selection.request(&core, None, false, Some(child_id))
            },
            {
                let core = core.clone();
                let selection = selection.clone();
                move |child_id| selection.clear_for_disposed_child(&core, child_id)
            },
        );
        let auto_construct_on_add = Arc::new(Mutex::new(false));
        let late_starts = LateStarts::new(Arc::clone(&membership_gate));
        let population = Arc::new(Mutex::new(None));
        // The command runs the full `reconstruct()` (spec/05 §5), so a fix to
        // the walk lands in one place. The command table and the ownership
        // registration are held weakly, so the stored command can keep
        // neither its container alive nor that container registered as its
        // children's parent. Its predicate checks the same handles, so a
        // command that outlives its container is disabled (#1483).
        let commands = Arc::new_cyclic(|table| {
            let table = table.clone();
            let command_core = core.clone();
            let items = items.clone();
            let ownership = ownership.handle();
            let alive = {
                let table = table.clone();
                let ownership = ownership.clone();
                move || table.strong_count() > 0 && ownership.is_alive()
            };
            let population = Arc::clone(&population);
            let current = Arc::clone(&current);
            let auto_construct_on_add = Arc::clone(&auto_construct_on_add);
            let late_starts = late_starts.clone();
            let async_selection = Arc::clone(&async_selection);
            let current_selector = Arc::clone(&current_selector);
            let on_current_changed = Arc::clone(&on_current_changed);
            let dispose_requested = Arc::clone(&dispose_requested);
            let membership_gate = Arc::clone(&membership_gate);
            let membership_transaction_active = Arc::clone(&membership_transaction_active);
            let membership_transaction_control = Arc::clone(&membership_transaction_control);
            let selection = selection.clone();
            ComponentCommands::with_liveness(&core, alive, move || {
                let (Some(commands), Some(ownership)) = (table.upgrade(), ownership.registration())
                else {
                    return;
                };
                let composite = Self {
                    core: command_core.clone(),
                    commands,
                    items: items.clone(),
                    ownership,
                    current: Arc::clone(&current),
                    auto_construct_on_add: Arc::clone(&auto_construct_on_add),
                    destruct_order,
                    late_starts: late_starts.clone(),
                    async_selection: Arc::clone(&async_selection),
                    current_selector: Arc::clone(&current_selector),
                    on_current_changed: Arc::clone(&on_current_changed),
                    dispose_requested: Arc::clone(&dispose_requested),
                    membership_gate: Arc::clone(&membership_gate),
                    membership_transaction_active: Arc::clone(&membership_transaction_active),
                    membership_transaction_control: Arc::clone(&membership_transaction_control),
                    selection: selection.clone(),
                    population: Arc::clone(&population),
                };
                let _ = composite.reconstruct();
            })
        });
        Self {
            core,
            commands,
            items,
            ownership,
            current,
            auto_construct_on_add,
            destruct_order,
            late_starts,
            async_selection,
            current_selector,
            on_current_changed,
            dispose_requested,
            membership_gate,
            membership_transaction_active,
            membership_transaction_control,
            selection,
            population,
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

    /// Returns the canonical composite family discriminator.
    pub fn view_model_type(&self) -> ViewModelType {
        ViewModelType::Composite
    }

    /// Returns the immutable presentation hint.
    pub fn hint(&self) -> String {
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

    /// Returns the hot error stream for this container's deferred lifecycle
    /// failures. It carries every child failure that rolls the container back
    /// once its walk waits on a child still in flight (a background child, or
    /// one another thread is transitioning), whether the failure settles
    /// before or after `construct`/`destruct` returns. It also carries the
    /// container's own construct failure in a deferred reconstruct. A walk
    /// that never waits returns its failure to the caller as an `Err`.
    pub fn background_errors(&self) -> crate::LifecycleErrorStream {
        self.core.background_errors()
    }

    /// Registers cleanup work that runs on disposal.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.core.own(cleanup);
    }

    /// Registers `member` for depth-first disposal (spec/02 §7.1, ADR-0162).
    ///
    /// `dispose()` disposes this composite's children first and then the
    /// registered members in registration order, all before the composite
    /// publishes `Disposed` (ADR-0179). When a construct or destruct hook of
    /// the composite runs on another thread, the composite publishes `Disposed`
    /// first and disposes its children and then its members after that hook
    /// returns (spec/02 §2.4, LIFE-015). A member is not a child: registration
    /// sets no parent link, adds no selection state, and does not construct
    /// it. Clones of the composite share the registrations, and the composite
    /// keeps a clone of `member` until it is disposed, so a member must not
    /// hold the composite (#750).
    ///
    /// A member registered once the composite's disposal began is disposed now,
    /// and its disposal result is returned. Registering a member twice keeps
    /// one registration.
    ///
    /// # Errors
    ///
    /// [`VmxError::OwnershipCycle`] when `member` is this composite (the same
    /// identity); the error of disposing a late member.
    pub fn own_member<N: VmNode>(&self, member: &N) -> VmxResult<()> {
        let member = member.clone();
        self.core
            .own_member(member.id(), Box::new(move || member.dispose()))
    }

    /// Publishes a change for an application-defined property.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Replaces the hook invoked during composite construction.
    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Construct, Arc::new(Mutex::new(hook)));
    }

    /// Replaces the hook invoked during composite destruction.
    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Destruct, Arc::new(Mutex::new(hook)));
    }

    /// Replaces the hook invoked during composite disposal.
    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Dispose, Arc::new(Mutex::new(hook)));
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
        let original_status = item.status();
        let mut late_start;
        let mut staged = self.selection.staging();
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
            // Attached but not admitted: not a member for selection yet
            // (spec/06 §4.3 rule 2).
            staged.stage(item.id());
            late_start = self.attach_start(&item);
            index
        };
        let admission = self
            .auto_construct_attached(late_start.as_mut(), &item)
            .and_then(|()| {
                if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                    Err(VmxError::Disposed)
                } else {
                    Ok(())
                }
            });
        if let Err(error) = admission {
            let _gate = lock(&self.membership_gate);
            if let Some(start) = late_start.as_mut() {
                start.forget();
            }
            if let Some(index) = self
                .items()
                .iter()
                .position(|child| child.id() == item.id())
            {
                let _ = self.items.remove_at_silent(index);
            }
            staged.admit();
            if item
                .parent_handle()
                .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
            {
                item.set_parent_handle(None);
            }
            // Destruct after releasing the gate: its messages can reach a
            // subscriber that disposes this container (#1066).
            drop(_gate);
            let compensation_error = compensate_auto_start(&item, original_status);
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            // The start attempt ends after the transaction, so a walk waiting
            // on it resumes outside it (ADR-0218 rule 4).
            drop(transaction);
            drop(late_start);
            return Err(rollback_error(error, compensation_error));
        }
        let mut commit_error = None;
        let mut commit_panic = None;
        if let Some(transfer) = transfer {
            retain_parent_transfer_commit(&mut commit_error, &mut commit_panic, transfer);
        }
        // Admitted: selectable from here on, also by a `CollectionChanged`
        // subscriber on this thread (spec/06 §4.3 rules 2 and 4).
        {
            let _gate = lock(&self.membership_gate);
            staged.admit();
        }
        self.items.publish_add(index);
        retain_first_error(&mut commit_error, transaction.finish());
        // The start attempt ends after the transaction (ADR-0218 rule 4).
        drop(late_start);
        if let Some(payload) = commit_panic {
            resume_unwind(payload);
        }
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
        let mut staged = self.selection.staging();
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
                    // A staged population is not selectable until it commits
                    // (spec/06 §4.3 rule 2).
                    staged.stage(child.id());
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
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                return Err(VmxError::Disposed);
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
            staged.admit();
            drop(_gate);
            for (child, original_status) in candidates
                .iter()
                .zip(&original_statuses)
                .take(transfers.len())
                .rev()
            {
                // Detached first, so a deferred compensation finds no parent
                // (ADR-0218 rule 7).
                if child
                    .parent_handle()
                    .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
                {
                    child.set_parent_handle(None);
                }
                if let Some(error) = compensate_auto_start(child, *original_status) {
                    compensation_error.get_or_insert(error);
                }
            }
            for transfer in transfers.into_iter().rev().flatten() {
                let _ = transfer.rollback();
            }
            return Err(rollback_error(error, compensation_error));
        }

        let mut commit_error = None;
        let mut commit_panic = None;
        for transfer in transfers.into_iter().flatten() {
            retain_parent_transfer_commit(&mut commit_error, &mut commit_panic, transfer);
        }
        {
            let _gate = lock(&self.membership_gate);
            staged.admit();
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
        if let Some(payload) = commit_panic {
            resume_unwind(payload);
        }
        finish_with_first_error(commit_error)
    }

    /// Inserts a child at `index` with atomic ownership transfer.
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let original_status = item.status();
        let mut late_start;
        let mut staged = self.selection.staging();
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
            staged.stage(item.id());
            late_start = self.attach_start(&item);
        }
        let admission = self
            .auto_construct_attached(late_start.as_mut(), &item)
            .and_then(|()| {
                if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                    Err(VmxError::Disposed)
                } else {
                    Ok(())
                }
            });
        if let Err(error) = admission {
            let _gate = lock(&self.membership_gate);
            if let Some(start) = late_start.as_mut() {
                start.forget();
            }
            if let Some(position) = self
                .items()
                .iter()
                .position(|child| child.id() == item.id())
            {
                let _ = self.items.remove_at_silent(position);
            }
            staged.admit();
            if item
                .parent_handle()
                .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
            {
                item.set_parent_handle(None);
            }
            // Destruct after releasing the gate: its messages can reach a
            // subscriber that disposes this container (#1066).
            drop(_gate);
            let compensation_error = compensate_auto_start(&item, original_status);
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            // The start attempt ends after the transaction, so a walk waiting
            // on it resumes outside it (ADR-0218 rule 4).
            drop(transaction);
            drop(late_start);
            return Err(rollback_error(error, compensation_error));
        }
        let mut commit_error = None;
        let mut commit_panic = None;
        if let Some(transfer) = transfer {
            retain_parent_transfer_commit(&mut commit_error, &mut commit_panic, transfer);
        }
        // Admitted: selectable from here on, also by a `CollectionChanged`
        // subscriber on this thread (spec/06 §4.3 rules 2 and 4).
        {
            let _gate = lock(&self.membership_gate);
            staged.admit();
        }
        self.items.publish_add(index);
        retain_first_error(&mut commit_error, transaction.finish());
        // The start attempt ends after the transaction (ADR-0218 rule 4).
        drop(late_start);
        if let Some(payload) = commit_panic {
            resume_unwind(payload);
        }
        finish_with_first_error(commit_error)
    }

    /// Removes a child, clearing ownership and current selection if needed.
    pub fn remove(&self, item: &T) -> VmxResult<()> {
        self.reject_if_disposed()?;
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let removed = {
            let _gate = lock(&self.membership_gate);
            self.items()
                .iter()
                .position(|candidate| same_node(candidate, item))
                .map(|index| {
                    let removed = self.items.remove_at_silent(index).expect("index checked");
                    let cleared = self.selection.clear_if_current_locked(&removed);
                    (index, removed, cleared)
                })
        };
        let Some((index, removed, cleared)) = removed else {
            return transaction.finish();
        };
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        let published = self.publish_current(cleared);
        self.items.publish_remove(index);
        published.and(transaction.finish())
    }

    /// Removes and returns the child at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        self.reject_if_disposed()?;
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let (removed, cleared) = {
            let _gate = lock(&self.membership_gate);
            let removed = self
                .items
                .remove_at_silent(index)
                .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
            let cleared = self.selection.clear_if_current_locked(&removed);
            (removed, cleared)
        };
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        let published = self.publish_current(cleared);
        self.items.publish_remove(index);
        published.and(transaction.finish())?;
        Ok(removed)
    }

    /// Replaces and returns a child using atomic ownership transfer.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        let original_status = item.status();
        let mut late_start;
        let mut staged = self.selection.staging();
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
                Ok(old) => {
                    staged.stage(item.id());
                    late_start = self.attach_start(&item);
                    old
                }
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
        let admission = self
            .auto_construct_attached(late_start.as_mut(), &item)
            .and_then(|()| {
                if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                    Err(VmxError::Disposed)
                } else {
                    Ok(())
                }
            });
        if let Err(error) = admission {
            let _gate = lock(&self.membership_gate);
            if let Some(start) = late_start.as_mut() {
                start.forget();
            }
            if let Some(attached) = self
                .items()
                .iter()
                .position(|candidate| candidate.id() == item.id())
            {
                let _ = self.items.replace_silent(attached, old.clone());
                old.set_parent_handle(Some(self.ownership.handle()));
                item.set_parent_handle(None);
            }
            staged.admit();
            drop(_gate);
            let compensation_error = compensate_auto_start(&item, original_status);
            if let Some(transfer) = transfer {
                let _ = transfer.rollback();
            }
            // The start attempt ends after the transaction, so a walk waiting
            // on it resumes outside it (ADR-0218 rule 4).
            drop(transaction);
            drop(late_start);
            return Err(rollback_error(error, compensation_error));
        }
        let mut commit_error = None;
        let mut commit_panic = None;
        if let Some(transfer) = transfer {
            retain_parent_transfer_commit(&mut commit_error, &mut commit_panic, transfer);
        }
        let cleared = {
            let _gate = lock(&self.membership_gate);
            staged.admit();
            self.selection.clear_if_current_locked(&old)
        };
        // Free `old` only after the clear, as `remove_at` does: a container
        // that adopts it can then select it without this clear resetting its
        // flag (COMP-006, #1219).
        if old
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            old.set_parent_handle(None);
        }
        retain_first_error(&mut commit_error, self.publish_current(cleared));
        self.items.publish_replace(index);
        retain_first_error(&mut commit_error, transaction.finish());
        // The start attempt ends after the transaction (ADR-0218 rule 4).
        drop(late_start);
        if let Some(payload) = commit_panic {
            resume_unwind(payload);
        }
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
            if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
                return Err(VmxError::Disposed);
            }
            self.items.move_item_silent(from_index, to_index)?
        };
        if changed {
            self.items.publish_move(from_index, to_index);
        }
        transaction.finish()
    }

    /// Clears all children, ownership links, and current selection.
    ///
    /// Returns [`VmxError::Disposed`] after disposal. Returns
    /// [`VmxError::OwnershipTransactionInProgress`] at once, and changes
    /// nothing, while a membership transaction of this composite is open on
    /// any thread (spec/06 §4.2, ADR-0187).
    pub fn clear(&self) -> VmxResult<()> {
        self.reject_if_disposed()?;
        let transaction = begin_membership_transaction(
            &self.membership_transaction_active,
            &self.membership_transaction_control,
        )?;
        let (removed, cleared) = {
            let _gate = lock(&self.membership_gate);
            for item in self.items() {
                if item
                    .parent_handle()
                    .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
                {
                    item.set_parent_handle(None);
                }
            }
            let removed = self.items.take_silent();
            let current = lock(&self.current).clone();
            let cleared = current
                .filter(|current| removed.iter().any(|item| same_node(item, current)))
                .and_then(|current| self.selection.clear_if_current_locked(&current));
            (removed, cleared)
        };
        // `is_current` is published after the membership gate is released: a
        // subscriber may dispose this composite, which takes the gate (#749).
        // The detach clear committed the previous current child's flag under
        // the gate, as in the other flavors. No removed child's flag is
        // written after the gate: another composite may already have adopted
        // and selected it (spec/06 §4.3 rule 2).
        let published = self.publish_current(cleared);
        // Removed children are dropped after the membership gate is released.
        let changed = !removed.is_empty();
        drop(removed);
        if changed {
            self.items.publish_reset();
        }
        published.and(transaction.finish())
    }

    /// Returns the current child, if selected.
    pub fn current(&self) -> Option<T> {
        lock(&self.current).clone()
    }

    /// Assigns a child as current or clears selection.
    ///
    /// Returns [`VmxError::NonChild`] for values outside this composite.
    ///
    /// The call opens no membership transaction, so another thread's add or
    /// removal never fails or delays it (spec/06 §4.3). It returns
    /// [`VmxError::NonChild`] for a value this composite has not admitted or
    /// that is `Disposed`, [`VmxError::Disposed`] for a value while disposal
    /// is pending or after disposal, and
    /// [`VmxError::OwnershipTransactionInProgress`] on the thread whose own
    /// add, population or transfer of this composite has not committed yet.
    /// Clearing with `None` is legal while disposal is pending. While the
    /// composite is `Destructing`, a value that passes these checks returns
    /// `Ok(())` and changes nothing (spec/06 §4.3 rule 8, ADR-0188).
    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        self.selection.request(&self.core, item, false, None)
    }

    /// Selects a constructed child. Refusals follow [`Self::set_current`].
    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        self.selection
            .request(&self.core, Some(item.clone()), true, None)
    }

    /// Deselects `item`, rejecting values that are not current. Refusals
    /// follow [`Self::set_current`] for `None`.
    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        self.selection
            .request(&self.core, None, false, Some(item.id()))
    }

    /// Reports whether [`Self::select_component`] would succeed now: `item` is
    /// an admitted, constructed child, no disposal is pending, the composite
    /// is not `Destructing`, and this thread is not inside its own
    /// uncommitted membership transaction of the composite (spec/06 §3.1).
    pub fn can_select_component(&self, item: &T) -> bool {
        !matches!(
            self.status(),
            ConstructionStatus::Disposed | ConstructionStatus::Destructing
        ) && self.selection.can_select(item)
    }

    /// Registers this add's start record for `item` in the current construct
    /// walk's scope, under the membership gate that attaches it, when the add
    /// will auto-start the child: auto-construct-on-add is on and the
    /// container is Constructing (spec/06 §5.1). Otherwise drops any record
    /// for `item` from that scope.
    fn attach_start(&self, item: &T) -> Option<StartAttempt> {
        let will_start =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructing;
        self.late_starts.attach(item.id(), will_start)
    }

    /// The add's auto-construct of `item`. With a start record, it constructs
    /// a Destructed child; the add marks the record done after it ends its
    /// membership transaction, which lets a construct walk waiting on it join
    /// the child (ADR-0218 rule 4). Without one, it constructs only for a
    /// Constructed container.
    fn auto_construct_attached(&self, start: Option<&mut StartAttempt>, item: &T) -> VmxResult<()> {
        if let Some(start) = start {
            return start.run(&self.core, item);
        }
        let enabled = *lock(&self.auto_construct_on_add);
        if self.core.auto_constructs_when_constructed(enabled) {
            item.construct()
        } else {
            Ok(())
        }
    }

    /// Test-only seam: runs `probe` after each construct walk's commit step
    /// wrote `Constructed` and before the composite publishes it. Production
    /// code never calls it. Only the non-default `test-seams` feature
    /// exports it.
    #[cfg(feature = "test-seams")]
    #[doc(hidden)]
    pub fn set_seal_probe_for_testing<F>(&self, probe: F)
    where
        F: Fn() + Send + Sync + 'static,
    {
        self.late_starts.set_seal_probe(Arc::new(probe));
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
        replace_locked(&self.current_selector, Some(Arc::new(selector)));
    }

    /// Sets the callback invoked after effective current changes.
    pub fn on_current_changed<F>(&self, callback: F)
    where
        F: Fn(Option<T>) + Send + Sync + 'static,
    {
        replace_locked(&self.on_current_changed, Some(Arc::new(callback)));
    }

    /// Coalesces child-collection notifications produced by `action`.
    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        self.items.batch_update(action);
    }

    /// Constructs children before completing the composite transition.
    ///
    /// The first construct of a built composite calls the builder's children
    /// factory once, inside the construct transition and after the construct
    /// hook, and attaches its children before the construct walk (spec/06
    /// §1). A factory result that the population refuses, such as a
    /// duplicate child, fails this construct, which rolls back to
    /// Destructed. It attaches nothing and keeps the factory for the next
    /// construct. So does a factory that panics.
    pub fn construct(&self) -> VmxResult<()> {
        self.construct_parts().run(&self.core, || self.populate())
    }

    /// Attaches the children factory's result once (spec/06 §1, ADR-0204).
    /// It runs inside the admitted construct transition, so a concurrent or
    /// re-entrant construct fails with
    /// [`VmxError::InvalidLifecycleTransition`] from `Constructing` instead
    /// of running it again. The factory leaves its slot only when
    /// the population commits.
    fn populate(&self) -> VmxResult<()> {
        if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
            return Ok(());
        }
        let Some(factory) = lock(&self.population).clone() else {
            return Ok(());
        };
        let population = Arc::clone(&self.population);
        self.attach_population(factory(), false, move || *lock(&population) = None)
    }

    /// The parts a construct walk needs besides the core.
    fn construct_parts(&self) -> CompositeConstruct<T> {
        CompositeConstruct {
            late: self.late_starts.clone(),
            selector: Arc::clone(&self.current_selector),
            selection: self.selection.clone(),
        }
    }

    /// Clears selection and destructs all children, in collection order or,
    /// with [`ChildOrder::Reverse`], from the last child to the first.
    ///
    /// The clear opens no membership transaction and is never refused, so it
    /// also runs while another thread holds one, inside this composite's own
    /// transaction, and while disposal is deferred (spec/06 §5). A disposal
    /// that `on_current_changed(None)` requests is deferred until the clear's
    /// publication ends.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            let cleared = self.selection.clear_for_destruct(&self.core);
            for item in self.destruct_order.arrange(self.items()) {
                self.core
                    .transition_child(&item, LifecycleOperation::Destruct)?;
            }
            cleared
        })
    }

    /// Disposes all children and returns the first encountered error.
    ///
    /// Children are disposed in the composite's [`ChildOrder`], each before
    /// the composite publishes `Disposed`. When a construct or destruct hook of
    /// the composite runs on another thread, the composite publishes `Disposed`
    /// first. It disposes no child until that hook returns (LIFE-015). A
    /// second `dispose()` returns `Ok(())` at once.
    pub fn dispose(&self) -> VmxResult<()> {
        self.core.abandon_child_settle();
        let snapshot = loop {
            let _gate = lock(&self.membership_gate);
            match self.membership_transaction_control.dispose_disposition() {
                // A disposal from a selection's own publication returns at
                // once, before any wait (spec/06 §4.3 rule 5).
                MembershipDisposeDisposition::PublishingThread
                | MembershipDisposeDisposition::Owned => {
                    let deferred = self.clone();
                    self.membership_transaction_control
                        .defer_dispose(move || deferred.dispose());
                    // A disposing container sends no hub message (ADR-0190).
                    self.items.close_hub_publication();
                    return Ok(());
                }
                MembershipDisposeDisposition::Foreign => {
                    drop(_gate);
                    let deferred = self.clone();
                    if self
                        .membership_transaction_control
                        .wait_until_inactive_or_defer(move || deferred.dispose())
                        .is_none()
                    {
                        self.items.close_hub_publication();
                        return Ok(());
                    }
                    continue;
                }
                MembershipDisposeDisposition::Inactive => {
                    // Another thread is publishing a selection: its last
                    // lease runs the disposal (spec/06 §4.3 rule 5).
                    let deferred = self.clone();
                    if self
                        .membership_transaction_control
                        .defer_while_publishing(move || deferred.dispose())
                        .is_none()
                    {
                        self.items.close_hub_publication();
                        return Ok(());
                    }
                    break if self.dispose_requested.swap(true, Ordering::AcqRel) {
                        None
                    } else {
                        // A disposed container publishes nothing (ADR-0142).
                        self.items.close_publication();
                        Some(self.items())
                    };
                }
            }
        };
        let Some(snapshot) = snapshot else {
            return Ok(());
        };
        let children = self.destruct_order.arrange(snapshot);
        let commands = self.commands.clone();
        self.core.dispose_container_then(
            Box::new(move || {
                let mut first_failure = None;
                for item in children {
                    retain_first_failure(&mut first_failure, || item.dispose());
                }
                first_failure
            }),
            move || commands.dispose(),
        )
    }

    /// Returns a reader of the current children that does not keep the
    /// composite alive (ADR-0208).
    pub(crate) fn children_reader(&self) -> impl Fn() -> Vec<T> + Send + Sync + 'static {
        self.items.reader()
    }

    /// Returns the local collection-change stream of the children.
    ///
    /// Each effective mutation sends one `CollectionChangedMessage` here
    /// first, then the equivalent message to [`hub`](Self::hub) (spec/06 §4,
    /// ADR-0208). A hub batch never defers this stream. A list batch sends one
    /// `Reset` when it completes. After disposal the composite sends nothing.
    pub fn collection_changed(&self) -> MessageHub {
        self.items.local_changes()
    }

    /// Rejects a membership or selection change after disposal, as `add`,
    /// `insert`, `replace`, and `move_item` do (disposal contract).
    fn reject_if_disposed(&self) -> VmxResult<()> {
        if self.disposal_pending() || self.status() == ConstructionStatus::Disposed {
            Err(VmxError::Disposed)
        } else {
            Ok(())
        }
    }

    fn disposal_pending(&self) -> bool {
        self.selection.disposal_pending()
    }

    /// Returns the current lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }

    /// Destructs and then constructs the composite.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.core.admit_reconstruct()?;
        self.destruct()?;
        // The deferred construct holds only the parts it needs, never the
        // composite's core or commands, so it cannot keep the composite
        // alive (#750). Only a Constructed composite reconstructs, so its
        // population is already attached and the construct skips it.
        let parts = self.construct_parts();
        self.core
            .construct_after_destruct(move |core| parts.run(core, || Ok(())))
    }

    /// Reports whether the composite is constructed.
    pub fn is_constructed(&self) -> bool {
        self.status() == ConstructionStatus::Constructed
    }

    /// Returns the current parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    /// Reports whether this composite can select itself through its parent.
    pub fn can_select(&self) -> bool {
        self.core.can_select()
    }

    /// Selects this composite through its owning selectable parent.
    pub fn select(&self) {
        self.core.select_via_parent();
    }

    /// Reports whether this composite can deselect itself through its parent.
    pub fn can_deselect(&self) -> bool {
        self.core.can_deselect()
    }

    /// Deselects this composite through its owning selectable parent.
    pub fn deselect(&self) {
        self.core.deselect_via_parent();
    }

    /// Reports whether this composite is current in its parent.
    pub fn is_current(&self) -> bool {
        self.core.is_selected()
    }

    /// Marks the composite as expanded.
    pub fn expand(&self) {
        self.core.set_expanded(true);
    }

    /// Marks the composite as collapsed.
    pub fn collapse(&self) {
        self.core.set_expanded(false);
    }

    /// Toggles the composite's expanded state.
    pub fn toggle_expansion(&self) {
        self.core.set_expanded(!self.core.is_expanded());
    }

    /// Reports whether the composite is expanded.
    pub fn is_expanded(&self) -> bool {
        self.core.is_expanded()
    }

    /// Returns the stable command that selects this composite through its parent.
    pub fn select_command(&self) -> RelayCommand {
        self.commands.select()
    }

    /// Returns the stable command that deselects this composite through its parent.
    pub fn deselect_command(&self) -> RelayCommand {
        self.commands.deselect()
    }

    /// Returns the inert baseline next-sibling command.
    pub fn select_next_command(&self) -> RelayCommand {
        self.commands.select_next()
    }

    /// Returns the inert baseline previous-sibling command.
    pub fn select_previous_command(&self) -> RelayCommand {
        self.commands.select_previous()
    }

    /// Returns the stable command that reconstructs this composite and its children.
    pub fn reconstruct_command(&self) -> RelayCommand {
        self.commands.reconstruct()
    }

    /// Publishes a committed `current` change, if there is one.
    fn publish_current(&self, commit: Option<CurrentCommit<T>>) -> VmxResult<()> {
        commit.map_or(Ok(()), |commit| self.selection.publish(&self.core, commit))
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
    fn clear(&self) -> VmxResult<()> {
        CompositeVm::clear(self)
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

    fn commit_current_flag(&self, is_current: bool) -> bool {
        self.core.commit_current_flag(is_current)
    }

    fn publish_current_flag(&self, _is_current: bool) {
        self.core.publish_current_flag();
    }

    fn when_lifecycle_settled(&self, callback: crate::LifecycleSettleCallback) -> bool {
        self.core.when_settled(callback)
    }

    fn background_failure_stream(&self) -> Option<crate::LifecycleErrorStream> {
        Some(self.core.background_errors())
    }

    fn lifecycle_publication_pending(&self) -> bool {
        self.core.publication_pending()
    }

    fn is_current(&self) -> bool {
        self.core.is_selected()
    }
}

impl<T: TreeNode, D: Dispatcher> TreeNode for CompositeVm<T, D> {
    /// Returns the children in order (spec/13 §2).
    fn try_children_nodes(&self) -> VmxResult<Vec<TreeNodeRef>> {
        Ok(self.items().into_iter().map(TreeNodeRef::new).collect())
    }
}

impl<T: TreeNode, D: Dispatcher> CompositeVm<T, D> {
    /// Returns children as tree nodes.
    pub fn child_nodes(&self) -> Vec<T> {
        self.items()
    }

    /// Reports the composite's own expansion flag.
    ///
    /// [`walk_expanded`](crate::walk_expanded) does not read this flag. It
    /// reads [`TreeNode::expandable`], which a composite leaves at `None`.
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
    /// Retain the current item only while it remains visible.
    PreserveIfVisible,
}

#[derive(Clone)]
/// A filtered or scored projection over a source [`CompositeVm`].
///
/// Predicate projections preserve source order. Scored projections order by
/// descending score with stable source-order ties. Disposal freezes a snapshot.
///
/// The projection subscribes to the source's membership changes. Each source
/// mutation, predicate change, [`refresh`](Self::refresh) and
/// [`refresh_scores`](Self::refresh_scores) reconciles the current item under
/// the cursor policy and then sends one [`changed`](Self::changed)
/// notification. A [`set_current`](Self::set_current) or move that changes
/// the current item also sends one (spec/06 §9, ADR-0207).
///
/// ```
/// use std::sync::{Arc, Mutex};
/// use vmx::{
///     ComponentVm, CompositeVm, FilteredCompositeVm, FilteredCursorPolicy, MessageHub,
///     NullDispatcher,
/// };
///
/// let item = |value: i32| ComponentVm::with_model("item", value, MessageHub::new(), NullDispatcher::new());
/// let source = CompositeVm::new("source");
/// for value in [1, 2, 3] {
///     source.add(item(value)).unwrap();
/// }
/// let view = FilteredCompositeVm::with_cursor_policy(
///     source.clone(),
///     |item: &ComponentVm<i32>| item.model() % 2 == 1,
///     FilteredCursorPolicy::Clear,
/// );
/// assert!(view.current().is_none());
///
/// let changes = Arc::new(Mutex::new(0));
/// let sink = Arc::clone(&changes);
/// let _subscription = view.changed().subscribe(move |()| *sink.lock().unwrap() += 1);
/// source.add(item(5)).unwrap();
/// assert_eq!(*changes.lock().unwrap(), 1);
/// assert_eq!(view.visible_count(), 3);
/// ```
pub struct FilteredCompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    inner: Arc<FilteredInner<T, D>>,
}

struct FilteredInner<T: VmNode, D: Dispatcher> {
    source: CompositeVm<T, D>,
    predicate: Mutex<FilterPredicate<T>>,
    scorer: Mutex<Option<ScorePredicate<T>>>,
    current: Mutex<Option<T>>,
    cursor_policy: Mutex<FilteredCursorPolicy>,
    disposed: Mutex<bool>,
    frozen: Mutex<Vec<T>>,
    /// Source membership seen at the last reconciliation.
    source_ids: Mutex<Vec<usize>>,
    changed: ValueStream<()>,
    /// The source membership subscription. Its handler holds only a weak
    /// reference to this state, so the source never keeps the view alive.
    source_subscription: Mutex<Option<Subscription>>,
}

impl<T: VmNode, D: Dispatcher> FilteredCompositeVm<T, D> {
    /// Returns the source composite's family discriminator.
    pub fn view_model_type(&self) -> ViewModelType {
        self.inner.source.view_model_type()
    }

    /// Creates a predicate-filtered projection with the
    /// [`SnapToFirst`](FilteredCursorPolicy::SnapToFirst) cursor policy.
    pub fn new<F>(source: CompositeVm<T, D>, predicate: F) -> Self
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        Self::with_cursor_policy(source, predicate, FilteredCursorPolicy::SnapToFirst)
    }

    /// Creates a predicate-filtered projection with `cursor_policy`.
    ///
    /// The policy also sets the start state: under
    /// [`SnapToFirst`](FilteredCursorPolicy::SnapToFirst) the view starts on
    /// the first visible item, and under the other policies it starts with no
    /// current item.
    pub fn with_cursor_policy<F>(
        source: CompositeVm<T, D>,
        predicate: F,
        cursor_policy: FilteredCursorPolicy,
    ) -> Self
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        Self::create(source, Arc::new(predicate), None, cursor_policy)
    }

    /// Returns the source composite's message hub.
    pub fn hub(&self) -> MessageHub {
        self.inner.source.hub()
    }

    /// Creates a projection that includes scored items in descending order,
    /// with the [`SnapToFirst`](FilteredCursorPolicy::SnapToFirst) cursor
    /// policy.
    pub fn scored<F>(source: CompositeVm<T, D>, scorer: F) -> Self
    where
        F: Fn(&T) -> Option<i32> + Send + Sync + 'static,
    {
        Self::scored_with_cursor_policy(source, scorer, FilteredCursorPolicy::SnapToFirst)
    }

    /// Creates a scored projection with `cursor_policy`, which also sets the
    /// start state as in [`with_cursor_policy`](Self::with_cursor_policy).
    pub fn scored_with_cursor_policy<F>(
        source: CompositeVm<T, D>,
        scorer: F,
        cursor_policy: FilteredCursorPolicy,
    ) -> Self
    where
        F: Fn(&T) -> Option<i32> + Send + Sync + 'static,
    {
        Self::create(
            source,
            Arc::new(|_| true),
            Some(Arc::new(scorer)),
            cursor_policy,
        )
    }

    fn create(
        source: CompositeVm<T, D>,
        predicate: FilterPredicate<T>,
        scorer: Option<ScorePredicate<T>>,
        cursor_policy: FilteredCursorPolicy,
    ) -> Self {
        let filtered = Self {
            inner: Arc::new(FilteredInner {
                source,
                predicate: Mutex::new(predicate),
                scorer: Mutex::new(scorer),
                current: Mutex::new(None),
                cursor_policy: Mutex::new(cursor_policy),
                disposed: Mutex::new(false),
                frozen: Mutex::new(Vec::new()),
                source_ids: Mutex::new(Vec::new()),
                changed: ValueStream::hot(()),
                source_subscription: Mutex::new(None),
            }),
        };
        filtered.reconcile_current();
        let state = Arc::downgrade(&filtered.inner);
        let owner_id = filtered.inner.source.id();
        let subscription = filtered
            .inner
            .source
            .collection_changed()
            .subscribe(move |message| {
                let membership = matches!(message, Message::CollectionChanged(change)
                    if change.sender_id == owner_id && change.property_name == "items");
                if !membership {
                    return;
                }
                if let Some(inner) = state.upgrade() {
                    Self { inner }.recompute();
                }
            });
        replace_locked(&filtered.inner.source_subscription, Some(subscription));
        filtered
    }

    /// Returns the hot change stream.
    ///
    /// It sends `()` once after each source membership change, predicate
    /// change, [`refresh`](Self::refresh) and
    /// [`refresh_scores`](Self::refresh_scores), and once for each
    /// [`set_current`](Self::set_current), [`move_next_visible`](Self::move_next_visible)
    /// or [`move_previous_visible`](Self::move_previous_visible) call that
    /// changes the current item. A subscriber reads the new state from
    /// [`visible`](Self::visible) and [`current`](Self::current).
    /// [`dispose`](Self::dispose) completes the stream.
    ///
    /// A notification caused by a source mutation runs inside that mutation,
    /// before the source hub's `CollectionChanged`. A subscriber that mutates
    /// the source membership there gets
    /// [`VmxError::OwnershipTransactionInProgress`].
    pub fn changed(&self) -> ValueStream<()> {
        self.inner.changed.clone()
    }

    /// Returns the current visible projection or the frozen disposed snapshot.
    pub fn visible(&self) -> Vec<T> {
        if *lock(&self.inner.disposed) {
            return lock(&self.inner.frozen).clone();
        }
        let predicate = lock(&self.inner.predicate).clone();
        let scorer = lock(&self.inner.scorer).clone();
        let mut indexed = self
            .inner
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
    ///
    /// A source membership change reconciles the selection under the cursor
    /// policy when the source publishes it (COMP-032, COMP-033). A read also
    /// reconciles a membership change that published nothing, such as one
    /// after the source's disposal closed its publication. An explicit clear
    /// stays cleared until the next source change, predicate change, or
    /// refresh.
    pub fn current(&self) -> Option<T> {
        self.reconcile_if_source_changed();
        lock(&self.inner.current).clone()
    }

    /// Applies a source membership change that no reconciliation has seen
    /// yet, so a later explicit assignment is not undone by it.
    fn reconcile_if_source_changed(&self) {
        if !*lock(&self.inner.disposed) && *lock(&self.inner.source_ids) != self.source_member_ids()
        {
            self.reconcile_current();
        }
    }

    fn source_member_ids(&self) -> Vec<usize> {
        self.inner.source.items().iter().map(VmNode::id).collect()
    }

    /// Assigns a visible current item or clears it.
    ///
    /// A change of the current item sends one [`changed`](Self::changed)
    /// notification; assigning the current item again sends none.
    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        // A disposed projection stays frozen (disposal contract, DISP-006).
        if *lock(&self.inner.disposed) {
            return Ok(());
        }
        self.reconcile_if_source_changed();
        if let Some(item) = item.as_ref() {
            if !self
                .visible()
                .iter()
                .any(|candidate| same_node(candidate, item))
            {
                return Err(VmxError::NonChild);
            }
        }
        self.assign_current(item);
        Ok(())
    }

    /// Replaces the predicate, reconciles current selection, and sends one
    /// [`changed`](Self::changed) notification.
    pub fn set_predicate<F>(&self, predicate: F)
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        if *lock(&self.inner.disposed) {
            return;
        }
        replace_locked(&self.inner.predicate, Arc::new(predicate));
        self.recompute();
    }

    /// Sets the policy for a current item hidden by filtering. The next
    /// reconciliation applies it.
    pub fn set_cursor_policy(&self, policy: FilteredCursorPolicy) {
        if *lock(&self.inner.disposed) {
            return;
        }
        *lock(&self.inner.cursor_policy) = policy;
    }

    /// Re-evaluates visibility, reconciles current selection, and sends one
    /// [`changed`](Self::changed) notification.
    pub fn refresh(&self) {
        self.recompute();
    }

    /// Re-evaluates scores, reconciles current selection, and sends one
    /// [`changed`](Self::changed) notification.
    pub fn refresh_scores(&self) {
        self.recompute();
    }

    /// Advances current within the visible projection, clamped at the end.
    pub fn move_next_visible(&self) {
        if *lock(&self.inner.disposed) {
            return;
        }
        let visible = self.visible();
        if visible.is_empty() {
            self.assign_current(None);
            return;
        }
        let next_index = self
            .current()
            .and_then(|current| visible.iter().position(|item| same_node(item, &current)))
            .map(|index| (index + 1).min(visible.len() - 1))
            .unwrap_or(0);
        self.assign_current(Some(visible[next_index].clone()));
    }

    /// Moves current backward within the visible projection.
    pub fn move_previous_visible(&self) {
        if *lock(&self.inner.disposed) {
            return;
        }
        let visible = self.visible();
        if visible.is_empty() {
            self.assign_current(None);
            return;
        }
        let previous_index = self
            .current()
            .and_then(|current| visible.iter().position(|item| same_node(item, &current)))
            .map(|index| index.saturating_sub(1))
            .unwrap_or(0);
        self.assign_current(Some(visible[previous_index].clone()));
    }

    /// Freezes the current visible projection for subsequent reads, releases
    /// the source subscription, and completes [`changed`](Self::changed).
    pub fn dispose(&self) {
        if *lock(&self.inner.disposed) {
            return;
        }
        // Apply a source change no reconciliation has seen yet, so the frozen
        // `current` is a member of the frozen `visible`.
        self.reconcile_if_source_changed();
        let visible = self.visible();
        let current_is_visible = lock(&self.inner.current)
            .as_ref()
            .is_none_or(|current| visible.iter().any(|item| same_node(item, current)));
        if !current_is_visible {
            // A predicate input changed without a source change; apply the
            // cursor policy so the frozen current item is still visible.
            self.reconcile_current();
        }
        replace_locked(&self.inner.frozen, self.visible());
        *lock(&self.inner.disposed) = true;
        let subscription = lock(&self.inner.source_subscription).take();
        drop(subscription);
        self.inner.changed.dispose();
    }

    /// Reconciles the current item and sends one change notification.
    fn recompute(&self) {
        if *lock(&self.inner.disposed) {
            return;
        }
        self.reconcile_current();
        self.inner.changed.send(());
    }

    /// Replaces the current item and sends one change notification when the
    /// item changes. The replaced item is dropped after the lock is released.
    fn assign_current(&self, next: Option<T>) {
        let previous = {
            let mut current = lock(&self.inner.current);
            if same_optional_node(current.as_ref(), next.as_ref()) {
                return;
            }
            std::mem::replace(&mut *current, next)
        };
        drop(previous);
        self.inner.changed.send(());
    }

    fn reconcile_current(&self) {
        replace_locked(&self.inner.source_ids, self.source_member_ids());
        let visible = self.visible();
        let current_is_visible = lock(&self.inner.current)
            .clone()
            .is_some_and(|current| visible.iter().any(|item| same_node(item, &current)));
        if current_is_visible {
            return;
        }
        let next = match *lock(&self.inner.cursor_policy) {
            FilteredCursorPolicy::Clear | FilteredCursorPolicy::PreserveIfVisible => None,
            FilteredCursorPolicy::SnapToFirst => visible.first().cloned(),
        };
        replace_locked(&self.inner.current, next);
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
    destruct_order: ChildOrder,
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
            destruct_order: ChildOrder::Insertion,
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

    /// Sets the order of the destruct and dispose walks (ADR-0161). The
    /// default is [`ChildOrder::Insertion`]; construct order is unchanged.
    pub fn destruct_order(mut self, order: ChildOrder) -> Self {
        self.destruct_order = order;
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

    /// Validates required fields and creates the composite.
    ///
    /// The built composite has no children. Its first `construct()` calls
    /// the children factory once and attaches the result (spec/06 §1,
    /// ADR-0204); a factory error such as a duplicate child comes from that
    /// `construct()`.
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
        let vm = CompositeVm::with_destruct_order(name, hub, dispatcher, self.destruct_order);
        if let Some(hint) = self.hint {
            vm.core.set_hint(hint);
        }
        vm.set_auto_construct_on_add(self.auto_construct_on_add);
        vm.set_async_selection(self.async_selection);
        if let Some(selector) = self.current_selector {
            vm.set_current_selector(move |items| selector(items));
        }
        *lock(&vm.population) = Some(children);
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
            .destruct_order(options.destruct_order)
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
    /// The order of the destruct and dispose walks; use
    /// [`ChildOrder::Insertion`] for the default.
    pub destruct_order: ChildOrder,
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
    /// Returns the modeled composite family discriminator.
    pub fn view_model_type(&self) -> ViewModelType {
        self.inner.view_model_type()
    }

    /// Returns the stable composite identity.
    pub fn id(&self) -> usize {
        self.inner.id()
    }

    /// Returns the immutable composite name.
    pub fn name(&self) -> String {
        self.inner.name()
    }

    /// Returns the immutable presentation hint.
    pub fn hint(&self) -> String {
        self.inner.hint()
    }

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

    /// Returns the local collection-change stream of the children (see
    /// [`CompositeVm::collection_changed`]).
    pub fn collection_changed(&self) -> MessageHub {
        self.inner.collection_changed()
    }

    /// Returns the hot error stream for this container's deferred lifecycle
    /// failures. It carries every child failure that rolls the container back
    /// once its walk waits on a child still in flight (a background child, or
    /// one another thread is transitioning), whether the failure settles
    /// before or after `construct`/`destruct` returns. It also carries the
    /// container's own construct failure in a deferred reconstruct. A walk
    /// that never waits returns its failure to the caller as an `Err`.
    pub fn background_errors(&self) -> crate::LifecycleErrorStream {
        self.inner.background_errors()
    }

    /// Registers cleanup work that runs on disposal.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.own(cleanup);
    }

    /// Replaces the hook invoked during construction, including the construct
    /// phase of `reconstruct` (spec/02 §2.2, ADR-0203). It runs as
    /// [`CompositeVm::on_construct`] does, after the children are
    /// materialized. The hook must not capture this composite (#750).
    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_construct(hook);
    }

    /// Replaces the hook invoked during destruction, including the destruct
    /// phase of `reconstruct` (spec/02 §2.2, ADR-0203). The hook must not
    /// capture this composite (#750).
    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_destruct(hook);
    }

    /// Replaces the hook invoked during disposal (spec/02 §2.2, ADR-0203).
    /// The hook must not capture this composite (#750).
    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_dispose(hook);
    }

    /// Registers `member` for depth-first disposal, as
    /// [`CompositeVm::own_member`] does.
    ///
    /// # Errors
    ///
    /// [`VmxError::OwnershipCycle`] when `member` is this composite (the same
    /// identity); the error of disposing a late member.
    pub fn own_member<N: VmNode>(&self, member: &N) -> VmxResult<()> {
        self.inner.own_member(member)
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

impl<M: Clone + PartialEq + Send + Sync + 'static, T: TreeNode, D: Dispatcher> TreeNode
    for ModeledCompositeVm<M, T, D>
{
    /// Returns the children in order (spec/13 §2).
    fn try_children_nodes(&self) -> VmxResult<Vec<TreeNodeRef>> {
        Ok(self.items().into_iter().map(TreeNodeRef::new).collect())
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

    fn commit_current_flag(&self, is_current: bool) -> bool {
        VmNode::commit_current_flag(&self.inner, is_current)
    }

    fn publish_current_flag(&self, is_current: bool) {
        VmNode::publish_current_flag(&self.inner, is_current);
    }

    fn when_lifecycle_settled(&self, callback: crate::LifecycleSettleCallback) -> bool {
        self.inner.core.when_settled(callback)
    }

    fn background_failure_stream(&self) -> Option<crate::LifecycleErrorStream> {
        Some(self.inner.core.background_errors())
    }

    fn lifecycle_publication_pending(&self) -> bool {
        self.inner.core.publication_pending()
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
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children_models: Option<ModelFactory<M>>,
    child_model_to_child_view_model: Option<ChildModelMapper<M, T>>,
    async_selection: bool,
    current_selector: Option<CurrentSelector<T>>,
    destruct_order: ChildOrder,
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> Default
    for ModeledCompositeVmBuilder<M, T, D>
{
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            children_models: None,
            child_model_to_child_view_model: None,
            async_selection: false,
            current_selector: None,
            destruct_order: ChildOrder::Insertion,
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

    /// Sets the order of the destruct and dispose walks (ADR-0161). The
    /// default is [`ChildOrder::Insertion`]; construct order is unchanged.
    pub fn destruct_order(mut self, order: ChildOrder) -> Self {
        self.destruct_order = order;
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
            inner: CompositeVm::with_destruct_order(name, hub, dispatcher, self.destruct_order),
            children_models,
            child_model_to_child_view_model,
            loaded: Arc::new(Mutex::new(false)),
        };
        if let Some(hint) = self.hint {
            vm.inner.core.set_hint(hint);
        }
        vm.inner.set_async_selection(self.async_selection);
        if let Some(selector) = self.current_selector {
            vm.inner.set_current_selector(move |items| selector(items));
        }
        Ok(vm)
    }
}
