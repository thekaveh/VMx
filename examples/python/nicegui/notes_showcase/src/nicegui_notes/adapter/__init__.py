"""NiceGUI adapter — VMx view-models → NiceGUI elements, page by page.

This is example code, not a published package. It mirrors the Textual
Notes-Showcase adapter's surface where NiceGUI has the same shape:

* :func:`bind_property` / :func:`bind_property_two_way` / :func:`bind_derived_property`.
* :func:`bind_command` — a button runs a command; enabled follows ``can_execute``.
* :func:`bind_refreshable` — re-runs a page-local ``@ui.refreshable`` collection builder.
* :func:`release_on_delete` — disposes a page's bindings when NiceGUI deletes its client.
* :func:`text` — parses a text input's value for a ``str`` property.
* :class:`ClientDelivery` — applies updates on NiceGUI's loop, inside the owning page.
"""

from __future__ import annotations

from nicegui_notes.adapter.binding import (
    bind_command,
    bind_derived_property,
    bind_property,
    bind_property_two_way,
    bind_refreshable,
    release_on_delete,
    text,
    vm_property_changes,
)
from nicegui_notes.adapter.delivery import ClientDelivery

__all__ = [
    "ClientDelivery",
    "bind_command",
    "bind_derived_property",
    "bind_property",
    "bind_property_two_way",
    "bind_refreshable",
    "release_on_delete",
    "text",
    "vm_property_changes",
]
