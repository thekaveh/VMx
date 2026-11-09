use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use vmx::{
    find, walk, walk_expanded, AggregateVm3, ComponentVm, CompositeVm, ConstructionStatus,
    Expandable, ExpandableState, GroupVm, HierarchicalVm, LifecycleSettleCallback, MessageHub,
    NullDispatcher, ParentHandle, TreeNode, TreeNodeRef, VmNode, VmxError, VmxResult,
};

/// A node type for trees that mix VM types. A Rust container holds one child
/// type, so a mixed tree uses an enum that forwards to the wrapped VM.
#[derive(Clone)]
enum Node {
    Leaf(ComponentVm),
    Composite(CompositeVm<Node>),
    Group(GroupVm<Node>),
    Aggregate(AggregateVm3<Node, Node, Node>),
    Hierarchy(HierarchicalVm<String>),
}

macro_rules! each {
    ($node:expr, $vm:ident => $body:expr) => {
        match $node {
            Node::Leaf($vm) => $body,
            Node::Composite($vm) => $body,
            Node::Group($vm) => $body,
            Node::Aggregate($vm) => $body,
            Node::Hierarchy($vm) => $body,
        }
    };
}

impl PartialEq for Node {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl VmNode for Node {
    fn id(&self) -> usize {
        each!(self, vm => VmNode::id(vm))
    }

    fn construct(&self) -> VmxResult<()> {
        each!(self, vm => VmNode::construct(vm))
    }

    fn destruct(&self) -> VmxResult<()> {
        each!(self, vm => VmNode::destruct(vm))
    }

    fn dispose(&self) -> VmxResult<()> {
        each!(self, vm => VmNode::dispose(vm))
    }

    fn status(&self) -> ConstructionStatus {
        each!(self, vm => VmNode::status(vm))
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        each!(self, vm => VmNode::set_parent_id(vm, parent_id))
    }

    fn parent_id(&self) -> Option<usize> {
        each!(self, vm => VmNode::parent_id(vm))
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        each!(self, vm => VmNode::set_parent_handle(vm, parent))
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        each!(self, vm => VmNode::parent_handle(vm))
    }

    fn set_current_flag(&self, is_current: bool) {
        each!(self, vm => VmNode::set_current_flag(vm, is_current))
    }

    fn commit_current_flag(&self, is_current: bool) -> bool {
        each!(self, vm => VmNode::commit_current_flag(vm, is_current))
    }

    fn publish_current_flag(&self, is_current: bool) {
        each!(self, vm => VmNode::publish_current_flag(vm, is_current))
    }

    fn is_current(&self) -> bool {
        each!(self, vm => VmNode::is_current(vm))
    }

    fn when_lifecycle_settled(&self, callback: LifecycleSettleCallback) -> bool {
        each!(self, vm => VmNode::when_lifecycle_settled(vm, callback))
    }

    fn lifecycle_publication_pending(&self) -> bool {
        each!(self, vm => VmNode::lifecycle_publication_pending(vm))
    }
}

impl TreeNode for Node {
    fn try_children_nodes(&self) -> VmxResult<Vec<TreeNodeRef>> {
        each!(self, vm => vm.try_children_nodes())
    }

