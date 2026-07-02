"""WorkspaceVM — root of the Notes Workspace VM tree.

Wraps a :class:`vmx.AggregateVM6` of six components per scenario §6.2:
notebooks tree, notes view, note form, status bar, notifications, and the
capability actions bar.

VMx-API adaptation: ``AggregateVM6`` is subclassable in Python (it is not
sealed), but the C# flavor chose composition over inheritance because the C#
``sealed`` keyword forbade subclassing. The Python flavor follows the same
composition pattern so cross-language audits compare identically — the
WorkspaceVM is a plain object holding a pre-built ``AggregateVM6``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timezone

from reactivex import operators as ops
from reactivex.scheduler import TimeoutScheduler

from reactivex.abc import DisposableBase

from vmx import (
    AggregateVM6,
    ConstructionStatus,
    MessageHub,
    RelayCommand,
    RxDispatcher,
    when_property_changed,
)
from vmx.messages.protocols import Message
from vmx.notifications import INotificationHub, NotificationHub
from vmx.services.dispatcher import Dispatcher

from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.viewmodels.capability_actions_vm import CapabilityActionsVM
from notes_showcase.viewmodels.dialog_service import (
    NULL_DIALOG_SERVICE,
    IDialogService,
)
from notes_showcase.viewmodels.global_search_vm import GlobalSearchVM
from notes_showcase.viewmodels.note_form_vm import NoteFormVM
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM
from notes_showcase.viewmodels.notifications_vm import NotificationsVM
from notes_showcase.viewmodels.status_bar_vm import StatusBarVM
from notes_showcase.viewmodels.theme_vm import ThemeVM


class WorkspaceVM:
    """Root of the Notes Workspace VM tree (composition of six children)."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        repository: INoteRepository,
        dialog_service: IDialogService,
        notification_hub: INotificationHub,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
    ) -> None:
        self._repo = repository
        self._dialog_service = dialog_service
        # Notebook-bind race bookkeeping (see _fire_bind_notes): the id of
        # the most recent bind request, and a COUNTER of binds currently
        # awaiting the repository. A counter, not an id — an id-keyed
        # marker collides when two outstanding binds target the same
        # notebook (B,A,B: the first B's cleanup erased the second B's
        # marker and resurrected the race; pass-7 adversarial review).
        self._requested_notebook_id: str | None = None
        self._inflight_binds: int = 0
        self._notification_hub = notification_hub
        self._hub = hub
        self._dispatcher = dispatcher
        self._focused: object | None = None

        # Pre-build children so the status bar and capability bar can wire
        # to live references via lazy factories.
        notebooks = (
            NotebooksRootVM.builder()
            .name("notebooks")
            .services(hub, dispatcher)
            .repository(repository)
            .notification_hub(notification_hub)
            .build()
        )
        notes_view = (
            NotesViewVM.builder()
            .name("notes")
            .services(hub, dispatcher)
            .repository(repository)
            .page_size(5)
            .dialog_service(dialog_service)
            .notification_hub(notification_hub)
            .build()
        )
        note_form = (
            NoteFormVM.builder()
            .name("form")
            .services(hub, dispatcher)
            .repository(repository)
            .notification_hub(notification_hub)
            .build()
        )
        status_bar = (
            StatusBarVM.builder()
            .name("status")
            .services(hub, dispatcher)
            .notes_view(notes_view)
            .notebooks(notebooks)
            .note_form(note_form)
            .build()
        )
        notifications = (
            NotificationsVM.builder()
            .name("notifications")
            .services(hub, dispatcher)
            .notification_hub(notification_hub)
            .scheduler(TimeoutScheduler())
            .build()
        )
        capability_actions = (
            CapabilityActionsVM.builder()
            .name("capabilities")
            .services(hub, dispatcher)
            .focused_getter(lambda: self._focused)
            # Edge-case backfill (readonly notebook gating): the bar's
            # *Add Note* command is gated on the currently-bound notebook's
            # readonly flag (mirrored into notes_view by this VM on
            # selection change), and on the workspace being constructed
            # with a current notebook.
            .can_add_note(
                lambda: (
                    self.is_constructed
                    and self.notebooks_root.current is not None
                    and not self.notes_view.current_notebook_is_readonly
                )
            )
            .add_note_action(self._fire_new_note)
            .build()
        )
        global_search = (
            GlobalSearchVM.builder()
            .name("global-search")
            .services(hub, dispatcher)
            .repository(repository)
            .page_size(5)
            .search_debounce_seconds(0.150)
            .build()
        )

        self._agg: AggregateVM6[
            NotebooksRootVM,
            NotesViewVM,
            NoteFormVM,
            StatusBarVM,
            NotificationsVM,
            CapabilityActionsVM,
        ] = AggregateVM6(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=lambda: notebooks,
            factory2=lambda: notes_view,
            factory3=lambda: note_form,
            factory4=lambda: status_bar,
            factory5=lambda: notifications,
            factory6=lambda: capability_actions,
        )

        # VMX-129: the theme seam is a workspace-owned sibling of the six
        # aggregate children. Composing it as a seventh aggregate child would
        # require an AggregateVM7 in core (declined in ADR-0058); instead it is
        # held directly and lifecycle-driven alongside the aggregate. It shares
        # the workspace hub + dispatcher so its ThemeChangedMessage rides the
        # same bus, and ``views.app`` binds the Textual ``theme_adapter`` to it.
        self._theme: ThemeVM = (
            ThemeVM.builder().name("theme").services(hub, dispatcher).build()
        )
        self._global_search: GlobalSearchVM = global_search

        # Round-3 Critical-2: rebind note_form whenever notes_view.current
        # changes (e.g. user clicks a different note in the list). Without
        # this the right-pane editor stays empty in the running app. Mirror
        # of the C# WorkspaceVM subscription (parity with the TS view
        # which performs the same wiring inline in NotesList.tsx).
        #
        # Round-4 Important-1: when current transitions to None (e.g. the
        # selected note is deleted in NotesViewVM._delete_note_async, or the
        # host explicitly clears selection) the form must be unbound —
        # otherwise the right pane keeps the title/body of the deleted note
        # and approve would attempt to persist a ghost.
        #
        # Round-4 Important-2: marshal delivery onto the foreground
        # scheduler so bind_to / unbind (which raise PropertyChanged) always
        # fire on the UI thread. Today current is set from the Textual UI
        # thread so this is defensive, but matches the foreground-marshal
        # contract documented in the THR-001 conformance test.
        #
        # VMX-017: the typed ``when_property_changed`` hub helper replaces the
        # hand-rolled ``filter(isinstance + sender is + property_name)`` filter
        # (still filtering FIRST, then ``observe_on`` so only matching messages
        # hop to the foreground scheduler).
        def _on_notes_view_msg(_m: Message) -> None:
            current = notes_view.current
            if current is not None:
                note_form.bind_to(current.model)
                self.set_focus(current)
            else:
                note_form.unbind()
                self.set_focus(notebooks.current)

        self._current_note_subscription: DisposableBase = (
            when_property_changed(notes_view.hub, notes_view, "current")
            .pipe(
                ops.observe_on(dispatcher.foreground),
            )
            .subscribe(on_next=_on_notes_view_msg)
        )

        # Pass-5 real-wiring audit: the tree view sets notebooks.current on
        # node selection, but nothing re-bound the notes view — the centre
        # pane stayed on the first notebook forever. Mirror the
        # construct_async wiring on every notebook-selection change.
        def _on_notebook_msg(_m: Message) -> None:
            nb = notebooks.current
            if nb is None:
                return
            self.set_focus(nb)
            notes_view.current_notebook_is_readonly = nb.model.is_readonly
            self._fire_bind_notes(nb.model.id)

        self._notebook_subscription: DisposableBase = (
            when_property_changed(notebooks.hub, notebooks, "current")
            .pipe(
                ops.observe_on(dispatcher.foreground),
            )
            .subscribe(on_next=_on_notebook_msg)
        )

        # Pass-5 real-wiring audit: refresh the saved note's list row (title /
        # star marker were construction-time snapshots and went stale after
        # every save).
        self._saved_note_subscription: DisposableBase = note_form.on_saved.pipe(
            ops.observe_on(dispatcher.foreground),
        ).subscribe(on_next=notes_view.refresh_note)

        self._new_notebook_command = (
            RelayCommand.builder()
            .predicate(lambda: self.is_constructed)
            .task(self._fire_new_notebook)
            .build()
        )
        self._new_note_command = (
            RelayCommand.builder()
            .predicate(
                lambda: self.is_constructed and self.notebooks_root.current is not None
            )
            .task(self._fire_new_note)
            .build()
        )
        self._export_command = (
            RelayCommand.builder()
            .predicate(lambda: self.is_constructed)
            .task(self._fire_export)
            .build()
        )

    # ── Public surface ─────────────────────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        return self._hub

    @property
    def name(self) -> str:
        return self._agg.name

    @property
    def status(self) -> ConstructionStatus:
        return self._agg.status

    @property
    def is_constructed(self) -> bool:
        return self._agg.is_constructed

    @property
    def notebooks_root(self) -> NotebooksRootVM:
        assert self._agg.component_1 is not None
        return self._agg.component_1

    @property
    def notes_view(self) -> NotesViewVM:
        assert self._agg.component_2 is not None
        return self._agg.component_2

    @property
    def note_form(self) -> NoteFormVM:
        assert self._agg.component_3 is not None
        return self._agg.component_3

    @property
    def status_bar(self) -> StatusBarVM:
        assert self._agg.component_4 is not None
        return self._agg.component_4

    @property
    def notifications(self) -> NotificationsVM:
        assert self._agg.component_5 is not None
        return self._agg.component_5

    @property
    def capability_actions(self) -> CapabilityActionsVM:
        assert self._agg.component_6 is not None
        return self._agg.component_6

    @property
    def global_search(self) -> GlobalSearchVM:
        return self._global_search

    @property
    def theme(self) -> ThemeVM:
        """Theme seam (THEME-001..005). Workspace-owned, not an aggregate
        child — ``views.app`` binds the Textual ``theme_adapter`` to it so the
        scenario is exercised in the running app (VMX-129)."""
        return self._theme

    @property
    def dialog_service(self) -> IDialogService:
        """Currently-bound :class:`IDialogService` (may be late-swapped)."""
        return self._dialog_service

    @dialog_service.setter
    def dialog_service(self, value: IDialogService) -> None:
        """Late-bind the dialog service (used by the composition root once
        the host UI exists — Avalonia / Textual / React). Forwarded to the
        notes view, whose delete-confirmation path reads it (the boot-time
        NullDialogService denies every confirm).
        """
        self._dialog_service = value
        notes_view = self._agg.component_2
        if notes_view is not None:
            notes_view.dialog_service = value

    @property
    def focused_vm(self) -> object | None:
        return self._focused

    def set_focus(self, focused: object | None) -> None:
        """Set the currently-focused VM and refresh the capability bar."""
        if self._focused is focused:
            return
        self._focused = focused
        self.capability_actions.recompute_actions()

    @property
    def new_notebook_command(self) -> RelayCommand:
        return self._new_notebook_command

    @property
    def new_note_command(self) -> RelayCommand:
        return self._new_note_command

    @property
    def export_command(self) -> RelayCommand:
        return self._export_command

    # ── Lifecycle ──────────────────────────────────────────────────────────
    def construct(self) -> None:
        """Synchronous construct cascade (per ADR-0034)."""
        self._agg.construct()
        self._theme.construct()
        self._global_search.construct()

    async def construct_async(self) -> None:
        """Async construct: build aggregate, populate notebooks, bind notes view."""
        self._agg.construct()
        self._theme.construct()
        self._global_search.construct()
        await self.notebooks_root.populate()
        first = next(iter(self.notebooks_root.roots), None)
        if first is not None:
            # Edge-case backfill (readonly notebook gating): mirror the
            # notebook's readonly flag into notes_view so
            # CapabilityActionsVM.add_note_command observes it.
            self.notes_view.current_notebook_is_readonly = first.model.is_readonly
            # Bind BEFORE assigning current: the notebook-selection
            # subscription fires on the assignment and would otherwise queue
            # a concurrent bind whose token supersedes (discards) this
            # awaited one; with the notes view already bound the queued task
            # dedupes on bound_notebook_id and exits.
            await self.notes_view.bind_to_async(first.model.id)
            await self.note_form.refresh_tag_suggestions_async()
            self.notebooks_root.current = first
            self.set_focus(first)

    def destruct(self) -> None:
        self._theme.destruct()
        self._global_search.destruct()
        self._agg.destruct()

    def dispose(self) -> None:
        self._current_note_subscription.dispose()
        self._notebook_subscription.dispose()
        self._saved_note_subscription.dispose()
        self._new_notebook_command.dispose()
        self._new_note_command.dispose()
        self._export_command.dispose()
        self._theme.dispose()
        self._global_search.dispose()
        self._agg.dispose()

    # ── Command fire-and-forget wrappers ───────────────────────────────────
    def _fire_bind_notes(self, notebook_id: str) -> None:
        async def _bind() -> None:
            if self._requested_notebook_id != notebook_id:
                return  # superseded by a newer selection before we ran
            if (
                self.notes_view.bound_notebook_id == notebook_id
                and self._inflight_binds == 0
            ):
                # Already bound and nothing racing: construct_async awaits
                # the initial bind explicitly, so the task its own
                # current-assignment queues must not reload. The in-flight
                # check matters for A→B→A: with a bind to B mid-await,
                # "bound is still A" does NOT mean A needs no rebind — the
                # superseding bind_to_async token must discard B's result
                # (race confirmed by the pass-6 adversarial probe).
                return
            self._inflight_binds += 1
            try:
                await self.notes_view.bind_to_async(notebook_id)
            finally:
                self._inflight_binds -= 1

        self._requested_notebook_id = notebook_id
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_bind())
        except RuntimeError:
            asyncio.run(_bind())

    def _fire_new_notebook(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.notebooks_root.add_notebook(parent_id=None, name="New Notebook")
            )
        except RuntimeError:
            asyncio.run(
                self.notebooks_root.add_notebook(parent_id=None, name="New Notebook")
            )

    def _fire_new_note(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._add_new_note_to_current())
        except RuntimeError:
            asyncio.run(self._add_new_note_to_current())

    def _fire_export(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._export_internal())
        except RuntimeError:
            asyncio.run(self._export_internal())

    async def _add_new_note_to_current(self) -> None:
        nb = self.notebooks_root.current
        if nb is None:
            return
        now = datetime.now(timezone.utc)
        note = NoteModel(
            id=f"note-{uuid.uuid4().hex[:8]}",
            notebook_id=nb.model.id,
            title="Untitled",
            tags=(),
            body="",
            starred=False,
            created_at=now,
            updated_at=now,
        )
        await self._repo.save_note(note)
        await self.notes_view.bind_to_async(nb.model.id)

    async def _export_internal(self) -> None:
        path = await self._dialog_service.pick_file_to_save(
            filter=None, title="Export workspace", suggested_name="notes-export.json"
        )
        if not path:
            return
        notebooks, notes = await self._repo.load_all()
        await self._repo.export(notebooks, notes, path)

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> WorkspaceVMBuilder:
        return WorkspaceVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class WorkspaceVMBuilder:
    """Immutable fluent builder for :class:`WorkspaceVM`."""

    _name: str = "workspace"
    _hint: str = ""
    _repo: INoteRepository | None = None
    _dialog_service: IDialogService | None = None
    _notification_hub: INotificationHub | None = None
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None

    def name(self, value: str) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def repository(self, repo: INoteRepository) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _repo=repo)

    def dialog_service(self, service: IDialogService) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _dialog_service=service)

    def notification_hub(self, nh: INotificationHub) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _notification_hub=nh)

    def message_hub(self, hub: MessageHub[Message]) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _hub=hub)

    def dispatcher(self, dispatcher: Dispatcher) -> WorkspaceVMBuilder:
        return dataclasses.replace(self, _dispatcher=dispatcher)

    def build(self) -> WorkspaceVM:
        if self._repo is None:
            raise ValueError("repository is required")
        return WorkspaceVM(
            name=self._name,
            hint=self._hint,
            repository=self._repo,
            dialog_service=self._dialog_service or NULL_DIALOG_SERVICE,
            notification_hub=self._notification_hub or NotificationHub(),
            hub=self._hub if self._hub is not None else MessageHub[Message](),
            dispatcher=self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate(),
        )
