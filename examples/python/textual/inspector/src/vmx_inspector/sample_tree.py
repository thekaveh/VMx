"""Builds the demo VMx hierarchy used by the inspector."""

from __future__ import annotations

from vmx.components import ComponentVM, ComponentVMOf, ReadonlyComponentVMOf
from vmx.composites import CompositeVM, CompositeVMOf
from vmx.groups import GroupVM, GroupVMBuilder
from vmx.services import MessageHub, RxDispatcher


def build_sample_tree() -> tuple[CompositeVM, MessageHub, RxDispatcher]:
    """Return ``(root, hub, dispatcher)`` for the demo VM tree.

    Tree shape::

        app (CompositeVM)
        ├── header (ComponentVMOf[dict])
        ├── workspace (GroupVM)
        │   ├── editor (ComponentVMOf[str])
        │   ├── terminal (ComponentVM)
        │   └── inspector (ReadonlyComponentVMOf[int])
        └── sidebar (CompositeVMOf[str, ComponentVM])
    """
    hub: MessageHub = MessageHub()
    dispatcher = RxDispatcher.immediate()

    header: ComponentVMOf[dict] = (
        ComponentVMOf.builder()
        .name("header")
        .services(hub, dispatcher)
        .model({"title": "VMx Inspector"})
        .build()
    )

    editor: ComponentVMOf[str] = (
        ComponentVMOf.builder()
        .name("editor")
        .services(hub, dispatcher)
        .model("untitled")
        .build()
    )

    terminal: ComponentVM = (
        ComponentVM.builder()
        .name("terminal")
        .services(hub, dispatcher)
        .build()
    )

    inspector_vm: ReadonlyComponentVMOf[int] = (
        ReadonlyComponentVMOf.builder()
        .name("inspector")
        .services(hub, dispatcher)
        .model(42)
        .build()
    )

    workspace: GroupVM = (
        GroupVMBuilder()
        .name("workspace")
        .services(hub, dispatcher)
        .children(lambda: [editor, terminal, inspector_vm])
        .build()
    )

    sidebar: CompositeVMOf[str, ComponentVM] = (
        CompositeVMOf.builder()
        .name("sidebar")
        .services(hub, dispatcher)
        .children_models(lambda: ["files", "git", "search"])
        .child_model_to_child_view_model(
            lambda m: ComponentVMOf.builder()
            .name(m)
            .services(hub, dispatcher)
            .model(m)
            .build()
        )
        .build()
    )

    root: CompositeVM = (
        CompositeVM.builder()
        .name("app")
        .services(hub, dispatcher)
        .children(lambda: [header, workspace, sidebar])
        .build()
    )

    root.construct()

    return root, hub, dispatcher
