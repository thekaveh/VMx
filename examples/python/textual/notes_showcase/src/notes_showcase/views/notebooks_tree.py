"""NotebooksTreeView — left pane (Tree of notebooks).

Renders the :class:`NotebooksRootVM` hierarchy via Textual's ``Tree`` widget.
Each ``TreeNode`` stores the underlying :class:`NotebookVM` in ``data`` so
selection forwarding stays a single statement (per spec §6.1).

Phase 5.b binding-gap #2: the tree walks :attr:`NotebookVM.children` (newly
added in this phase) to build a real hierarchy from the flat ``parent_id``
graph used by Phase 3.b.

Widget-class discipline (spec §6.1): the class exposes only ``compose()``,
``on_mount()`` / ``on_unmount()``, ``on_tree_node_selected()``, and a single
``action_*`` / helper-free body. All non-trivial logic lives in module-level
functions so the Phase 6 CI grep stays happy.

The tree repopulates on every :class:`~vmx.TreeStructureChangedMessage` from
the root VM (via the adapter's :func:`on_tree_structure_changed`) — a
populate-once tree never showed notebooks added at runtime (real-wiring
audit, pass 5).
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode

from notes_showcase.viewmodels.notebook_vm import NotebookVM
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM
from notes_showcase.views.adapter import on_tree_structure_changed


def _populate_tree(tree: Tree[NotebookVM], vm: NotebooksRootVM) -> None:
    tree.clear()
    tree.show_root = False
    for root_vm in vm.roots:
        _add_node(tree.root, root_vm)
    tree.root.expand()


def _add_node(parent_node: TreeNode[NotebookVM], nb_vm: NotebookVM) -> None:
    node = parent_node.add(nb_vm.notebook_name, data=nb_vm)
    for child in nb_vm.children:
        _add_node(node, child)


def _wire_bindings(view: "NotebooksTreeView") -> CompositeDisposable:
    tree = view.query_one("#notebooks_tree", Tree)
    _populate_tree(tree, view._vm)
    return CompositeDisposable(
        on_tree_structure_changed(view._vm, lambda: _populate_tree(tree, view._vm)),
    )


class NotebooksTreeView(Vertical):
    """Vertical pane: title row + the notebooks ``Tree``."""

    def __init__(self, vm: NotebooksRootVM) -> None:
        super().__init__(id="notebooks_pane")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        yield Static("Notebooks", classes="pane_title")
        yield Tree("Notebooks", id="notebooks_tree")

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_unmount(self) -> None:
        self._disposables.dispose()

    def on_tree_node_selected(self, event: Tree.NodeSelected[NotebookVM]) -> None:
        if event.node.data is not None:
            self._vm.current = event.node.data
