"""Shared Notes scenario `notes-lifecycle-v1` (#346).

Runs `examples/notes-showcase-scenario.json` through this showcase's view models
and compares every step's semantic snapshot with the shared expectation. The
C#, TypeScript, and Swift showcases run the same file through their own
adapters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reactivex.scheduler import ImmediateScheduler
from vmx import MessageHub, RxDispatcher
from vmx.messages.protocols import Message

from notes_showcase.messages.theme_changed import ThemeChangedMessage
from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM

SCENARIO = Path(__file__).resolve().parents[4] / "notes-showcase-scenario.json"
FLAVOR = "python"


class _Adapter:
    def __init__(self) -> None:
        repo = InMemoryNoteRepository(
            build_seed(),
            load_all_delay=0.0,
            load_notes_delay=0.0,
            save_note_delay=0.0,
            add_notebook_delay=0.0,
            export_delay=0.0,
        )
        self.hub = MessageHub[Message]()
        self.ws = (
            WorkspaceVM.builder()
            .name("workspace")
            .repository(repo)
            .message_hub(self.hub)
            .dispatcher(
                RxDispatcher(foreground=ImmediateScheduler(), background=ImmediateScheduler())
            )
            .build()
        )
        self.events: list[str] = []
        self.saved_completed = False
        self.hub.messages.subscribe(on_next=self._on_message)

    def _on_message(self, message: object) -> None:
        if isinstance(message, ThemeChangedMessage):
            self.events.append(f"theme:{message.prev_theme.name}->{message.curr_theme.name}")

    def _on_saved_completed(self) -> None:
        self.saved_completed = True

    async def run(self, step: dict[str, Any]) -> str | None:
        action = step["action"]
        try:
            if action == "construct":
                await self.ws.construct_async()
                # The note form exists once the workspace is constructed.
                self.ws.note_form.on_saved.subscribe(
                    on_next=lambda model: self.events.append(f"saved:{model.title}"),
                    on_completed=self._on_saved_completed,
                )
            elif action == "create_note":
                await self.ws.new_note_command.execute_async()
            elif action == "select_note":
                self.ws.notes_view.current = self.ws.notes_view.inner[step["index"]]
            elif action == "edit_title":
                self.ws.note_form.title = step["title"]
            elif action == "save":
                await self.ws.note_form.approve_async()
            elif action == "delete_selected_declined":
                # The default dialog service declines every confirmation.
                current = self.ws.notes_view.current
                assert current is not None
                await current.delete_command.execute_async()
            elif action == "set_theme":
                self.ws.theme.set_theme_command.execute(step["theme"])
            elif action == "dispose":
                self.ws.dispose()
            else:
                raise AssertionError(f"unknown scenario action {action!r}")
        except ValueError:
            return "invalid"
        return None

    def snapshot(self, error: str | None) -> dict[str, Any]:
        if self.saved_completed:
            return {"events": self._drain(), "error": error, "disposed": True}
        view = self.ws.notes_view
        form = self.ws.note_form
        return {
            "notebook": view.bound_notebook_id,
            "notes": [note.model.title for note in view.inner],
            "selected": view.current.model.title if view.current is not None else None,
            "form": (
                {"title": form.title, "dirty": form.is_dirty.value, "valid": form.is_valid.value}
                if form.has_bound_note
                else None
            ),
            "theme": self.ws.theme.current_theme.value.name,
            "events": self._drain(),
            "error": error,
            "disposed": False,
        }

    def _drain(self) -> list[str]:
        events, self.events = self.events, []
        return events


def _differences(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    return [
        f"{key}: expected {expected[key]!r}, got {actual.get(key, '<absent>')!r}"
        for key in expected
        if actual.get(key, "<absent>") != expected[key]
    ]


async def test_shared_notes_scenario_matches_the_semantic_expectation() -> None:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    adapter = _Adapter()
    failures = []
    for number, step in enumerate(scenario["steps"], start=1):
        actual = adapter.snapshot(await adapter.run(step))
        where = f"{scenario['id']} [{FLAVOR}] step {number} {step['action']}"
        for difference in _differences(step["expect"], actual):
            failures.append(f"{where}: {difference}")
    assert not failures, "\n".join(failures)
