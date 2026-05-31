"""VMxInspectorApp — Textual TUI for exploring a VMx hierarchy."""

from __future__ import annotations

from typing import Any, cast

from reactivex.abc import DisposableBase
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

from vmx.components.protocols import ComponentVMProto
from vmx.lifecycle import StatusTransitionError
from vmx.messages.protocols import Message
from vmx.tree import walk

from vmx_inspector.details_view import DetailsView
from vmx_inspector.message_log import MessageLog
from vmx_inspector.sample_tree import build_sample_tree
from vmx_inspector.tree_view import populate_tree, refresh_node_label


def _build_parent_map(root: ComponentVMProto) -> dict[int, str]:
    """Return ``{id(child): parent.name}`` for every node reachable from *root*."""
    result: dict[int, str] = {}
    # walk() expects the internal _ComponentVMBase; the inspector deliberately
    # operates against the public ComponentVMProto, so cast at the boundary.
    for node in walk(cast(Any, root)):
        if hasattr(node, "__iter__"):
            try:
                for child in node:
                    if isinstance(child, ComponentVMProto):
                        result[id(child)] = node.name
            except TypeError:
                pass
    return result


class VMxInspectorApp(App[None]):
    """TUI inspector for a live VMx hierarchy."""

    CSS = """
    Screen {
        layout: horizontal;
    }
    #tree-pane {
        width: 2fr;
        border: solid $primary;
    }
    #right-pane {
        width: 3fr;
        layout: vertical;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "construct", "Construct"),
        Binding("d", "destruct", "Destruct"),
        Binding("r", "reconstruct", "Reconstruct"),
        Binding("x", "dispose", "Dispose"),
        Binding("s", "select_vm", "Select"),
        Binding("question_mark", "toggle_help", "Help", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._root, self._hub, self._dispatcher = build_sample_tree()
        self._hub_sub: DisposableBase | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        tree: Tree[ComponentVMProto] = Tree("VMx Tree", id="tree-pane")
        tree.guide_depth = 2
        yield tree
        with Vertical(id="right-pane"):
            yield DetailsView(id="details")
            yield MessageLog(id="msg-log")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one(Tree)
        populate_tree(tree, self._root)
        details = self.query_one(DetailsView)
        details.parent_map = _build_parent_map(self._root)
        self._hub_sub = self._hub.messages.subscribe(on_next=self._on_hub_message)

    def on_unmount(self) -> None:
        if self._hub_sub is not None:
            self._hub_sub.dispose()

    def _on_hub_message(self, msg: Message) -> None:
        self.call_from_thread(self._dispatch_hub_message, msg)

    def _dispatch_hub_message(self, msg: Message) -> None:
        log = self.query_one(MessageLog)
        log.append_message(msg)
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        tree = self.query_one(Tree)
        self._refresh_node_recursive(tree.root)

    def _refresh_node_recursive(self, node: TreeNode[ComponentVMProto]) -> None:
        if node.data is not None:
            refresh_node_label(node)
        for child in node.children:
            self._refresh_node_recursive(child)

    def _selected_vm(self) -> ComponentVMProto | None:
        tree = self.query_one(Tree)
        node = tree.cursor_node
        if node is None:
            return None
        return node.data

    def on_tree_node_highlighted(
        self, event: Tree.NodeHighlighted[ComponentVMProto]
    ) -> None:
        details = self.query_one(DetailsView)
        details.selected_vm = event.node.data

    def _safe_lifecycle(self, op: str) -> None:
        vm = self._selected_vm()
        if vm is None:
            return
        try:
            getattr(vm, op)()
        except StatusTransitionError as exc:
            self.notify(str(exc), severity="error")

    def action_construct(self) -> None:
        self._safe_lifecycle("construct")

    def action_destruct(self) -> None:
        self._safe_lifecycle("destruct")

    def action_reconstruct(self) -> None:
        self._safe_lifecycle("reconstruct")

    def action_dispose(self) -> None:
        self._safe_lifecycle("dispose")

    def action_select_vm(self) -> None:
        vm = self._selected_vm()
        if vm is None:
            return
        try:
            vm.select()
        except Exception as exc:
            self.notify(str(exc), severity="error")

    def action_toggle_help(self) -> None:
        self.action_show_help_panel()
