"""Tree widget built from a VMx hierarchy via ``walk(root)``."""

from __future__ import annotations

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from vmx.components.protocols import ComponentVMProto
from vmx.tree import walk


def populate_tree(tree: Tree[ComponentVMProto], root: ComponentVMProto) -> None:
    """Fill *tree* with one node per VM in depth-first order.

    Each node label is ``name (Type, Status)``; its data is the VM instance.
    The tree's built-in root node is hidden; a synthetic root is added instead.
    """
    tree.clear()
    _add_subtree(tree.root, root)
    tree.root.expand_all()


def _node_label(vm: ComponentVMProto) -> str:
    return f"{vm.name} ({vm.type.value}, {vm.status.name})"


def _add_subtree(
    parent_node: TreeNode[ComponentVMProto],
    vm: ComponentVMProto,
) -> TreeNode[ComponentVMProto]:
    node = parent_node.add(_node_label(vm), data=vm)
    if hasattr(vm, "__iter__"):
        try:
            for child in vm:
                if isinstance(child, ComponentVMProto):
                    _add_subtree(node, child)
        except TypeError:
            pass
    return node


def refresh_node_label(node: TreeNode[ComponentVMProto]) -> None:
    """Update the label of *node* to reflect the VM's current state."""
    if node.data is not None:
        node.set_label(_node_label(node.data))
