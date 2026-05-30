"""Adapter sub-package — VMx hub primitives → Textual widget state.

This sub-package is the *only* view-layer code permitted to subscribe to a
VM's :class:`~vmx.services.message_hub.MessageHub` (scenario §6.1). Widgets
delegate to these bridges; they never touch the hub directly.

Public surface (plan §4.b, scenario §7.3):

* :func:`bind_property` / :func:`bind_property_two_way` — PropertyBridge.
* :func:`bind_command` — CommandBridge.
* :func:`bind_collection` — CollectionBridge.
* :class:`TextualDispatcher` — implements VMx's ``Dispatcher`` Protocol over
  Textual's asyncio loop.
* :class:`TextualDialogService` — implements ``IDialogService`` against the
  Textual modal stack. Phase 4.b ships the shell only; modal screens land in
  Phase 5.b.
"""

from __future__ import annotations

from notes_showcase.views.adapter.collection import bind_collection
from notes_showcase.views.adapter.command import bind_command
from notes_showcase.views.adapter.dialog import TextualDialogService
from notes_showcase.views.adapter.dispatcher import TextualDispatcher
from notes_showcase.views.adapter.property import bind_property, bind_property_two_way

__all__ = [
    "TextualDialogService",
    "TextualDispatcher",
    "bind_collection",
    "bind_command",
    "bind_property",
    "bind_property_two_way",
]
