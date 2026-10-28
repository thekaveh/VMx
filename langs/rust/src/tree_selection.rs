//! Opt-in single current node for a hierarchical tree.
//!
//! Spec: `spec/18-hierarchical-vm.md` §10; ADR-0164.

use crate::{
    finish_with_first_failure, lock, retain_first_failure, Arc, AtomicU64, AtomicUsize,
    ConstructionStatus, HashMap, HashSet, HierarchicalVm, MessageHub, Mutex, Ordering,
    Subscription, ValueStream, VmxError, VmxResult, Weak,
};

/// Hub subscriptions keyed by [`MessageHub::identity`].
type HubSubscriptions = HashMap<usize, Subscription>;

/// One current node for the tree under a root [`HierarchicalVm`].
///
/// A tree node cannot be the current item of a container, so a consumer that
/// needs one current node per tree composes this helper on a tree node, its
/// *root* (spec/18 §10, ADR-0164). The helper adds no member to
/// [`HierarchicalVm`] and implements no capability on the nodes.
///
/// - [`can_select`](Self::can_select) is true when walking parent links from a
///   node reaches the root and no node on that path is
///   [`Disposed`](ConstructionStatus::Disposed). It reads only parent links and
///   status, so it never materializes children.
/// - [`select`](Self::select) makes a member current and
///   [`clear`](Self::clear) clears it. Neither navigates: they do not
///   materialize, expand, construct, move or publish anything.
/// - While a node is current, the helper watches the path from that node to
///   the root. It clears the selection when the node leaves the tree: a
///   removal, a transfer out of the tree, an ancestor's child-cache
///   invalidation, or the disposal of the node or an ancestor. A move inside
///   the tree keeps the selection.
/// - [`current_changed`](Self::current_changed) is a hot stream that emits
///   once for every effective change. The owning view model forwards it to its
///   own property notification (chapter 14 rule 6).
///
/// Clones share one selection. The helper is `Send + Sync`, like
/// [`HierarchicalVm`]: it keeps its state behind a lock that it never holds
/// while it reads the tree, subscribes to a hub, or emits. A revision counter
/// discards a stale re-check, so a re-check that started before a newer
/// [`select`](Self::select) cannot clear the newer selection. The helper keeps
/// a handle to the root but never disposes or detaches a node. Dropping the
/// last clone releases its hub subscriptions; call [`dispose`](Self::dispose)
/// to also complete the change stream.
///
/// ```
/// use std::sync::{Arc, Mutex};
/// use vmx::{HierarchicalVm, TreeSelection};
///
/// let root = HierarchicalVm::new("root", "root".to_string());
/// let child = HierarchicalVm::new("child", "child".to_string());
/// root.add_child(child.clone()).unwrap();
///
/// let selection = TreeSelection::new(&root);
/// let seen = Arc::new(Mutex::new(Vec::new()));
/// let sink = Arc::clone(&seen);
/// let _subscription = selection
///     .current_changed()
///     .subscribe(move |node| sink.lock().unwrap().push(node.map(|node| node.model())));
///
/// selection.select(&child).unwrap();
/// assert!(selection.current() == Some(child.clone()));
///
/// // Removing the current node clears the selection.
/// root.remove_child(&child).unwrap();
/// assert!(selection.current().is_none());
/// assert_eq!(*seen.lock().unwrap(), vec![Some("child".to_string()), None]);
/// ```
#[derive(Clone)]
pub struct TreeSelection<M: Clone + PartialEq + Send + Sync + 'static> {
    shared: Arc<SelectionShared<M>>,
}

struct SelectionShared<M: Clone + PartialEq + Send + Sync + 'static> {
    root: HierarchicalVm<M>,
    state: Mutex<SelectionState<M>>,
    /// Mirrors `SelectionState::revision` for the emission predicate, which
    /// runs under the stream lock and so must not take the state lock.
    revision: AtomicU64,
    /// Identity of the last emitted node, or 0 for `None`. Node identities
    /// start at 1.
    last_emitted: AtomicUsize,
    changed: ValueStream<Option<HierarchicalVm<M>>>,
    #[cfg(test)]
    hub_deliveries: AtomicUsize,
}

