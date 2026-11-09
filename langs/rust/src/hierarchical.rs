//! Recursive hierarchical view models, batch attachment, and tree traversal.
//!
//! Spec: `spec/18-hierarchical-vm.md`; ADR-0048 and ADR-0087.

use super::{
    catch_unwind, lock, resume_unwind, thread, wait, Arc, AssertUnwindSafe, ComponentVm, Condvar,
    ConstructionStatus, Expandable, ExpandableState, Hash, HashMap, HashSet, Message, MessageHub,
    Mutex, NullDispatcher, OnceLock, ParentHandle, PropertyChangedMessage, PropertyChangedStream,
    ThreadId, TreeNode, TreeNodeRef, TreeStructureChange, TreeStructureChangedMessage, VmNode,
    VmxError, VmxResult, Weak, HIERARCHY_TOPOLOGY_GATE,
};

type HierChildrenFactory<M, N> =
    Arc<dyn Fn(&HierarchicalVm<M, N>) -> Vec<HierarchicalVm<M, N>> + Send + Sync>;

/// A node's materialized children.
type HierChildren<M, N> = Vec<HierarchicalVm<M, N>>;

// The hook runs only for the node whose identity it names, so tests that
// materialize other trees in parallel never reach it.
#[cfg(test)]
type MaterializationValidationHook = (usize, Box<dyn Fn() + Send + 'static>);

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
/// Hierarchies do not implicitly opt in to expansion. A consumer composes an
/// [`ExpandableState`] with [`compose_expansion`](Self::compose_expansion)
/// when expanded traversal is needed, and [`walk_expanded`] then stops at the
/// node while the state is collapsed (spec/18 §9, ADR-0207). The node itself
/// does not implement [`Expandable`]:
///
/// ```compile_fail
/// use vmx::{Expandable, HierarchicalVm};
///
/// fn requires_expandable<T: Expandable>(_: &T) {}
/// requires_expandable(&HierarchicalVm::new("root", "root".to_string()));
/// ```
///
/// # Node data
///
/// `N` is consumer node data, the Rust form of a `TVM` subclass (spec/18 §2,
/// ADR-0202). Every node of one tree has the same type
/// `HierarchicalVm<M, N>`, so [`parent`](Self::parent),
/// [`children`](Self::children) and [`path`](Self::path) return nodes whose
/// [`node_data`](Self::node_data) needs no downcast. `N` defaults to `()`, so
/// `HierarchicalVm<M>` names a node without data.
///
/// Clones of a node share one `N`, so `N` needs no `Clone` or `PartialEq`.
/// Keep changing state behind interior mutability, such as a `Mutex` or an
/// atomic, and add node methods through an extension trait. `N` must not hold
/// a strong handle to its own node or to an ancestor: that makes a reference
/// cycle, and the nodes are never dropped.
pub struct HierarchicalVm<
    M: Clone + PartialEq + Send + Sync + 'static,
    N: Send + Sync + 'static = (),
> {
    inner: Arc<HierarchicalVmInner<M, N>>,
    materialization_context: Option<u64>,
}

struct HierarchicalVmInner<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> {
    component: ComponentVm<M>,
    node_data: N,
    children: Arc<Mutex<Option<HierChildren<M, N>>>>,
    materializing_children: Arc<(Mutex<ChildrenMaterializationState>, Condvar)>,
    parent: Mutex<Option<Weak<HierarchicalVmInner<M, N>>>>,
    children_factory: HierChildrenFactory<M, N>,
    eager_children: Arc<Mutex<bool>>,
    parked_attach_items: Arc<Mutex<Vec<HierarchicalVm<M, N>>>>,
    hub: MessageHub,
    /// The composed expansion capability, set at most once.
    expansion: OnceLock<ExpandableState>,
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
        Self::with_node_data(name, model, (), children_factory, eager_children, hub)
    }

    /// Creates an immutable hierarchy builder.
    pub fn builder() -> HierarchicalVmBuilder<M> {
        HierarchicalVmBuilder::new()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> HierarchicalVm<M, N> {
    /// Creates a VM that carries consumer node data, with an explicit lazy or
    /// eager children factory.
    ///
    /// ```
    /// use vmx::{HierarchicalVm, MessageHub};
    ///
    /// struct FolderData {
    ///     size: u64,
    /// }
    ///
    /// let root = HierarchicalVm::with_node_data(
    ///     "root",
    ///     "root".to_string(),
    ///     FolderData { size: 1 },
    ///     |_| {
    ///         vec![HierarchicalVm::with_node_data(
    ///             "child",
    ///             "child".to_string(),
    ///             FolderData { size: 2 },
    ///             |_| Vec::new(),
    ///             false,
    ///             MessageHub::new(),
    ///         )]
    ///     },
    ///     false,
    ///     MessageHub::new(),
    /// );
    ///
    /// let child = &root.children()[0];
    /// assert_eq!(child.node_data().size, 2);
    /// assert_eq!(child.parent().unwrap().node_data().size, 1);
    /// ```
    pub fn with_node_data<F>(
        name: impl Into<String>,
        model: M,
        node_data: N,
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
                node_data,
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
                expansion: OnceLock::new(),
            }),
            materialization_context: None,
        }
    }

    /// Composes `expansion` as this node's opt-in expansion capability.
    ///
    /// [`TreeNode::expandable`] then returns it, so [`walk_expanded`] yields
    /// this node but not its descendants while `expansion` is collapsed.
    /// Clones of the node share the composition. The node does not dispose
    /// the state; the caller keeps that ownership.
    ///
    /// ```
    /// use vmx::{walk_expanded, ExpandableState, HierarchicalVm};
    ///
    /// let root = HierarchicalVm::new("root", "root".to_string());
    /// root.add_child(HierarchicalVm::new("child", "child".to_string())).unwrap();
    /// let expansion = ExpandableState::new();
    /// root.compose_expansion(expansion.clone()).unwrap();
    /// assert_eq!(walk_expanded(&root).unwrap().len(), 1);
    ///
    /// expansion.expand();
    /// assert_eq!(walk_expanded(&root).unwrap().len(), 2);
    /// ```
    ///
    /// # Errors
    ///
    /// Returns [`VmxError::InvalidArgument`] when the node already composes
    /// an expansion state; the first composition stays.
    pub fn compose_expansion(&self, expansion: ExpandableState) -> VmxResult<()> {
        self.inner.expansion.set(expansion).map_err(|_| {
            VmxError::InvalidArgument("the node already composes an expansion state".to_string())
        })
    }

    /// Returns the composed expansion state, when present.
    pub fn expansion(&self) -> Option<&ExpandableState> {
        self.inner.expansion.get()
    }

    /// Returns this node's own consumer node data. Clones of this node share it.
    pub fn node_data(&self) -> &N {
        &self.inner.node_data
    }

    /// Returns this node's stable identity.
    pub fn id(&self) -> usize {
        self.inner.component.id()
    }

    /// Returns this node's name.
    pub fn name(&self) -> String {
        self.inner.component.name()
    }

    /// Returns the canonical component family discriminator.
    pub fn view_model_type(&self) -> crate::ViewModelType {
        self.inner.component.view_model_type()
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
        self.attach_child(&child, false)
    }

    /// Removes `child` from this node without disposing it.
    pub fn remove_child(&self, child: &Self) -> VmxResult<()> {
        self.reject_structural_reentry()?;
        self.try_children()?;
        let removed = {
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
        };
        let Some((removed, index)) = removed else {
            return Ok(());
        };
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
        self.attach_child(child, true)
    }

    fn attach_child(&self, child: &Self, explicit_reparent: bool) -> VmxResult<()> {
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
                    let reparented = explicit_reparent || old_parent.is_some();
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
    ///
    /// # Panics
    ///
    /// Panics when the children factory returns structurally invalid output
    /// (a duplicate child, this node or an ancestor, or an already-parented
    /// child) or re-enters structural materialization on its receiver. This
    /// is the fail-fast accessor of spec/18 §4 and ADR-0127, matching Swift's
    /// `children`; use [`try_children`](Self::try_children) to receive the
    /// error instead.
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
    ///
    /// # Panics
    ///
    /// Materializes this node's children through [`children`](Self::children), so it panics
    /// under the same conditions.
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
    ///
    /// # Panics
    ///
    /// Materializes the parent's children through [`children`](Self::children), so it panics
    /// under the same conditions.
    pub fn is_first(&self) -> bool {
        self.parent()
            .and_then(|parent| parent.children().first().cloned())
            .map(|first| first == *self)
            .unwrap_or(false)
    }

    /// Reports whether this is the last child of its parent.
    ///
    /// # Panics
    ///
    /// Materializes the parent's children through [`children`](Self::children), so it panics
    /// under the same conditions.
    pub fn is_last(&self) -> bool {
        self.parent()
            .and_then(|parent| parent.children().last().cloned())
            .map(|last| last == *self)
            .unwrap_or(false)
    }

    /// Constructs this node and, when configured eager, its direct children.
    ///
    /// The eager option applies to this node's children only. It continues
    /// deeper only through children that are eager themselves.
    pub fn construct(&self) -> VmxResult<()> {
        if !*lock(&self.inner.eager_children) {
            return self.inner.component.construct();
        }
        // Cascade inside this node's own Constructing phase: a rejected
        // transition (disposed or already constructed) constructs no child, and
        // the parent reaches Constructed only after every child that this
        // cascade constructs (spec/18 §3).
        self.inner.component.construct_with(|| {
            for child in self.try_children()? {
                self.inner
                    .component
                    .core
                    .transition_child(&child, crate::LifecycleOperation::Construct)?;
            }
            Ok(())
        })
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
        let discarded = {
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
            discarded
        };
        // Discarded children are dropped after the topology gate is released.
        let was_materialized = discarded.is_some();
        drop(discarded);
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
        let parked = std::mem::take(&mut *lock(&self.inner.parked_attach_items));
        // Parked items are dropped after the lock is released.
        drop(parked);
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
                // A factory that re-entered materialization on its receiver
                // (for example through `is_leaf` or `children`) received the
                // re-entry error, and `children` turned it into a panic. Report
                // the re-entry as this call's error instead of re-raising it.
                let reentered = {
                    let state = lock(&self.inner.materializing_children.0);
                    state.epoch == epoch && state.reentered_epoch == epoch
                };
                self.finish_children_materialization(epoch);
                if reentered {
                    drop(error);
                    return Err(VmxError::InvalidArgument(
                        "children factory re-entered structural materialization".to_string(),
                    ));
                }
                resume_unwind(error);
            }
        };
        let mut owner_released = false;
        let committed = (|| -> VmxResult<Vec<Self>> {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            #[cfg(test)]
            if let Some((node, hook)) = lock(&MATERIALIZATION_VALIDATION_HOOK).as_ref() {
                if *node == self.id() {
                    hook();
                }
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

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> Clone
    for HierarchicalVm<M, N>
{
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

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> PartialEq
    for HierarchicalVm<M, N>
{
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> Eq
    for HierarchicalVm<M, N>
{
}

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> VmNode
    for HierarchicalVm<M, N>
{
    fn when_lifecycle_settled(&self, callback: crate::LifecycleSettleCallback) -> bool {
        self.inner.component.core.when_settled(callback)
    }

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

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static> TreeNode
    for HierarchicalVm<M, N>
{
    /// Returns [`HierarchicalVm::try_children`], which [`walk`],
    /// [`walk_expanded`] and [`find`] use. Invalid factory output returns the
    /// error and leaves this node unmaterialized and retryable (ADR-0170).
    fn try_children_nodes(&self) -> VmxResult<Vec<TreeNodeRef>> {
        Ok(self
            .try_children()?
            .into_iter()
            .map(TreeNodeRef::new)
            .collect())
    }

    /// Returns the composed [`ExpandableState`], when present, so
    /// [`walk_expanded`] stops at a collapsed node.
    fn expandable(&self) -> Option<&dyn Expandable> {
        self.inner
            .expansion
            .get()
            .map(|expansion| expansion as &dyn Expandable)
    }
}

#[derive(Clone)]
/// Immutable builder for [`HierarchicalVm`].
///
/// [`new`](Self::new) builds a node without data (`N = ()`), and
/// [`with_node_data`](Self::with_node_data) builds a root that carries
/// consumer node data (ADR-0202).
pub struct HierarchicalVmBuilder<
    M: Clone + PartialEq + Send + Sync + 'static,
    N: Send + Sync + 'static = (),
> {
    model: Option<M>,
    node_data: N,
    children_factory: Option<HierChildrenFactory<M, N>>,
    services: Option<(MessageHub, NullDispatcher)>,
    hint: Option<String>,
    eager_children: bool,
}

impl<M: Clone + PartialEq + Send + Sync + 'static> Default for HierarchicalVmBuilder<M> {
    fn default() -> Self {
        Self::with_node_data(())
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> HierarchicalVmBuilder<M> {
    /// Creates an empty builder with lazy children.
    pub fn new() -> Self {
        Self::default()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, N: Send + Sync + 'static>
    HierarchicalVmBuilder<M, N>
{
    /// Creates an empty builder with lazy children for a root that carries
    /// `node_data`.
    pub fn with_node_data(node_data: N) -> Self {
        Self {
            model: None,
            node_data,
            children_factory: None,
            services: None,
            hint: Some(String::new()),
            eager_children: false,
        }
    }

    /// Sets the required root model.
    pub fn model(mut self, model: M) -> Self {
        self.model = Some(model);
        self
    }

    /// Sets the recursive children factory.
    pub fn children_factory<F>(mut self, factory: F) -> Self
    where
        F: Fn(&HierarchicalVm<M, N>) -> Vec<HierarchicalVm<M, N>> + Send + Sync + 'static,
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

    /// Controls whether construction eagerly materializes and constructs this
    /// node's children.
    ///
    /// The option applies to this node's children only. It continues deeper
    /// only through children that are eager themselves.
    pub fn eager_children(mut self, eager: bool) -> Self {
        self.eager_children = eager;
        self
    }

    /// Validates required fields and builds a hierarchy root.
    pub fn build(self) -> VmxResult<HierarchicalVm<M, N>> {
        let model = self
            .model
            .ok_or_else(|| VmxError::BuilderValidation("model is required".to_string()))?;
        let factory = self.children_factory.ok_or_else(|| {
            VmxError::BuilderValidation("children_factory is required".to_string())
        })?;
        let (hub, _dispatcher) = self
            .services
            .ok_or_else(|| VmxError::BuilderValidation("services are required".to_string()))?;
        let node_data = self.node_data;
        let node = HierarchicalVm::with_node_data(
            "HierarchicalVm",
            model,
            node_data,
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
///
/// The walk yields `root`, then descends through each node's
/// [`TreeNode::try_children_nodes`]: the children of a `CompositeVm` or
/// `GroupVm`, the present components of an aggregate in `component_1`,
/// `component_2`, … order, and the children of a `HierarchicalVm` (spec/13
/// §2, ADR-0207). A leaf yields only itself.
///
/// ```
/// use vmx::{walk, ComponentVm, CompositeVm};
///
/// let root = CompositeVm::new("root");
/// root.add(ComponentVm::<()>::new("a")).unwrap();
/// root.add(ComponentVm::<()>::new("b")).unwrap();
/// assert_eq!(walk(&root).unwrap().len(), 3);
/// ```
///
/// # Errors
///
/// Returns the error of [`TreeNode::try_children_nodes`], such as
/// [`VmxError::InvalidArgument`] for a [`HierarchicalVm`] whose lazy children
/// factory returns structurally invalid output (spec/13 §6, ADR-0170). That
/// node stays unmaterialized, and a later walk retries the factory.
pub fn walk<T: TreeNode>(root: &T) -> VmxResult<Vec<TreeNodeRef>> {
    let mut nodes = Vec::new();
    walk_into(TreeNodeRef::new(root.clone()), false, &mut nodes)?;
    Ok(nodes)
}

/// Returns the first depth-first node matching `predicate`.
///
/// The search visits nodes in [`walk`] order, calls `predicate` at most once
/// per visited node, and stops at the first match.
///
/// # Errors
///
/// Returns the error of [`TreeNode::try_children_nodes`], as [`walk`] does,
/// when the search reaches a node whose children fail to load before it finds
/// a match.
pub fn find<T: TreeNode, F>(root: &T, predicate: F) -> VmxResult<Option<TreeNodeRef>>
where
    F: Fn(&TreeNodeRef) -> bool,
{
    find_inner(TreeNodeRef::new(root.clone()), &predicate)
}

fn find_inner<F>(node: TreeNodeRef, predicate: &F) -> VmxResult<Option<TreeNodeRef>>
where
    F: Fn(&TreeNodeRef) -> bool,
{
    if predicate(&node) {
        return Ok(Some(node));
    }
    for child in node.try_children_nodes()? {
        if let Some(found) = find_inner(child, predicate)? {
            return Ok(Some(found));
        }
    }
    Ok(None)
}

/// Returns a depth-first snapshot while skipping collapsed descendants.
///
/// It descends as [`walk`] does, but a node whose
/// [`TreeNode::expandable`] capability reports collapsed contributes only
/// itself (spec/13 §5). A node without the capability counts as expanded.
///
/// # Errors
///
/// Returns the error of [`TreeNode::try_children_nodes`], as [`walk`] does,
/// for a descended node whose children fail to load. A collapsed node's
/// children are not read.
pub fn walk_expanded<T: TreeNode>(root: &T) -> VmxResult<Vec<TreeNodeRef>> {
    let mut nodes = Vec::new();
    walk_into(TreeNodeRef::new(root.clone()), true, &mut nodes)?;
    Ok(nodes)
}

fn walk_into(
    node: TreeNodeRef,
    expanded_only: bool,
    nodes: &mut Vec<TreeNodeRef>,
) -> VmxResult<()> {
    let descend = !expanded_only || node.expandable().is_none_or(Expandable::is_expanded);
    let children = if descend {
        Some(node.try_children_nodes())
    } else {
        None
    };
    nodes.push(node);
    for child in children.transpose()?.unwrap_or_default() {
        walk_into(child, expanded_only, nodes)?;
    }
    Ok(())
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
        *lock(&MATERIALIZATION_VALIDATION_HOOK) = Some((
            root.id(),
            Box::new(move || {
                at_boundary_tx.send(()).unwrap();
                captured_resume.lock().unwrap().recv().unwrap();
            }),
        ));

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