    fn expandable(&self) -> Option<&dyn Expandable> {
        each!(self, vm => vm.expandable())
    }
}

/// Names the nodes of a test tree by identity.
#[derive(Default)]
struct Names(HashMap<usize, &'static str>);

impl Names {
    fn leaf(&mut self, name: &'static str) -> ComponentVm {
        let vm = ComponentVm::new(name);
        self.0.insert(vm.id(), name);
        vm
    }

    fn composite(&mut self, name: &'static str) -> CompositeVm<Node> {
        let vm = CompositeVm::new(name);
        self.0.insert(vm.id(), name);
        vm
    }

    fn hierarchy(&mut self, name: &'static str) -> HierarchicalVm<String> {
        let vm = HierarchicalVm::new(name, name.to_string());
        self.0.insert(vm.id(), name);
        vm
    }

    fn name<T: VmNode>(&mut self, name: &'static str, vm: T) -> T {
        self.0.insert(vm.id(), name);
        vm
    }

    fn of(&self, nodes: &[TreeNodeRef]) -> Vec<&'static str> {
        nodes.iter().map(|node| self.0[&node.id()]).collect()
    }
}

/// The UTIL-001 catalog tree: `root` holds leaf `a` and composite `b`, and `b`
/// holds `b1` and `b2`.
fn catalog_tree(names: &mut Names) -> CompositeVm<Node> {
    let root = names.composite("root");
    let b = names.composite("b");
    b.add(Node::Leaf(names.leaf("b1"))).unwrap();
    b.add(Node::Leaf(names.leaf("b2"))).unwrap();
    root.add(Node::Leaf(names.leaf("a"))).unwrap();
    root.add(Node::Composite(b)).unwrap();
    root
}

/// UTIL-001 — walk yields root then descendants in DFS pre-order
#[test]
fn walk_yields_depth_first_preorder() {
    let mut names = Names::default();
    let root = catalog_tree(&mut names);

    let nodes = walk(&root).unwrap();

    assert_eq!(names.of(&nodes), vec!["root", "a", "b", "b1", "b2"]);
    assert!(nodes[0].downcast::<CompositeVm<Node>>() == Some(root.clone()));
    // A handle wraps the container's child type.
    assert!(matches!(
        nodes[2].downcast::<Node>(),
        Some(Node::Composite(_))
    ));
}

/// UTIL-001 — a leaf yields exactly itself
#[test]
fn walk_of_a_leaf_yields_only_the_leaf() {
    let leaf = ComponentVm::new("leaf");

    let nodes = walk(&leaf).unwrap();

    assert_eq!(nodes, vec![TreeNodeRef::new(leaf.clone())]);
    assert!(nodes[0].downcast::<ComponentVm>() == Some(leaf));
}

/// Hierarchical nodes walk in the same pre-order (spec/13 §6).
#[test]
fn walk_yields_hierarchical_preorder() {
    let root = sample_tree();

    let names = models(walk(&root).unwrap());

    assert_eq!(names, vec!["root", "a", "b", "b1", "b2"]);
}

/// UTIL-002 — walk skips empty aggregate slots
///
/// A builder-made aggregate fills its slots from their factories at
/// construction. Before that, every slot is empty and `walk` yields only the
/// aggregate.
#[test]
fn walk_skips_empty_child_slots() {
    let mut names = Names::default();
    let component = |name: &'static str| {
        move || ComponentVm::with_model(name, 0, MessageHub::new(), NullDispatcher::new())
    };
    let aggregate = AggregateVm3::<ComponentVm<i32>, ComponentVm<i32>, ComponentVm<i32>>::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(component("one"))
        .component_2(component("two"))
        .component_3(component("three"))
        .build()
        .unwrap();
    let aggregate = names.name("aggregate", aggregate);

    assert_eq!(names.of(&walk(&aggregate).unwrap()), vec!["aggregate"]);

    aggregate.construct().unwrap();
    names.name("one", aggregate.component_1().unwrap());
    names.name("two", aggregate.component_2().unwrap());
    names.name("three", aggregate.component_3().unwrap());
    assert_eq!(
        names.of(&walk(&aggregate).unwrap()),
        vec!["aggregate", "one", "two", "three"]
    );
}

/// UTIL-002 — walk lists a group's members and an aggregate's slots in order
#[test]
fn walk_descends_into_groups_and_aggregate_slots_in_order() {
    let mut names = Names::default();
    let group = names.name("group", GroupVm::new("group"));
    group.add(names.leaf("g1")).unwrap();
    group.add(names.leaf("g2")).unwrap();
    assert_eq!(names.of(&walk(&group).unwrap()), vec!["group", "g1", "g2"]);

    let (first, second, third) = (names.leaf("c1"), names.leaf("c2"), names.leaf("c3"));
    let aggregate = names.name(
        "aggregate",
        AggregateVm3::new("aggregate", first, second, third),
    );
    let nodes = walk(&aggregate).unwrap();
    assert_eq!(names.of(&nodes), vec!["aggregate", "c1", "c2", "c3"]);
    assert!(nodes[1].downcast::<ComponentVm>() == aggregate.component_1());
}

/// UTIL-003 — find returns first matching node and short-circuits
#[test]
fn find_returns_first_match_and_short_circuits() {
    let mut names = Names::default();
    let root = catalog_tree(&mut names);
    let b1 = names
        .0
        .iter()
        .find(|(_, name)| **name == "b1")
        .map(|(id, _)| *id)
        .unwrap();
    let visited = Arc::new(Mutex::new(Vec::new()));
    let visited_inner = visited.clone();

    let found = find(&root, move |node| {
        visited_inner.lock().unwrap().push(node.id());
        node.id() == b1
    })
    .unwrap()
    .unwrap();

    assert_eq!(found.id(), b1);
    assert!(matches!(found.downcast::<Node>(), Some(Node::Leaf(_))));
    let visited = visited.lock().unwrap().clone();
    let visited = visited.iter().map(|id| names.0[id]).collect::<Vec<_>>();
    assert_eq!(visited, vec!["root", "a", "b", "b1"]);
}

