"""NotebookVM — leaf VM for a notebook tree node.

Capabilities (plan §3.b.5, scenario §6.2):
    ``ISelectable``, ``IExpandable``, ``ICollapsible``, ``IExpansionTogglable``,
    ``IReconstructable``.

Implemented as a subclass of :class:`vmx.ComponentVMOf` (``ComponentVMOf[M]``
is not sealed in Python, so direct inheritance is permitted). Capability ABCs
are layered on via MRO; ``ExpandableState`` provides the expand/collapse mix-in.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from vmx import (
    ComponentVMOf,
    ExpandableState,
    ICollapsible,
    IExpandable,
    IExpansionTogglable,
    IReconstructable,
    ISelectable,
    MessageHub,
    PropertyChangedMessage,
    RxDispatcher,
)
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher

from notes_showcase.models.notebook_model import NotebookModel


class NotebookVM(
    ComponentVMOf[NotebookModel],
    ISelectable,
    IExpandable,
    ICollapsible,
    IExpansionTogglable,
    IReconstructable,
):
    """Leaf VM for a single notebook node."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        model: NotebookModel,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        initially_expanded: bool = False,
        children_getter: Callable[["NotebookVM"], list["NotebookVM"]] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            initial_model=model,
            modeled_hinter=lambda m: m.name,
            on_model_changed=None,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._expansion = ExpandableState(initially_expanded)
        # Phase 5.b binding gap #2: expose child notebooks so the tree
        # widget can walk a real hierarchy. The owner (NotebooksRootVM)
        # injects a callback that closes over the flat collection and
        # filters by parent_id.
        self._children_getter = children_getter

    # ── Convenience accessors ──────────────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        """Public hub accessor — exposed so views/tests can subscribe."""
        return self._hub

    @property
    def notebook_name(self) -> str:
        """Derived display name (proxy on :attr:`model`)."""
        return str(self.model.name)

    @property
    def children(self) -> list["NotebookVM"]:
        """Child notebook VMs (``parent_id`` walk via the owner-supplied getter).

        Returns an empty list when no getter was supplied (standalone VMs do
        not know about siblings). See Phase 5.b binding gap #2 — the Textual
        ``Tree`` widget uses this to build a real hierarchy from what is, on
        disk, a flat ``parent_id`` graph.
        """
        if self._children_getter is None:
            return []
        return self._children_getter(self)

    def set_children_getter(
        self, getter: Callable[["NotebookVM"], list["NotebookVM"]] | None
    ) -> None:
        """Late-bind the children resolver (used by :class:`NotebooksRootVM`)."""
        self._children_getter = getter

    # ── IExpandable / ICollapsible / IExpansionTogglable ───────────────────
    @property
    def is_expanded(self) -> bool:
        return self._expansion.is_expanded

    def can_expand(self) -> bool:
        return self._expansion.can_expand()

    def expand(self) -> None:
        if not self._expansion.can_expand():
            return
        self._expansion.expand()
        self._emit_expansion_change()

    def can_collapse(self) -> bool:
        return self._expansion.can_collapse()

    def collapse(self) -> None:
        if not self._expansion.can_collapse():
            return
        self._expansion.collapse()
        self._emit_expansion_change()

    def can_toggle_expansion(self) -> bool:
        return self._expansion.can_toggle_expansion()

    def toggle_expansion(self) -> None:
        if self._expansion.is_expanded:
            self.collapse()
        else:
            self.expand()

    def _emit_expansion_change(self) -> None:
        self._hub.send(PropertyChangedMessage.create(self, self._name, "is_expanded"))
        self._raise_property_changed("is_expanded")

    # ── Model setter override — emit notebook_name PCM in addition ─────────
    def _set_model(self, value: NotebookModel) -> None:
        old_name = self._model.name
        super()._set_model(value)
        if old_name != value.name:
            # ComponentVMOf emits "model" and "modeled_hint"; we add the
            # showcase-specific "notebook_name" alias.
            self._hub.send(
                PropertyChangedMessage.create(self, self._name, "notebook_name")
            )
            self._raise_property_changed("notebook_name")

    # ── Lifecycle hook — dispose expansion subject ─────────────────────────
    def _on_dispose(self) -> None:
        self._expansion.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    # The base ComponentVMOf exposes `builder() -> ComponentVMOfBuilder[M]`;
    # we deliberately narrow to the showcase builder so callers reach our
    # fluent API. Suppress the LSP-override warning since the swap is by
    # design (mirrors C# `new NotebookVMBuilder Builder()`).
    @staticmethod
    def builder() -> NotebookVMBuilder:  # type: ignore[override]
        return NotebookVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class NotebookVMBuilder:
    """Immutable fluent builder for :class:`NotebookVM` (spec ch. 10)."""

    _name: str | None = None
    _hint: str = ""
    _model: NotebookModel | None = None
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _initially_expanded: bool = False
    _children_getter: Callable[[NotebookVM], list[NotebookVM]] | None = None

    def name(self, value: str) -> NotebookVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NotebookVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def model(self, value: NotebookModel) -> NotebookVMBuilder:
        return dataclasses.replace(self, _model=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> NotebookVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def initially_expanded(self, value: bool) -> NotebookVMBuilder:
        return dataclasses.replace(self, _initially_expanded=value)

    def children_getter(
        self, getter: Callable[[NotebookVM], list[NotebookVM]]
    ) -> NotebookVMBuilder:
        return dataclasses.replace(self, _children_getter=getter)

    def build(self) -> NotebookVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._model is None:
            raise ValueError("model is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
        return NotebookVM(
            name=self._name,
            hint=self._hint,
            model=self._model,
            hub=hub,
            dispatcher=dispatcher,
            initially_expanded=self._initially_expanded,
            children_getter=self._children_getter,
        )
