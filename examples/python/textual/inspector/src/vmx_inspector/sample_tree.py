"""Builds the demo VMx hierarchy used by the inspector."""

from __future__ import annotations

from typing import Any, cast

from vmx.components import ComponentVM, ComponentVMOf, ReadonlyComponentVMOf
from vmx.composites import CompositeVM, CompositeVMOf
from vmx.groups import GroupVM, GroupVMBuilder
from vmx.messages import Message
from vmx.services import MessageHub, RxDispatcher


def build_sample_tree() -> tuple[CompositeVM[Any], MessageHub[Message], RxDispatcher]:
    """Return ``(root, hub, dispatcher)`` for the demo VM tree.

    Tree shape::

        app (CompositeVM)
        ├── header (ComponentVMOf[dict[str, str]])
        ├── workspace (GroupVM)
        │   ├── editor (ComponentVMOf[str])
        │   ├── terminal (ComponentVM)
        │   └── inspector (ReadonlyComponentVMOf[int])
        └── sidebar (CompositeVMOf[str, ComponentVMOf[str]])
    """
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()

    # ComponentVMOf.builder() returns ComponentVMOfBuilder[Never] when the
    # generic parameter isn't carried by a subclass (the showcase pattern is
    # to subclass ComponentVMOf[M]; the inspector deliberately demonstrates
    # the unsubclassed-builder path). Cast at the boundary so mypy --strict
    # accepts the .model(...) call without per-line type:ignores.
    header = cast(
        "ComponentVMOf[dict[str, str]]",
        ComponentVMOf.builder()
        .name("header")
        .services(hub, dispatcher)
        .model({"title": "VMx Inspector"})
        .build(),
    )

    editor = cast(
        "ComponentVMOf[str]",
        ComponentVMOf.builder()
        .name("editor")
        .services(hub, dispatcher)
        .model("untitled")
        .build(),
    )

    terminal: ComponentVM = (
        ComponentVM.builder().name("terminal").services(hub, dispatcher).build()
    )

    inspector_vm = cast(
        "ReadonlyComponentVMOf[int]",
        ReadonlyComponentVMOf.builder()
        .name("inspector")
        .services(hub, dispatcher)
        .model(42)
        .build(),
    )

    workspace = cast(
        "GroupVM[Any]",
        GroupVMBuilder()
        .name("workspace")
        .services(hub, dispatcher)
        .children(lambda: [editor, terminal, inspector_vm])
        .build(),
    )

    # The builders below are Never-parameterized without a subclass; mypy
    # can't infer through the chain. The runtime behavior is correct because
    # the builders forward values without enforcing the generic at call time.
    sidebar = cast(
        "CompositeVMOf[str, ComponentVMOf[str]]",
        CompositeVMOf.builder()
        .name("sidebar")
        .services(hub, dispatcher)
        .children_models(lambda: ["files", "git", "search"])
        .child_model_to_child_view_model(
            lambda m: cast(
                "ComponentVMOf[str]",
                ComponentVMOf.builder()
                .name(m)
                .services(hub, dispatcher)
                .model(m)
                .build(),
            )
        )
        .build(),
    )

    root = cast(
        "CompositeVM[Any]",
        CompositeVM.builder()
        .name("app")
        .services(hub, dispatcher)
        .children(lambda: [header, workspace, sidebar])
        .build(),
    )

    root.construct()

    return root, hub, dispatcher
