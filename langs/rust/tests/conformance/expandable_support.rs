use std::sync::{Arc, Mutex};

use vmx::{
    ConstructionStatus, Expandable, ExpandableState, HierarchicalVm, TreeNode, VmNode, VmxResult,
};

#[derive(Clone)]
pub(super) struct ExpandableHierarchy {
    node: HierarchicalVm<String>,
    expansion: Option<ExpandableState>,
    children: Arc<Mutex<Vec<Self>>>,
}

impl ExpandableHierarchy {
    pub(super) fn plain(name: &str) -> Self {
        Self::new(name, None)
    }

    pub(super) fn expandable(name: &str, initially_expanded: bool) -> Self {
        Self::new(
            name,
            Some(ExpandableState::with_initial(initially_expanded)),
        )
    }

    fn new(name: &str, expansion: Option<ExpandableState>) -> Self {
        Self {
            node: HierarchicalVm::new(name, name.to_string()),
            expansion,
            children: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub(super) fn add_child(&self, child: Self) {
        self.node.add_child(child.node.clone()).unwrap();
        self.children.lock().unwrap().push(child);
    }

    pub(super) fn expansion(&self) -> Option<&ExpandableState> {
        self.expansion.as_ref()
    }

    pub(super) fn model(&self) -> String {
        self.node.model()
    }
}

impl PartialEq for ExpandableHierarchy {
    fn eq(&self, other: &Self) -> bool {
        self.node == other.node
    }
}

impl VmNode for ExpandableHierarchy {
    fn id(&self) -> usize {
        self.node.id()
    }

    fn construct(&self) -> VmxResult<()> {
        self.node.construct()
    }

    fn destruct(&self) -> VmxResult<()> {
        self.node.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        self.node.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.node.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        VmNode::set_parent_id(&self.node, parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        VmNode::parent_id(&self.node)
    }
}

impl TreeNode for ExpandableHierarchy {
    fn children_nodes(&self) -> Vec<Self> {
        self.children.lock().unwrap().clone()
    }

    fn expandable(&self) -> Option<&dyn Expandable> {
        self.expansion
            .as_ref()
            .map(|expansion| expansion as &dyn Expandable)
    }
}
