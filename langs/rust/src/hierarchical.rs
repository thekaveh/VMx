//! Recursive hierarchical view models, batch attachment, and tree traversal.
//!
//! Spec: `spec/18-hierarchical-vm.md`; ADR-0048 and ADR-0087.

use super::{
    catch_unwind, lock, resume_unwind, thread, wait, Arc, AssertUnwindSafe, ComponentVm, Condvar,
    ConstructionStatus, Expandable, Hash, HashMap, HashSet, Message, MessageHub, Mutex,
    NullDispatcher, ParentHandle, PropertyChangedMessage, PropertyChangedStream, ThreadId,
    TreeNode, TreeStructureChange, TreeStructureChangedMessage, VmNode, VmxError, VmxResult, Weak,
    HIERARCHY_TOPOLOGY_GATE,
};

type HierChildrenFactory<M> =
    Arc<dyn Fn(&HierarchicalVm<M>) -> Vec<HierarchicalVm<M>> + Send + Sync>;

#[cfg(test)]
type MaterializationValidationHook = Box<dyn Fn() + Send + 'static>;

#[cfg(test)]
static MATERIALIZATION_VALIDATION_HOOK: Mutex<Option<MaterializationValidationHook>> =
    Mutex::new(None);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Controls how batch attachment handles items whose parent key is unavailable.
pub enum MissingParentPolicy {
    /// Retain the item at the structural root for a later batch.
    Park,
    /// Reject the item without retaining it.
    Reject,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Classifies a non-throwing batch-attachment rejection.
pub enum BatchAttachRejectionReason {
    /// The key already belongs to a node in the existing tree.
    DuplicateExistingKey,
    /// The key appears more than once in the incoming batch.
    DuplicateBatchKey,
    /// The item is already attached to a hierarchy.
    AlreadyAttached,
    /// The selected parent key could not be resolved.
    MissingParent,
    /// The attachment would create a hierarchy cycle.
    Cycle,
    /// A key selector failed or returned an invalid key.
    SelectorFailed,
    /// The final structural attachment failed.
    AttachmentFailed,
}

/// One rejected batch-attachment item with a stable reason and optional detail.
pub struct BatchAttachRejection<N> {
    /// The rejected input item.
    pub item: N,
    /// The stable rejection classification.
    pub reason: BatchAttachRejectionReason,
    /// Optional diagnostic detail from the failing operation.
    pub detail: Option<String>,
}

/// Partitioned outcome of a non-throwing hierarchical batch attachment.
pub struct BatchAttachResult<N> {
    /// Items attached during this batch.
    pub added: Vec<N>,
    /// Items rejected because of duplicate keys.
    pub duplicates: Vec<N>,
    /// Items whose selected parent was unavailable.
    pub orphans: Vec<N>,
    /// Structured rejections in deterministic input order.
    pub rejections: Vec<BatchAttachRejection<N>>,
}

struct BatchAttachCandidate<N, K> {
    item: N,
    key: K,
    parent_key: Option<K>,
    retain_if_missing: bool,
}

#[derive(Default)]
struct ChildrenMaterializationState {
    owner: Option<ThreadId>,
    epoch: u64,
    reentered_epoch: u64,
}

/// A recursive modeled VM with lazy children and derived topology properties.
///
/// Hierarchies do not implicitly opt in to expansion; consumers compose
/// [`crate::ExpandableState`] in a wrapper when expanded traversal is needed:
///
/// ```compile_fail
/// use vmx::{Expandable, HierarchicalVm};
///
/// fn requires_expandable<T: Expandable>(_: &T) {}
/// requires_expandable(&HierarchicalVm::new("root", "root".to_string()));
/// ```
pub struct HierarchicalVm<M: Clone + PartialEq + Send + Sync + 'static> {
    inner: Arc<HierarchicalVmInner<M>>,
    materialization_context: Option<u64>,
}

struct HierarchicalVmInner<M: Clone + PartialEq + Send + Sync + 'static> {
    component: ComponentVm<M>,
    children: Arc<Mutex<Option<Vec<HierarchicalVm<M>>>>>,
    materializing_children: Arc<(Mutex<ChildrenMaterializationState>, Condvar)>,
    parent: Mutex<Option<Weak<HierarchicalVmInner<M>>>>,
    children_factory: HierChildrenFactory<M>,
    eager_children: Arc<Mutex<bool>>,
    parked_attach_items: Arc<Mutex<Vec<HierarchicalVm<M>>>>,
    hub: MessageHub,
}