struct SelectionState<M: Clone + PartialEq + Send + Sync + 'static> {
    disposed: bool,
    current: Option<HierarchicalVm<M>>,
    current_id: Option<usize>,
    /// Bumped on every change of `current`, including disposal.
    revision: u64,
    /// Bumped on every change of `watched` or `subscriptions`.
    watch_epoch: u64,
    /// Identities of the nodes on the path from `current` to the root.
    watched: HashSet<usize>,
    subscriptions: HubSubscriptions,
}

/// The result of a membership walk: the path from a node to the root.
struct MemberPath {
    ids: HashSet<usize>,
    hubs: Vec<(usize, MessageHub)>,
}

impl<M: Clone + PartialEq + Send + Sync + 'static> TreeSelection<M> {
    /// Creates an empty selection over the tree under `root`.
    ///
    /// `root` is normally a structural root, but any node qualifies. The
    /// helper keeps a handle to `root` and never takes ownership of it: it
    /// never disposes or detaches a node.
    ///
    /// ```
    /// use vmx::{HierarchicalVm, TreeSelection};
    ///
    /// let root = HierarchicalVm::new("root", 0);
    /// let selection = TreeSelection::new(&root);
    /// assert!(selection.current().is_none());
    /// assert!(selection.can_select(&root));
    /// ```
    pub fn new(root: &HierarchicalVm<M>) -> Self {
        Self {
            shared: Arc::new(SelectionShared {
                root: root.clone(),
                state: Mutex::new(SelectionState {
                    disposed: false,
                    current: None,
                    current_id: None,
                    revision: 0,
                    watch_epoch: 0,
                    watched: HashSet::new(),
                    subscriptions: HashMap::new(),
                }),
                revision: AtomicU64::new(0),
                last_emitted: AtomicUsize::new(0),
                changed: ValueStream::hot(None),
                #[cfg(test)]
                hub_deliveries: AtomicUsize::new(0),
            }),
        }
    }

    /// Returns the current node, or `None` when nothing is selected.
    ///
    /// ```
    /// use vmx::{HierarchicalVm, TreeSelection};
    ///
    /// let root = HierarchicalVm::new("root", 0);
    /// let selection = TreeSelection::new(&root);
    /// selection.select(&root).unwrap();
    /// assert!(selection.current() == Some(root.clone()));
    /// ```
    pub fn current(&self) -> Option<HierarchicalVm<M>> {
        lock(&self.shared.state).current.clone()
    }

    /// Reports whether `node` is a member of the selectable tree.
    ///
    /// It is true when the helper is not disposed, walking parent links from
    /// `node` reaches the root (the root itself qualifies), and no node on
    /// that path is [`Disposed`](ConstructionStatus::Disposed). The walk reads
    /// only parent links and status, so it never invokes a children factory.
    ///
    /// ```
    /// use vmx::{HierarchicalVm, TreeSelection};
    ///
    /// let root = HierarchicalVm::new("root", 0);
    /// let child = HierarchicalVm::new("child", 1);
    /// let detached = HierarchicalVm::new("detached", 2);
    /// root.add_child(child.clone()).unwrap();
    ///
    /// let selection = TreeSelection::new(&root);
    /// assert!(selection.can_select(&child));
    /// assert!(!selection.can_select(&detached));
    /// ```
    pub fn can_select(&self, node: &HierarchicalVm<M>) -> bool {
        if lock(&self.shared.state).disposed {
            return false;
        }
        self.shared.member_path(node).is_some()
    }

    /// Makes `node` current and starts watching its path to the root.
    ///
    /// Selecting the current node again does nothing. After
    /// [`dispose`](Self::dispose) the call does nothing and returns `Ok(())`.
    ///
    /// # Errors
    ///
    /// Returns [`VmxError::InvalidArgument`] when
    /// [`can_select`](Self::can_select) rejects `node`. The current node then
    /// keeps its value and nothing is emitted.
    ///
    /// ```
    /// use vmx::{HierarchicalVm, TreeSelection, VmxError};
    ///
    /// let root = HierarchicalVm::new("root", 0);
    /// let child = HierarchicalVm::new("child", 1);
    /// root.add_child(child.clone()).unwrap();
    /// let selection = TreeSelection::new(&root);
    ///
    /// selection.select(&child).unwrap();
    /// let stranger = HierarchicalVm::new("stranger", 2);
    /// assert!(matches!(
    ///     selection.select(&stranger),
    ///     Err(VmxError::InvalidArgument(_))
    /// ));
    /// assert!(selection.current() == Some(child.clone()));
    /// ```
    pub fn select(&self, node: &HierarchicalVm<M>) -> VmxResult<()> {
        let shared = &self.shared;
        let id = node.id();
        if lock(&shared.state).disposed {
            return Ok(());
        }
        // Membership is checked first, so a current node that left the tree
        // before the watch cleared it is rejected like any other non-member.
        let Some(path) = shared.member_path(node) else {
            return Err(VmxError::InvalidArgument(
                "node is not a member of the selection's tree".to_string(),
            ));
        };
        if lock(&shared.state).current_id == Some(id) {
            return Ok(());
        }
        let fresh = shared.subscribe_hubs(&path.hubs, &HashSet::new());
        let selected = node.clone();
        let outcome = {
            let mut state = lock(&shared.state);
            if state.disposed || state.current_id == Some(id) {
                Err((fresh, selected))
            } else {
                let previous = state.current.replace(selected);
                let released = std::mem::replace(&mut state.subscriptions, fresh);
                state.current_id = Some(id);
                state.watched = path.ids;
                state.watch_epoch += 1;
                let revision = shared.bump_revision(&mut state);
                Ok((previous, released, revision))
            }
        };
        // Handles and subscriptions drop after the state lock is released.
        match outcome {
            Err(discarded) => drop(discarded),
            Ok((previous, released, revision)) => {
                drop((previous, released));
                shared.emit(Some(node.clone()), revision);
                // The path was read before the watch started; check it again
                // so a change in between is not missed.
                shared.revalidate();
            }
        }
        Ok(())
    }

    /// Clears the selection and releases the watch.
    ///
    /// It does nothing when nothing is selected or after
    /// [`dispose`](Self::dispose).
    ///
    /// ```
    /// use vmx::{HierarchicalVm, TreeSelection};
    ///
    /// let root = HierarchicalVm::new("root", 0);
    /// let selection = TreeSelection::new(&root);
    /// selection.select(&root).unwrap();
    /// selection.clear();
    /// assert!(selection.current().is_none());
    /// ```
    pub fn clear(&self) {
        self.shared.clear_at(None);
    }

    /// Returns the hot stream of effective changes to
    /// [`current`](Self::current).
    ///
    /// It emits the new current node, or `None`, once for every effective
    /// change and replays nothing to a new subscriber. A value reaches
    /// subscribers after the state and watch are updated, so a subscriber may
    /// call [`select`](Self::select) or [`clear`](Self::clear). The stream
    /// completes on [`dispose`](Self::dispose) without a final value. The
    /// helper publishes nothing to any hub: the owning view model forwards
    /// this stream to its own property notification.
    ///
    /// ```
    /// use std::sync::{Arc, Mutex};
    /// use vmx::{ComponentVm, HierarchicalVm, TreeSelection};
    ///
    /// let owner = ComponentVm::new("explorer");
    /// let root = HierarchicalVm::new("root", 0);
    /// let selection = TreeSelection::new(&root);
    ///
    /// let forwarded = owner.clone();
    /// let _forwarding = selection
    ///     .current_changed()
    ///     .subscribe(move |_| forwarded.notify_property_changed("selected_node"));
    /// let names = Arc::new(Mutex::new(Vec::new()));
    /// let sink = Arc::clone(&names);
    /// let _local = owner
    ///     .property_changed()
    ///     .subscribe(move |name| sink.lock().unwrap().push(name.to_string()));
    ///
    /// selection.select(&root).unwrap();
    /// assert_eq!(*names.lock().unwrap(), vec!["selected_node".to_string()]);
    /// ```
    pub fn current_changed(&self) -> ValueStream<Option<HierarchicalVm<M>>> {
        self.shared.changed.clone()
    }

    /// Releases the hub subscriptions, clears the selection without emitting,
    /// and completes the change stream.
    ///
    /// Every step runs, and the first panic resumes after the last step.
    /// Afterwards [`current`](Self::current) is `None`,
    /// [`can_select`](Self::can_select) is false, and
    /// [`select`](Self::select), [`clear`](Self::clear) and tree changes do
    /// nothing. A second call does nothing. Disposal never disposes or
    /// detaches a node.
    ///
    /// ```
    /// use vmx::{HierarchicalVm, TreeSelection};
    ///
    /// let root = HierarchicalVm::new("root", 0);
    /// let selection = TreeSelection::new(&root);
    /// selection.select(&root).unwrap();
    /// selection.dispose();
    /// assert!(selection.current().is_none());
    /// assert!(!selection.can_select(&root));
    /// assert!(selection.select(&root).is_ok());
    /// assert!(selection.current().is_none());
    /// ```
    pub fn dispose(&self) {
        let shared = &self.shared;
        let (current, subscriptions) = {
            let mut state = lock(&shared.state);
            if state.disposed {
                return;
            }
            state.disposed = true;
            state.current_id = None;
            state.watched.clear();
            state.watch_epoch += 1;
            shared.bump_revision(&mut state);
            (
                state.current.take(),
                std::mem::take(&mut state.subscriptions),
            )
        };
        let mut first_failure = None;
        for subscription in subscriptions.into_values() {
            retain_first_failure(&mut first_failure, || {
                subscription.dispose();
                Ok(())
            });
        }
        retain_first_failure(&mut first_failure, || {
            drop(current);
            Ok(())
        });
        retain_first_failure(&mut first_failure, || {
            shared.changed.dispose();
            Ok(())
        });
        // Every step returns `Ok`, so only a captured panic can resume here.
        let _ = finish_with_first_failure(first_failure);
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> SelectionShared<M> {
    /// Walks parent links from `node` to the root. Returns `None` when the
    /// walk ends before the root or meets a disposed node. It never reads
    /// children, and it takes the topology gate once per step without holding
    /// the state lock.
    fn member_path(&self, node: &HierarchicalVm<M>) -> Option<MemberPath> {
        let mut ids = HashSet::new();
        let mut hubs = Vec::new();
        let mut seen_hubs = HashSet::new();
        let mut cursor = node.clone();
        loop {
            if cursor.status() == ConstructionStatus::Disposed {
                return None;
            }
            ids.insert(cursor.id());
            let hub = cursor.hub();
            if seen_hubs.insert(hub.identity()) {
                hubs.push((hub.identity(), hub));
            }
            if cursor == self.root {
                return Some(MemberPath { ids, hubs });
            }
            cursor = cursor.parent()?;
        }
    }

    /// Subscribes to every hub in `hubs` that `existing` does not contain.
    /// The caller holds no lock.
    fn subscribe_hubs(
        self: &Arc<Self>,
        hubs: &[(usize, MessageHub)],
        existing: &HashSet<usize>,
    ) -> HubSubscriptions {
        hubs.iter()
            .filter(|(identity, _)| !existing.contains(identity))
            .map(|(identity, hub)| {
                let weak: Weak<Self> = Arc::downgrade(self);
                let subscription = hub.subscribe(move |message| {
                    let Some(shared) = weak.upgrade() else {
                        return;
                    };
                    #[cfg(test)]
                    shared.hub_deliveries.fetch_add(1, Ordering::SeqCst);
                    if shared.watches(message.sender_id()) {
                        shared.revalidate();
                    }
                });
                (*identity, subscription)
            })
            .collect()
    }

    fn watches(&self, sender_id: usize) -> bool {
        lock(&self.state).watched.contains(&sender_id)
    }

    fn bump_revision(&self, state: &mut SelectionState<M>) -> u64 {
        state.revision += 1;
        self.revision.store(state.revision, Ordering::SeqCst);
        state.revision
    }

    /// Repeats the membership check for the current node. Clears the
    /// selection when the check fails, and watches the new path when the
    /// check passes and the path changed.
    fn revalidate(self: &Arc<Self>) {
        loop {
            let (revision, epoch, current, watched, subscribed) = {
                let state = lock(&self.state);
                if state.disposed {
                    return;
                }
                let Some(current) = state.current.clone() else {
                    return;
                };
                (
                    state.revision,
                    state.watch_epoch,
                    current,
                    state.watched.clone(),
                    state.subscriptions.keys().copied().collect::<HashSet<_>>(),
                )
            };
            let Some(path) = self.member_path(&current) else {
                drop(current);
                self.clear_at(Some(revision));
                return;
            };
            drop(current);
            if path.ids == watched {
                return;
            }
            // An intra-tree move changed the ancestors: watch the new path.
            let fresh = self.subscribe_hubs(&path.hubs, &subscribed);
            let outcome = {
                let mut state = lock(&self.state);
                if state.disposed || state.revision != revision || state.watch_epoch != epoch {
                    Err(fresh)
                } else {
                    state.subscriptions.extend(fresh);
                    let needed = path
                        .hubs
                        .iter()
                        .map(|(identity, _)| *identity)
                        .collect::<HashSet<_>>();
                    let stale = state
                        .subscriptions
                        .keys()
                        .filter(|identity| !needed.contains(identity))
                        .copied()
                        .collect::<Vec<_>>();
                    let released = stale
                        .iter()
                        .filter_map(|identity| state.subscriptions.remove(identity))
                        .collect::<Vec<_>>();
                    state.watched = path.ids;
                    state.watch_epoch += 1;
                    Ok(released)
                }
            };
            // Subscriptions drop after the state lock is released. Either way
            // the loop checks again: after a newer change, or after the new
            // watch started, so a change during this pass is not missed.
            drop(outcome);
        }
    }

    /// Clears the selection. With `expected`, it clears only while the
    /// revision still matches, so a stale check cannot clear a newer
    /// selection.
    fn clear_at(&self, expected: Option<u64>) {
        let (released, revision) = {
            let mut state = lock(&self.state);
            if state.disposed || state.current.is_none() {
                return;
            }
            if expected.is_some_and(|expected| expected != state.revision) {
                return;
            }
            let current = state.current.take();
            let subscriptions = std::mem::take(&mut state.subscriptions);
            state.current_id = None;
            state.watched.clear();
            state.watch_epoch += 1;
            let revision = self.bump_revision(&mut state);
            ((current, subscriptions), revision)
        };
        drop(released);
        self.emit(None, revision);
    }

    /// Emits `value` unless a newer change superseded `revision` or the value
    /// repeats the last emission.
    fn emit(&self, value: Option<HierarchicalVm<M>>, revision: u64) {
        let identity = value.as_ref().map_or(0, HierarchicalVm::id);
        self.changed.send_if(value, || {
            self.revision.load(Ordering::SeqCst) == revision
                && self.last_emitted.swap(identity, Ordering::SeqCst) != identity
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ComponentVm, NullDispatcher};
    use std::sync::mpsc;
    use std::time::Duration;

    fn node(name: &str) -> HierarchicalVm<String> {
        HierarchicalVm::new(name, name.to_string())
    }

    fn on_hub(name: &str, hub: &MessageHub) -> HierarchicalVm<String> {
        HierarchicalVm::builder()
            .model(name.to_string())
            .children_factory(|_| Vec::new())
            .services(hub.clone(), NullDispatcher::new())
            .build()
            .unwrap()
    }

    type Seen = Arc<Mutex<Vec<Option<String>>>>;

    fn record(selection: &TreeSelection<String>) -> (Seen, crate::ValueSubscription) {
        let seen: Seen = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&seen);
        let subscription = selection
            .current_changed()
            .subscribe(move |node| lock(&sink).push(node.map(|node| node.model())));
        (seen, subscription)
    }

    fn some(name: &str) -> Option<String> {
        Some(name.to_string())
    }

    /// root -> a -> aa, root -> b, each node on its own hub.
    fn tree() -> [HierarchicalVm<String>; 4] {
        let [root, a, aa, b] = ["root", "a", "aa", "b"].map(node);
        root.add_child(a.clone()).unwrap();
        a.add_child(aa.clone()).unwrap();
        root.add_child(b.clone()).unwrap();
        [root, a, aa, b]
    }

    #[test]
    fn tree_selection_is_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<TreeSelection<String>>();
    }

    #[test]
    fn selecting_the_root_works_and_root_disposal_clears() {
        let [root, ..] = tree();
        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);

        selection.select(&root).unwrap();
        assert!(selection.current() == Some(root.clone()));

        root.dispose().unwrap();
        assert!(selection.current().is_none());
        assert_eq!(*lock(&seen), vec![some("root"), None]);
    }

    #[test]
    fn root_disposal_clears_a_deep_selection() {
        let [root, _, aa, _] = tree();
        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);
        selection.select(&aa).unwrap();

        root.dispose().unwrap();

        assert!(selection.current().is_none());
        assert!(!selection.can_select(&aa));
        assert_eq!(*lock(&seen), vec![some("aa"), None]);
    }

    #[test]
    fn a_move_inside_rewatches_the_new_path() {
        let [root, a, aa, b] = tree();
        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);
        selection.select(&aa).unwrap();

        b.add_child(aa.clone()).unwrap();
        assert!(selection.current() == Some(aa.clone()));

        // The old ancestor no longer matters.
        root.remove_child(&a).unwrap();
        assert!(selection.current() == Some(aa.clone()));

        // The new ancestor does.
        root.remove_child(&b).unwrap();
        assert!(selection.current().is_none());
        assert_eq!(*lock(&seen), vec![some("aa"), None]);
    }

    #[test]
    fn an_ancestor_on_a_different_hub_still_clears() {
        let shared_hub = MessageHub::new();
        let other_hub = MessageHub::new();
        let root = on_hub("root", &shared_hub);
        let a = on_hub("a", &other_hub);
        let aa = on_hub("aa", &shared_hub);
        root.add_child(a.clone()).unwrap();
        a.add_child(aa.clone()).unwrap();

        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);
        selection.select(&aa).unwrap();
        assert_eq!(lock(&selection.shared.state).subscriptions.len(), 2);

        a.invalidate_children();
        assert!(selection.current().is_none());

        a.add_child(aa.clone()).unwrap();
        selection.select(&aa).unwrap();
        root.remove_child(&a).unwrap();
        assert!(selection.current().is_none());
        assert_eq!(*lock(&seen), vec![some("aa"), None, some("aa"), None]);
    }

    #[test]
    fn invalidating_the_root_subtree_clears() {
        let [root, _, aa, _] = tree();
        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);
        selection.select(&aa).unwrap();

        root.invalidate_subtree();

        assert!(selection.current().is_none());
        assert_eq!(*lock(&seen), vec![some("aa"), None]);
    }

    #[test]
    fn a_subscriber_may_select_reentrantly() {
        let [root, a, aa, _] = tree();
        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);
        let reentrant = selection.clone();
        let fallback = a.clone();
        let _redirect = selection.current_changed().subscribe(move |node| {
            if node.is_none() {
                reentrant.select(&fallback).unwrap();
            }
        });

        selection.select(&aa).unwrap();
        a.remove_child(&aa).unwrap();

        assert!(selection.current() == Some(a.clone()));
        assert_eq!(*lock(&seen), vec![some("aa"), None, some("a")]);
    }

    #[test]
    fn the_owner_forwards_changes_to_its_property_notification() {
        struct Explorer {
            component: ComponentVm,
            selection: TreeSelection<String>,
            _forwarding: crate::ValueSubscription,
        }

        impl Explorer {
            fn new(root: &HierarchicalVm<String>) -> Self {
                let component = ComponentVm::new("explorer");
                let selection = TreeSelection::new(root);
                let forwarded = component.clone();
                let forwarding = selection
                    .current_changed()
                    .subscribe(move |_| forwarded.notify_property_changed("selected_node"));
                Self {
                    component,
                    selection,
                    _forwarding: forwarding,
                }
            }
        }

        let [root, a, ..] = tree();
        let explorer = Explorer::new(&root);
        let names = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&names);
        let _local = explorer
            .component
            .property_changed()
            .subscribe(move |name| lock(&sink).push(name.to_string()));

        explorer.selection.select(&a).unwrap();
        explorer.selection.select(&a).unwrap();
        explorer.selection.clear();

        assert_eq!(*lock(&names), vec!["selected_node", "selected_node"]);
    }

    #[test]
    fn dispose_releases_hub_subscriptions() {
        let [root, a, aa, _] = tree();
        let selection = TreeSelection::new(&root);
        selection.select(&aa).unwrap();
        let before = selection.shared.hub_deliveries.load(Ordering::SeqCst);
        a.notify_property_changed("name");
        assert!(selection.shared.hub_deliveries.load(Ordering::SeqCst) > before);

        selection.dispose();
        let after = selection.shared.hub_deliveries.load(Ordering::SeqCst);
        a.notify_property_changed("name");
        root.remove_child(&a).unwrap();
        aa.dispose().unwrap();

        assert_eq!(
            selection.shared.hub_deliveries.load(Ordering::SeqCst),
            after
        );
        assert!(lock(&selection.shared.state).subscriptions.is_empty());
    }

    #[test]
    fn clear_releases_hub_subscriptions() {
        let [root, a, aa, _] = tree();
        let selection = TreeSelection::new(&root);
        selection.select(&aa).unwrap();
        selection.clear();
        let after = selection.shared.hub_deliveries.load(Ordering::SeqCst);

        a.notify_property_changed("name");

        assert_eq!(
            selection.shared.hub_deliveries.load(Ordering::SeqCst),
            after
        );
    }

    #[test]
    fn dropping_the_last_clone_leaks_nothing() {
        let [root, a, aa, _] = tree();
        let selection = TreeSelection::new(&root);
        selection.select(&aa).unwrap();
        let weak = Arc::downgrade(&selection.shared);

        drop(selection);
        a.notify_property_changed("name");

        assert!(weak.upgrade().is_none());
    }

    #[test]
    fn an_unrelated_message_on_a_watched_hub_is_ignored() {
        let hub = MessageHub::new();
        let root = on_hub("root", &hub);
        let a = on_hub("a", &hub);
        let other = on_hub("other", &hub);
        root.add_child(a.clone()).unwrap();
        let selection = TreeSelection::new(&root);
        let (seen, _subscription) = record(&selection);
        selection.select(&a).unwrap();
        assert_eq!(lock(&selection.shared.state).subscriptions.len(), 1);

        other.dispose().unwrap();

        assert!(selection.current() == Some(a.clone()));
        assert_eq!(*lock(&seen), vec![some("a")]);
    }

    fn within_deadline(name: &str, work: impl FnOnce() + Send + 'static) {
        let (done, finished) = mpsc::channel();
        std::thread::spawn(move || {
            work();
            let _ = done.send(());
        });
        finished
            .recv_timeout(Duration::from_secs(60))
            .unwrap_or_else(|_| panic!("{name} did not finish: possible deadlock"));
    }

    #[test]
    fn concurrent_select_and_remove_child_stay_consistent() {
        within_deadline("select vs remove_child", || {
            for _ in 0..50 {
                let [root, a, aa, b] = tree();
                let bb = node("bb");
                b.add_child(bb.clone()).unwrap();
                let selection = TreeSelection::new(&root);
                let (seen, _subscription) = record(&selection);

                let selector = {
                    let selection = selection.clone();
                    let (aa, bb) = (aa.clone(), bb.clone());
                    std::thread::spawn(move || {
                        for step in 0..100 {
                            let target = if step % 2 == 0 { &aa } else { &bb };
                            let _ = selection.select(target);
                            if step % 7 == 0 {
                                selection.clear();
                            }
                        }
                    })
                };
                let mutator = {
                    let (root, a, b) = (root.clone(), a.clone(), b.clone());
                    std::thread::spawn(move || {
                        for step in 0..100 {
                            let target = if step % 2 == 0 { &a } else { &b };
                            root.remove_child(target).unwrap();
                            root.add_child(target.clone()).unwrap();
                        }
                    })
                };
                selector.join().unwrap();
                mutator.join().unwrap();

                // A detached-then-reattached ancestor is a member again, so
                // only a non-member current would be inconsistent.
                if let Some(current) = selection.current() {
                    assert!(selection.can_select(&current));
                }
                let last = lock(&seen).last().cloned().flatten();
                assert_eq!(last, selection.current().map(|node| node.model()));

                // The watch is live after the race.
                if let Some(current) = selection.current() {
                    let ancestor = current.parent().unwrap();
                    root.remove_child(&ancestor).unwrap();
                    assert!(selection.current().is_none());
                }
            }
        });
    }

    #[test]
    fn concurrent_moves_out_always_clear() {
        within_deadline("select vs transfer out", || {
            for _ in 0..100 {
                let [root, a, aa, _] = tree();
                let elsewhere = node("elsewhere");
                let selection = TreeSelection::new(&root);
                let mover = {
                    let (elsewhere, a) = (elsewhere.clone(), a.clone());
                    std::thread::spawn(move || elsewhere.add_child(a).unwrap())
                };
                let _ = selection.select(&aa);
                mover.join().unwrap();

                assert!(
                    selection.current().is_none(),
                    "a stale member stayed current"
                );
            }
        });
    }

    #[test]
    fn concurrent_dispose_and_select_leave_an_inert_helper() {
        within_deadline("select vs dispose", || {
            for _ in 0..100 {
                let [root, _, aa, b] = tree();
                let selection = TreeSelection::new(&root);
                let selector = {
                    let selection = selection.clone();
                    let (aa, b) = (aa.clone(), b.clone());
                    std::thread::spawn(move || {
                        for step in 0..20 {
                            let _ = selection.select(if step % 2 == 0 { &aa } else { &b });
                        }
                    })
                };
                selection.dispose();
                selector.join().unwrap();

                assert!(selection.current().is_none());
                assert!(lock(&selection.shared.state).subscriptions.is_empty());
            }
        });
    }
}