/// UTIL-003 — find over a hierarchy returns the first match
#[test]
fn find_returns_first_hierarchical_match() {
    let root = sample_tree();

    let found = find(&root, |node| {
        node.downcast::<HierarchicalVm<String>>()
            .is_some_and(|node| node.model() == "b1")
    })
    .unwrap()
    .unwrap();

    assert_eq!(
        found.downcast::<HierarchicalVm<String>>().unwrap().model(),
        "b1"
    );
}

/// `walk_expanded` descends into composites, groups and aggregates, and stops
/// at a collapsed expandable container (spec/13 §5, ADR-0207).
#[test]
fn walk_expanded_descends_containers_and_stops_at_a_collapsed_node() {
    let mut names = Names::default();
    let root = names.composite("root");
    let group = names.name("group", GroupVm::new("group"));
    let folder = names.hierarchy("folder");
    folder.add_child(names.hierarchy("file")).unwrap();
    let expansion = ExpandableState::new();
    folder.compose_expansion(expansion.clone()).unwrap();
    let (x, y) = (names.leaf("x"), names.leaf("y"));
    let aggregate = names.name(
        "aggregate",
        AggregateVm3::new(
            "aggregate",
            Node::Leaf(x),
            Node::Hierarchy(folder),
            Node::Leaf(y),
        ),
    );
    group.add(Node::Aggregate(aggregate)).unwrap();
    root.add(Node::Group(group)).unwrap();

    assert_eq!(
        names.of(&walk_expanded(&root).unwrap()),
        vec!["root", "group", "aggregate", "x", "folder", "y"]
    );
    assert_eq!(
        names.of(&walk(&root).unwrap()),
        vec!["root", "group", "aggregate", "x", "folder", "file", "y"]
    );

    expansion.expand();
    assert_eq!(
        names.of(&walk_expanded(&root).unwrap()),
        vec!["root", "group", "aggregate", "x", "folder", "file", "y"]
    );
}

fn leaf(name: &str) -> HierarchicalVm<String> {
    HierarchicalVm::new(name, name.to_string())
}

fn sample_tree() -> HierarchicalVm<String> {
    let root = leaf("root");
    let a = leaf("a");
    let b = leaf("b");
    let b1 = leaf("b1");
    let b2 = leaf("b2");
    b.add_child(b1).unwrap();
    b.add_child(b2).unwrap();
    root.add_child(a).unwrap();
    root.add_child(b).unwrap();
    root
}

fn models(nodes: Vec<TreeNodeRef>) -> Vec<String> {
    nodes
        .iter()
        .map(|node| node.downcast::<HierarchicalVm<String>>().unwrap().model())
        .collect()
}

/// Tree walks over invalid factory output (spec/13 §6, ADR-0170, #1060):
/// `walk`, `walk_expanded` and `find` return the factory error instead of
/// panicking, and the node stays unmaterialized so a later walk retries.
#[test]
fn walks_return_invalid_factory_output_error_and_stay_retryable() {
    let dup = leaf("dup");
    let other = leaf("other");
    let snapshot = Arc::new(Mutex::new(vec![dup.clone(), dup.clone()]));
    let captured = Arc::clone(&snapshot);
    let calls = Arc::new(Mutex::new(0_usize));
    let counted = Arc::clone(&calls);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            *counted.lock().unwrap() += 1;
            captured.lock().unwrap().clone()
        },
        false,
        MessageHub::new(),
    );
    let is_factory_error = |error: &VmxError| matches!(error, VmxError::InvalidArgument(message) if message.contains("factory"));

    assert!(walk(&root).is_err_and(|error| is_factory_error(&error)));
    assert!(walk_expanded(&root).is_err_and(|error| is_factory_error(&error)));
    assert!(find(&root, |_| false).is_err_and(|error| is_factory_error(&error)));
    assert_eq!(*calls.lock().unwrap(), 3, "each walk retries the factory");
    assert!(
        dup.parent().is_none(),
        "a rejected snapshot assigns no parent"
    );
    assert!(!root.is_children_materialized());

    // A predicate that matches the root returns before any child is read.
    let target = root.id();
    assert_eq!(
        find(&root, move |node| node.id() == target)
            .unwrap()
            .map(|node| node.id()),
        Some(root.id())
    );
    assert_eq!(*calls.lock().unwrap(), 3);

    *snapshot.lock().unwrap() = vec![dup.clone(), other.clone()];
    assert_eq!(walk(&root).unwrap().len(), 3);
    assert_eq!(walk_expanded(&root).unwrap().len(), 3);
    let wanted = other.id();
    let found = find(&root, move |node| node.id() == wanted)
        .unwrap()
        .unwrap();
    assert!(found.downcast::<HierarchicalVm<String>>() == Some(other.clone()));
}