impl<M: Clone + PartialEq + Send + Sync + 'static> HierarchicalVm<M> {
    /// Creates a leaf-like VM whose children factory initially returns no children.
    pub fn new(name: impl Into<String>, model: M) -> Self {
        Self::with_children_factory(name, model, |_| Vec::new(), false, MessageHub::new())
    }

    /// Creates a VM with an explicit lazy or eager children factory.
    pub fn with_children_factory<F>(
        name: impl Into<String>,
        model: M,
        children_factory: F,
        eager_children: bool,
        hub: MessageHub,
    ) -> Self
    where
        F: Fn(&Self) -> Vec<Self> + Send + Sync + 'static,
    {
        Self {
            inner: Arc::new(HierarchicalVmInner {
                component: ComponentVm::with_model(name, model, hub.clone(), NullDispatcher::new()),
                children: Arc::new(Mutex::new(None)),
                materializing_children: Arc::new((
                    Mutex::new(ChildrenMaterializationState::default()),
                    Condvar::new(),
                )),
                parent: Mutex::new(None),
                children_factory: Arc::new(children_factory),
                eager_children: Arc::new(Mutex::new(eager_children)),
                parked_attach_items: Arc::new(Mutex::new(Vec::new())),
                hub,
            }),
            materialization_context: None,
        }
    }

    /// Creates an immutable hierarchy builder.
    pub fn builder() -> HierarchicalVmBuilder<M> {
        HierarchicalVmBuilder::new()
    }

    /// Returns this node's stable identity.
    pub fn id(&self) -> usize {
        self.inner.component.id()
    }

    /// Returns this node's name.
    pub fn name(&self) -> String {
        self.inner.component.name()
    }

    /// Returns this node's model.
    pub fn model(&self) -> M {
        self.inner.component.model()
    }

    /// Returns this node's hint.
    pub fn hint(&self) -> Option<String> {
        self.inner.component.hint()
    }

    /// Returns this node's message hub.
    pub fn hub(&self) -> MessageHub {
        self.inner.hub.clone()
    }

    /// Registers an owned cleanup action with this node.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.component.own(cleanup);
    }

    /// Returns this node's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.component.property_changed()
    }

    /// Publishes one named property change from this node.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.component.notify_property_changed(property_name);
    }

    /// Returns this node's parent, when attached.
    pub fn parent(&self) -> Option<Self> {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        self.parent_unlocked()
    }

    fn parent_unlocked(&self) -> Option<Self> {
        lock(&self.inner.parent)
            .as_ref()
            .and_then(Weak::upgrade)
            .map(|inner| Self {
                inner,
                materialization_context: None,
            })
    }

    /// Adds or transfers `child` beneath this node.
    pub fn add_child(&self, child: Self) -> VmxResult<()> {
        self.reject_structural_reentry()?;
        self.attach_child(&child)
    }

    /// Removes `child` from this node without disposing it.
    pub fn remove_child(&self, child: &Self) -> VmxResult<()> {
        self.reject_structural_reentry()?;
        self.try_children()?;
        let (removed, index) = {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            let mut children = lock(&self.inner.children);
            let children = children.as_mut().expect("children materialized");
            let removed = children
                .iter()
                .position(|candidate| candidate == child)
                .map(|index| (children.remove(index), index));
            if let Some((removed, _)) = &removed {
                removed.set_parent_state(None);
            }
            removed
        }
        .ok_or(VmxError::NonChild)?;
        removed.publish_parent_changed();
        self.inner
            .hub
            .send(Message::TreeStructureChanged(TreeStructureChangedMessage {
                sender_id: self.id(),
                sender_name: self.name(),
                change: TreeStructureChange::Removed,
                affected_id: removed.id(),
                index: index as isize,
            }));
        Ok(())
    }

    /// Transfers `child` from its current parent beneath this node.
    pub fn reparent_child(&self, child: &Self) -> VmxResult<()> {
        self.reject_structural_reentry()?;
        self.attach_child(child)
    }

    fn attach_child(&self, child: &Self) -> VmxResult<()> {
        // Materialize the destination before detaching so a child factory
        // failure cannot orphan an attached child.
        let (reparented, index) = loop {
            self.try_children()?;
            let attached = {
                let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
                if lock(&self.inner.children).is_none() {
                    None
                } else {
                    self.ensure_not_reparenting_cycle_unlocked(child)?;
                    let old_parent = child.parent_unlocked();
                    if old_parent.as_ref() == Some(self) {
                        return Ok(());
                    }
                    let reparented = old_parent.is_some();
                    if let Some(parent) = &old_parent {
                        if let Some(children) = lock(&parent.inner.children).as_mut() {
                            children.retain(|candidate| candidate != child);
                        }
                    }
                    let mut children = lock(&self.inner.children);
                    let children = children.as_mut().expect("children materialized");
                    let index = children.len();
                    if !children.iter().any(|candidate| candidate == child) {
                        children.push(child.clone());
                    }
                    child.set_parent_state(Some(self.clone()));
                    Some((reparented, index))
                }
            };
            if let Some(attached) = attached {
                break attached;
            }
        };
        child.publish_parent_changed();
        self.inner
            .hub
            .send(Message::TreeStructureChanged(TreeStructureChangedMessage {
                sender_id: self.id(),
                sender_name: self.name(),
                change: if reparented {
                    TreeStructureChange::Reparented
                } else {
                    TreeStructureChange::Added
                },
                affected_id: child.id(),
                index: if reparented { -1 } else { index as isize },
            }));
        Ok(())
    }

    /// Returns the number of missing-parent items parked at the structural root.
    pub fn parked_attach_count(&self) -> usize {
        lock(&self.tree_root().inner.parked_attach_items).len()
    }

    /// Attaches an out-of-order batch by stable item and parent keys.
    pub fn attach_many<K, FKey, FParent>(
        &self,
        items: Vec<Self>,
        key_of: FKey,
        parent_key_of: FParent,
        on_missing_parent: MissingParentPolicy,
    ) -> BatchAttachResult<Self>
    where
        K: Clone + Eq + Hash,
        FKey: Fn(&Self) -> VmxResult<K>,
        FParent: Fn(&Self) -> VmxResult<Option<K>>,
    {
        if let Err(error) = self.reject_structural_reentry() {
            return BatchAttachResult {
                added: Vec::new(),
                duplicates: Vec::new(),
                orphans: Vec::new(),
                rejections: items
                    .into_iter()
                    .map(|item| BatchAttachRejection {
                        item,
                        reason: BatchAttachRejectionReason::AttachmentFailed,
                        detail: Some(error.to_string()),
                    })
                    .collect(),
            };
        }
        let root = self.tree_root();
        let parked = std::mem::take(&mut *lock(&root.inner.parked_attach_items));
        let mut added = Vec::new();
        let mut duplicates = Vec::new();
        let mut orphans = Vec::new();
        let mut rejections = Vec::new();
        let mut existing = HashMap::<K, Self>::new();

        for materialized in root.materialized_subtree() {
            let key = match key_of(&materialized) {
                Ok(key) => key,
                Err(error) => {
                    lock(&root.inner.parked_attach_items).extend(parked.iter().cloned());
                    rejections.extend(parked.into_iter().chain(items).map(|item| {
                        BatchAttachRejection {
                            item,
                            reason: BatchAttachRejectionReason::SelectorFailed,
                            detail: Some(error.to_string()),
                        }
                    }));
                    return BatchAttachResult {
                        added,
                        duplicates,
                        orphans,
                        rejections,
                    };
                }
            };
            existing.entry(key).or_insert(materialized);
        }

        let mut candidates = Vec::<BatchAttachCandidate<Self, K>>::new();
        let mut candidate_keys = HashSet::<K>::new();
        let active = parked
            .into_iter()
            .map(|item| (item, true))
            .chain(items.into_iter().map(|item| (item, false)));
        for (item, was_parked) in active {
            let key = match key_of(&item) {
                Ok(key) => key,
                Err(error) => {
                    if was_parked {
                        lock(&root.inner.parked_attach_items).push(item.clone());
                    }
                    rejections.push(BatchAttachRejection {
                        item,
                        reason: BatchAttachRejectionReason::SelectorFailed,
                        detail: Some(error.to_string()),
                    });
                    continue;
                }
            };
            let parent_key = match parent_key_of(&item) {
                Ok(parent_key) => parent_key,
                Err(error) => {
                    if was_parked {
                        lock(&root.inner.parked_attach_items).push(item.clone());
                    }
                    rejections.push(BatchAttachRejection {
                        item,
                        reason: BatchAttachRejectionReason::SelectorFailed,
                        detail: Some(error.to_string()),
                    });
                    continue;
                }
            };

            if existing.contains_key(&key) {
                duplicates.push(item.clone());
                rejections.push(BatchAttachRejection {
                    item,
                    reason: BatchAttachRejectionReason::DuplicateExistingKey,
                    detail: None,
                });
                continue;
            }
            if candidate_keys.contains(&key) {
                duplicates.push(item.clone());
                rejections.push(BatchAttachRejection {
                    item,
                    reason: BatchAttachRejectionReason::DuplicateBatchKey,
                    detail: None,
                });
                continue;
            }
            if item.parent().is_some() {
                rejections.push(BatchAttachRejection {
                    item,
                    reason: BatchAttachRejectionReason::AlreadyAttached,
                    detail: None,
                });
                continue;
            }
            candidate_keys.insert(key.clone());
            candidates.push(BatchAttachCandidate {
                item,
                key,
                parent_key,
                retain_if_missing: was_parked || on_missing_parent == MissingParentPolicy::Park,
            });
        }

        let mut unresolved = candidates;
        loop {
            if unresolved.is_empty() {
                break;
            }
            let mut next = Vec::new();
            let mut progressed = false;
            for candidate in unresolved {
                let parent = candidate
                    .parent_key
                    .as_ref()
                    .and_then(|key| existing.get(key).cloned())
                    .or_else(|| candidate.parent_key.is_none().then(|| root.clone()));
                let Some(parent) = parent else {
                    next.push(candidate);
                    continue;
                };
                if let Err(error) = parent.add_child(candidate.item.clone()) {
                    Self::rollback_batch_attach(&parent, &candidate.item);
                    rejections.push(BatchAttachRejection {
                        item: candidate.item,
                        reason: BatchAttachRejectionReason::AttachmentFailed,
                        detail: Some(error.to_string()),
                    });
                    continue;
                }
                existing.insert(candidate.key, candidate.item.clone());
                added.push(candidate.item);
                progressed = true;
            }
            unresolved = next;
            if !progressed {
                break;
            }
        }

        let unresolved_by_key = unresolved
            .iter()
            .map(|candidate| (candidate.key.clone(), candidate.parent_key.clone()))
            .collect::<HashMap<_, _>>();
        for candidate in unresolved {
            let is_cycle = Self::batch_parent_chain_cycles(&candidate, &unresolved_by_key);
            let reason = if is_cycle {
                BatchAttachRejectionReason::Cycle
            } else {
                BatchAttachRejectionReason::MissingParent
            };
            rejections.push(BatchAttachRejection {
                item: candidate.item.clone(),
                reason,
                detail: None,
            });
            if !is_cycle {
                orphans.push(candidate.item.clone());
                if candidate.retain_if_missing {
                    lock(&root.inner.parked_attach_items).push(candidate.item);
                }
            }
        }

        BatchAttachResult {
            added,
            duplicates,
            orphans,
            rejections,
        }
    }

    /// Materializes and returns this node's ordered children.
    pub fn children(&self) -> Vec<Self> {
        self.try_children().unwrap_or_else(|error| {
            panic!("children factory returned structurally invalid output: {error}")
        })
    }

    /// Materializes children after atomically validating the complete factory
    /// snapshot. Invalid output leaves the hierarchy unchanged and can be retried.
    pub fn try_children(&self) -> VmxResult<Vec<Self>> {
        self.materialize_children()
    }

    /// Reports whether the children factory has been evaluated.
    pub fn is_children_materialized(&self) -> bool {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        lock(&self.inner.children).is_some()
    }

    /// Reports whether this node has no parent.
    pub fn is_root(&self) -> bool {
        self.parent().is_none()
    }

    /// Reports whether this node has no children.
    pub fn is_leaf(&self) -> bool {
        self.children().is_empty()
    }

    /// Returns this node's zero-based depth from the root.
    pub fn depth(&self) -> usize {
        self.parent().map(|parent| parent.depth() + 1).unwrap_or(0)
    }

    /// Returns the root-to-self path.
    pub fn path(&self) -> Vec<Self> {
        let mut path = self
            .parent()
            .map(|parent| parent.path())
            .unwrap_or_default();
        path.push(self.clone());
        path
    }

    /// Reports whether this is the first child of its parent.
    pub fn is_first(&self) -> bool {
        self.parent()
            .and_then(|parent| parent.children().first().cloned())
            .map(|first| first == *self)
            .unwrap_or(false)
    }

    /// Reports whether this is the last child of its parent.
    pub fn is_last(&self) -> bool {
        self.parent()
            .and_then(|parent| parent.children().last().cloned())
            .map(|last| last == *self)
            .unwrap_or(false)
    }

    /// Constructs this node and, when configured eager, its descendants.
    pub fn construct(&self) -> VmxResult<()> {
        if *lock(&self.inner.eager_children) {
            for child in self.children() {
                child.construct()?;
            }
        }
        self.inner.component.construct()
    }

    /// Returns this node's lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.inner.component.status()
    }

    /// Detaches materialized children so the factory runs on the next read.
    pub fn invalidate_children(&self) {
        if self.reject_structural_reentry().is_err() {
            return;
        }
        let was_materialized = {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            let discarded = lock(&self.inner.children).take();
            if let Some(children) = &discarded {
                for child in children {
                    let attached_to_self = child.parent_unlocked().as_ref() == Some(self);
                    if attached_to_self {
                        child.set_parent_state(None);
                    }
                }
            }
            discarded.is_some()
        };
        if was_materialized {
            self.inner
                .hub
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.id(),
                    sender_name: self.name(),
                    property_name: "children".to_string(),
                }));
        }
    }

    /// Invalidates this node and every currently materialized descendant.
    pub fn invalidate_subtree(&self) {
        if self.reject_structural_reentry().is_err() {
            return;
        }
        let materialized_children = lock(&self.inner.children).clone();
        if let Some(children) = materialized_children {
            for child in children {
                child.invalidate_subtree();
            }
            self.invalidate_children();
        }
    }

    /// Disposes this node and clears parked batch items. Children are not
    /// disposed, destructed, detached, or reparented (spec/18-hierarchical-vm.md
    /// §3).
    pub fn dispose(&self) -> VmxResult<()> {
        lock(&self.inner.parked_attach_items).clear();
        self.inner.component.dispose()
    }

    fn materialize_children(&self) -> VmxResult<Vec<Self>> {
        let current = thread::current().id();
        let epoch = loop {
            let topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            if let Some(children) = lock(&self.inner.children).clone() {
                return Ok(children);
            }

            let (state, ready) = &*self.inner.materializing_children;
            let mut state = lock(state);
            if let Some(children) = lock(&self.inner.children).clone() {
                return Ok(children);
            }
            match state.owner {
                None => {
                    state.epoch = state.epoch.wrapping_add(1).max(1);
                    let epoch = state.epoch;
                    state.owner = Some(current);
                    drop(state);
                    drop(topology);
                    break epoch;
                }
                Some(active)
                    if active == current || self.materialization_context == Some(state.epoch) =>
                {
                    state.reentered_epoch = state.epoch;
                    return Err(VmxError::InvalidArgument(
                        "children factory re-entered structural materialization".to_string(),
                    ));
                }
                Some(_) => {
                    drop(topology);
                    drop(wait(ready, state));
                }
            }
        };

        let factory_receiver = Self {
            inner: Arc::clone(&self.inner),
            materialization_context: Some(epoch),
        };
        let generated = catch_unwind(AssertUnwindSafe(|| {
            (self.inner.children_factory)(&factory_receiver)
        }));
        let children = match generated {
            Ok(children) => children,
            Err(error) => {
                self.finish_children_materialization(epoch);
                resume_unwind(error);
            }
        };
        let mut owner_released = false;
        let committed = (|| -> VmxResult<Vec<Self>> {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            #[cfg(test)]
            if let Some(hook) = lock(&MATERIALIZATION_VALIDATION_HOOK).as_ref() {
                hook();
            }
            let mut seen = HashSet::new();
            for child in &children {
                if !seen.insert(child.id()) {
                    return Err(VmxError::InvalidArgument(
                        "children factory returned duplicate child identity".to_string(),
                    ));
                }
                let mut ancestor = Some(self.clone());
                while let Some(node) = ancestor {
                    if node == *child {
                        return Err(VmxError::InvalidArgument(
                            "children factory returned this node or one of its ancestors"
                                .to_string(),
                        ));
                    }
                    ancestor = node.parent_unlocked();
                }
                if child.parent_unlocked().is_some() {
                    return Err(VmxError::InvalidArgument(
                        "children factory returned an already-parented child".to_string(),
                    ));
                }
            }
            let (materialization_state, ready) = &*self.inner.materializing_children;
            let mut materialization_state = lock(materialization_state);
            if materialization_state.epoch != epoch
                || materialization_state.owner != Some(current)
                || materialization_state.reentered_epoch == epoch
            {
                return Err(VmxError::InvalidArgument(
                    "children factory re-entered a structural operation".to_string(),
                ));
            }
            for child in &children {
                child.set_parent_state(Some(Self {
                    inner: Arc::clone(&self.inner),
                    materialization_context: None,
                }));
            }
            *lock(&self.inner.children) = Some(children.clone());
            let result = children.clone();
            materialization_state.owner = None;
            drop(materialization_state);
            ready.notify_all();
            owner_released = true;
            Ok(result)
        })();
        if !owner_released {
            self.finish_children_materialization(epoch);
        }
        // First materialization is initial construction, not a parent *change*:
        // the children are born as this node's children. Emitting
        // PropertyChanged("parent") here would publish N spurious hub messages on
        // the first lazy children() access. The other four flavors assign the
        // parent silently on hydration (see the C# note in HierarchicalVM); real
        // reparents/detaches still emit via publish_parent_changed elsewhere.
        committed
    }

    fn tree_root(&self) -> Self {
        let mut current = self.clone();
        while let Some(parent) = current.parent() {
            current = parent;
        }
        current
    }

    fn materialized_subtree(&self) -> Vec<Self> {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        let mut result = Vec::new();
        let mut stack = vec![self.clone()];
        while let Some(current) = stack.pop() {
            result.push(current.clone());
            if let Some(children) = lock(&current.inner.children).clone() {
                stack.extend(children.into_iter().rev());
            }
        }
        result
    }

    fn batch_parent_chain_cycles<K: Clone + Eq + Hash>(
        candidate: &BatchAttachCandidate<Self, K>,
        unresolved: &HashMap<K, Option<K>>,
    ) -> bool {
        let mut seen = HashSet::new();
        let mut current_key = candidate.key.clone();
        loop {
            if !seen.insert(current_key.clone()) {
                return true;
            }
            match unresolved.get(&current_key) {
                Some(Some(parent_key)) => current_key = parent_key.clone(),
                Some(None) | None => return false,
            }
        }
    }

    fn rollback_batch_attach(parent: &Self, child: &Self) {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        if let Some(children) = lock(&parent.inner.children).as_mut() {
            children.retain(|item| item.id() != child.id());
        }
        child.set_parent_state(None);
    }

    fn set_parent_state(&self, parent: Option<Self>) {
        *lock(&self.inner.parent) = parent.as_ref().map(|parent| Arc::downgrade(&parent.inner));
        self.inner
            .component
            .core
            .set_parent_id(parent.as_ref().map(|parent| parent.id()));
    }

    fn publish_parent_changed(&self) {
        self.inner
            .hub
            .send(Message::PropertyChanged(PropertyChangedMessage {
                sender_id: self.id(),
                sender_name: self.name(),
                property_name: "parent".to_string(),
            }));
    }

    fn ensure_not_reparenting_cycle_unlocked(&self, child: &Self) -> VmxResult<()> {
        let mut current = Some(self.clone());
        while let Some(node) = current {
            if node == *child {
                return Err(VmxError::InvalidArgument(
                    "cannot reparent self or ancestor".to_string(),
                ));
            }
            current = node.parent_unlocked();
        }
        if child.id() == self.id() {
            return Err(VmxError::InvalidArgument(
                "cannot reparent self or ancestor".to_string(),
            ));
        }
        Ok(())
    }

    fn finish_children_materialization(&self, epoch: u64) {
        let (state, ready) = &*self.inner.materializing_children;
        let mut state = lock(state);
        if state.epoch == epoch {
            state.owner = None;
        }
        drop(state);
        ready.notify_all();
    }

    fn reject_structural_reentry(&self) -> VmxResult<()> {
        let current = thread::current().id();
        let mut state = lock(&self.inner.materializing_children.0);
        if let Some(owner) = state.owner {
            if owner == current || self.materialization_context == Some(state.epoch) {
                state.reentered_epoch = state.epoch;
                return Err(VmxError::InvalidArgument(
                    "children factory re-entered a structural operation on its receiver"
                        .to_string(),
                ));
            }
            return Err(VmxError::InvalidArgument(
                "structural operation overlaps active children materialization".to_string(),
            ));
        }
        Ok(())
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> Clone for HierarchicalVm<M> {
    fn clone(&self) -> Self {
        let current = thread::current().id();
        let state = lock(&self.inner.materializing_children.0);
        let materialization_context = match state.owner {
            Some(owner) if owner == current => Some(state.epoch),
            _ => self.materialization_context,
        };
        drop(state);
        Self {
            inner: Arc::clone(&self.inner),
            materialization_context,
        }
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> PartialEq for HierarchicalVm<M> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> Eq for HierarchicalVm<M> {}

impl<M: Clone + PartialEq + Send + Sync + 'static> VmNode for HierarchicalVm<M> {
    fn id(&self) -> usize {
        HierarchicalVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        HierarchicalVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        self.inner.component.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        HierarchicalVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        HierarchicalVm::status(self)
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.component.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.inner.component.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.component.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.component.core.parent_handle()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> TreeNode for HierarchicalVm<M> {
    fn children_nodes(&self) -> Vec<Self> {
        self.children()
    }
}

#[derive(Clone)]
/// Immutable builder for [`HierarchicalVm`].
pub struct HierarchicalVmBuilder<M: Clone + PartialEq + Send + Sync + 'static> {
    model: Option<M>,
    children_factory: Option<HierChildrenFactory<M>>,
    services: Option<(MessageHub, NullDispatcher)>,
    hint: Option<String>,
    eager_children: bool,
}

impl<M: Clone + PartialEq + Send + Sync + 'static> Default for HierarchicalVmBuilder<M> {
    fn default() -> Self {
        Self {
            model: None,
            children_factory: None,
            services: None,
            hint: None,
            eager_children: false,
        }
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> HierarchicalVmBuilder<M> {
    /// Creates an empty builder with lazy children.
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the required root model.
    pub fn model(mut self, model: M) -> Self {
        self.model = Some(model);
        self
    }

    /// Sets the recursive children factory.
    pub fn children_factory<F>(mut self, factory: F) -> Self
    where
        F: Fn(&HierarchicalVm<M>) -> Vec<HierarchicalVm<M>> + Send + Sync + 'static,
    {
        self.children_factory = Some(Arc::new(factory));
        self
    }

    /// Sets the hub and null dispatcher services.
    pub fn services(mut self, hub: MessageHub, dispatcher: NullDispatcher) -> Self {
        self.services = Some((hub, dispatcher));
        self
    }

    /// Sets the optional hierarchy hint.
    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    /// Controls whether construction eagerly materializes descendants.
    pub fn eager_children(mut self, eager: bool) -> Self {
        self.eager_children = eager;
        self
    }

    /// Validates required fields and builds a hierarchy root.
    pub fn build(self) -> VmxResult<HierarchicalVm<M>> {
        let model = self
            .model
            .ok_or_else(|| VmxError::BuilderValidation("model is required".to_string()))?;
        let factory = self.children_factory.ok_or_else(|| {
            VmxError::BuilderValidation("children_factory is required".to_string())
        })?;
        let (hub, _dispatcher) = self
            .services
            .ok_or_else(|| VmxError::BuilderValidation("services are required".to_string()))?;
        let node = HierarchicalVm::with_children_factory(
            "HierarchicalVm",
            model,
            move |parent| factory(parent),
            self.eager_children,
            hub,
        );
        if let Some(hint) = self.hint {
            node.inner.component.core.set_hint(Some(hint));
        }
        Ok(node)
    }
}

/// Returns a depth-first pre-order snapshot rooted at `root`.
pub fn walk<T: TreeNode>(root: &T) -> Vec<T> {
    let mut nodes = vec![root.clone()];
    for child in root.children_nodes() {
        nodes.extend(walk(&child));
    }
    nodes
}

/// Returns the first depth-first node matching `predicate`.
pub fn find<T: TreeNode, F>(root: &T, predicate: F) -> Option<T>
where
    F: Fn(&T) -> bool,
{
    find_inner(root, &predicate)
}

fn find_inner<T: TreeNode, F>(root: &T, predicate: &F) -> Option<T>
where
    F: Fn(&T) -> bool,
{
    if predicate(root) {
        return Some(root.clone());
    }
    for child in root.children_nodes() {
        if let Some(found) = find_inner(&child, predicate) {
            return Some(found);
        }
    }
    None
}

/// Returns a depth-first snapshot while skipping collapsed descendants.
pub fn walk_expanded<T: TreeNode>(root: &T) -> Vec<T> {
    let mut nodes = vec![root.clone()];
    if root.expandable().is_none_or(Expandable::is_expanded) {
        for child in root.children_nodes() {
            nodes.extend(walk_expanded(&child));
        }
    }
    nodes
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::mpsc;
    use std::time::Duration;

    #[test]
    fn late_contextual_reentry_is_rejected_at_the_commit_boundary() {
        let hub = MessageHub::new();
        let messages = Arc::new(Mutex::new(Vec::<Message>::new()));
        let captured_messages = Arc::clone(&messages);
        let _subscription = hub.subscribe(move |message| {
            captured_messages.lock().unwrap().push(message.clone());
        });
        let retry_child = HierarchicalVm::new("retry-child", "retry-child".to_string());
        let captured_retry_child = retry_child.clone();
        let late_child = HierarchicalVm::new("late-child", "late-child".to_string());
        let captured_late_child = late_child.clone();
        let attempts = Arc::new(AtomicUsize::new(0));
        let captured_attempts = Arc::clone(&attempts);
        let (release_worker_tx, release_worker_rx) = mpsc::channel();
        let release_worker_rx = Arc::new(Mutex::new(release_worker_rx));
        let captured_release_worker = Arc::clone(&release_worker_rx);
        let (worker_result_tx, worker_result_rx) = mpsc::channel();
        let root = HierarchicalVm::with_children_factory(
            "root",
            "root".to_string(),
            move |parent| {
                if captured_attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                    let delegated_parent: HierarchicalVm<String> = (*parent).clone();
                    let delegated_child = captured_late_child.clone();
                    let worker_release = Arc::clone(&captured_release_worker);
                    let result_tx = worker_result_tx.clone();
                    std::thread::spawn(move || {
                        worker_release.lock().unwrap().recv().unwrap();
                        result_tx
                            .send(delegated_parent.add_child(delegated_child))
                            .unwrap();
                    });
                    vec![HierarchicalVm::new(
                        "first-attempt",
                        "first-attempt".to_string(),
                    )]
                } else {
                    vec![captured_retry_child.clone()]
                }
            },
            false,
            hub,
        );

        let (at_boundary_tx, at_boundary_rx) = mpsc::channel();
        let (resume_tx, resume_rx) = mpsc::channel();
        let resume_rx = Arc::new(Mutex::new(resume_rx));
        let captured_resume = Arc::clone(&resume_rx);
        *lock(&MATERIALIZATION_VALIDATION_HOOK) = Some(Box::new(move || {
            at_boundary_tx.send(()).unwrap();
            captured_resume.lock().unwrap().recv().unwrap();
        }));

        let (hydration_tx, hydration_rx) = mpsc::channel();
        let first_root = root.clone();
        std::thread::spawn(move || {
            hydration_tx.send(first_root.try_children()).unwrap();
        });
        at_boundary_rx
            .recv_timeout(Duration::from_millis(500))
            .unwrap();
        release_worker_tx.send(()).unwrap();
        assert!(matches!(
            worker_result_rx
                .recv_timeout(Duration::from_millis(500))
                .unwrap(),
            Err(VmxError::InvalidArgument(message)) if message.contains("factory re-entered")
        ));
        resume_tx.send(()).unwrap();
        assert!(hydration_rx
            .recv_timeout(Duration::from_millis(500))
            .unwrap()
            .is_err());
        *lock(&MATERIALIZATION_VALIDATION_HOOK) = None;

        assert!(late_child.parent().is_none());
        assert!(messages.lock().unwrap().is_empty());
        assert!(root.try_children().unwrap() == vec![retry_child.clone()]);
        assert!(retry_child.parent().as_ref() == Some(&root));
        assert_eq!(attempts.load(Ordering::SeqCst), 2);
        assert!(messages.lock().unwrap().is_empty());
    }
}
