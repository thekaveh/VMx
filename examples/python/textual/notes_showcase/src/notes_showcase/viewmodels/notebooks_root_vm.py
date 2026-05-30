"""NotebooksRootVM — root of the notebooks tree.

VMx-API adaptation (cross-reference with the C# §3.a flavor):
:class:`vmx.HierarchicalVM` materialises its children eagerly from a factory at
construct time and is awkward to mutate dynamically (it supports
``add_child``/``remove_child`` but has no first-class "current selection"
surface the plan assumed). Instead we own a flat
:class:`~vmx.ObservableList` of :class:`NotebookVM` instances, exposing
``roots`` / ``children_of`` walks for the view, and publish a
:class:`vmx.TreeStructureChangedMessage` on every add/remove so subscribers
observe structural changes identically to the HierarchicalVM contract.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid

from vmx import (
    ComponentVM,
    ConstructionStatus,
    INewCreatable,
    IReconstructable,
    MessageHub,
    ObservableList,
    PropertyChangedMessage,
    RelayCommand,
    RxDispatcher,
    TreeStructureChange,
    TreeStructureChangedMessage,
)
from vmx.messages.protocols import Message
from vmx.notifications import INotificationHub, Notification, NotificationType
from vmx.services.dispatcher import Dispatcher

from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.models.notebook_model import NotebookModel
from notes_showcase.viewmodels.notebook_vm import NotebookVM


class NotebooksRootVM(ComponentVM, INewCreatable, IReconstructable):
    """Root VM owning the flat collection of notebook VMs."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        repository: INoteRepository,
        notification_hub: INotificationHub | None = None,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._repo = repository
        self._notification_hub = notification_hub
        self._notebooks: ObservableList[NotebookVM] = ObservableList()
        self._current: NotebookVM | None = None

        self._add_notebook_command = (
            RelayCommand.builder()
            .predicate(self.can_create_new)
            .task(self.create_new)
            .build()
        )

    # ── Convenience hub accessor ───────────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        return self._hub

    # ── Collection projections ─────────────────────────────────────────────
    @property
    def all(self) -> ObservableList[NotebookVM]:
        """All notebook VMs in load order."""
        return self._notebooks

    @property
    def roots(self) -> list[NotebookVM]:
        """Top-level notebook VMs (``parent_id is None``)."""
        return [nb for nb in self._notebooks if nb.model.parent_id is None]

    def children_of(self, parent: NotebookVM) -> list[NotebookVM]:
        """Children of *parent* by ``parent_id`` walk."""
        return [nb for nb in self._notebooks if nb.model.parent_id == parent.model.id]

    def walk(self) -> list[NotebookVM]:
        """All notebook VMs (parents-before-children, repo order)."""
        return list(self._notebooks)

    # ── current (two-way bindable) ─────────────────────────────────────────
    @property
    def current(self) -> NotebookVM | None:
        return self._current

    @current.setter
    def current(self, value: NotebookVM | None) -> None:
        if self._current is value:
            return
        self._current = value
        self._hub.send(PropertyChangedMessage.create(self, self._name, "current"))
        self._raise_property_changed("current")

    # ── INewCreatable ──────────────────────────────────────────────────────
    def can_create_new(self) -> bool:
        return self._status == ConstructionStatus.CONSTRUCTED

    def create_new(self) -> None:
        """Fire-and-forget schedule of a default "New Notebook" add."""
        # Schedule via asyncio if a loop is running; otherwise no-op (the
        # async add_notebook is the canonical entry-point).
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.add_notebook(parent_id=None, name="New Notebook"))
        except RuntimeError:
            asyncio.run(self.add_notebook(parent_id=None, name="New Notebook"))

    @property
    def add_notebook_command(self) -> RelayCommand:
        return self._add_notebook_command

    # ── Async mutation ─────────────────────────────────────────────────────
    async def add_notebook(self, parent_id: str | None, name: str) -> NotebookVM:
        """Persist a new notebook via the repo and publish TreeStructureChanged.

        Returns the newly created :class:`NotebookVM`.
        """
        nb_id = f"nb-{uuid.uuid4().hex[:6]}"
        model = NotebookModel(id=nb_id, name=name, parent_id=parent_id)
        await self._repo.add_notebook(model)
        vm = (
            NotebookVM.builder()
            .name(f"nb:{nb_id}")
            .services(self.hub, self._dispatcher)
            .model(model)
            .children_getter(self.children_of)
            .build()
        )
        vm.construct()
        index = self._notebooks.count
        self._notebooks.append(vm)
        self._hub.send(
            TreeStructureChangedMessage(
                sender=self,
                sender_name=self._name,
                change=TreeStructureChange.ADDED,
                affected=vm,
                index=index,
            )
        )
        # Spec §6.2: publish a "Notebook added" notification (cross-flavor
        # parity with the C# and TypeScript flavors). No-op when no
        # notification hub is wired.
        if self._notification_hub is not None:
            self._notification_hub.post(
                Notification(
                    NotificationType.NOTIFICATION,
                    f'Notebook added: “{name}”',
                )
            )
        return vm

    async def populate(self) -> None:
        """Replace the inner collection with fresh data from the repo.

        Disposes any previously-held VMs first. Called by
        :meth:`WorkspaceVM.construct_async` during workspace startup.
        """
        notebooks, _ = await self._repo.load_all()
        # Dispose previous children.
        for prev in list(self._notebooks):
            prev.dispose()
        # Replace via a single Reset emission rather than per-item churn.
        with self._notebooks.batch_update():
            while self._notebooks.count > 0:
                self._notebooks.remove_at(0)
            for nb in notebooks:
                vm = (
                    NotebookVM.builder()
                    .name(f"nb:{nb.id}")
                    .services(self.hub, self._dispatcher)
                    .model(nb)
                    .children_getter(self.children_of)
                    .build()
                )
                vm.construct()
                self._notebooks.append(vm)
        self._current = None
        # Re-broadcast a tree-structure reset so subscribers refresh.
        self._hub.send(
            TreeStructureChangedMessage(
                sender=self,
                sender_name=self._name,
                change=TreeStructureChange.ADDED,
                affected=self,
                index=-1,
            )
        )

    # ── Lifecycle overrides ────────────────────────────────────────────────
    def _on_destruct(self) -> None:
        for nb in list(self._notebooks):
            nb.destruct()
        super()._on_destruct()

    def _on_dispose(self) -> None:
        for nb in list(self._notebooks):
            nb.dispose()
        self._add_notebook_command.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> NotebooksRootVMBuilder:  # type: ignore[override]
        # Narrows ComponentVM.builder() to the showcase NotebooksRootVMBuilder.
        return NotebooksRootVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class NotebooksRootVMBuilder:
    """Immutable fluent builder for :class:`NotebooksRootVM`."""

    _name: str | None = None
    _hint: str = ""
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _repo: INoteRepository | None = None
    _notification_hub: INotificationHub | None = None

    def name(self, value: str) -> NotebooksRootVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NotebooksRootVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> NotebooksRootVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def repository(self, repo: INoteRepository) -> NotebooksRootVMBuilder:
        return dataclasses.replace(self, _repo=repo)

    def notification_hub(self, nh: INotificationHub) -> NotebooksRootVMBuilder:
        return dataclasses.replace(self, _notification_hub=nh)

    def build(self) -> NotebooksRootVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._repo is None:
            raise ValueError("repository is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = self._dispatcher if self._dispatcher is not None else RxDispatcher.immediate()
        return NotebooksRootVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            repository=self._repo,
            notification_hub=self._notification_hub,
        )
