"""Shared local-then-hub delivery for the hub-publishing collections.

See spec/01-concepts.md §1.4, spec/21-collections.md §2.5 and ADR-0171.
"""

from __future__ import annotations

from collections.abc import Callable


def deliver_then_publish(deliver: Callable[[], None], publish: Callable[[], None]) -> None:
    """Run the local delivery, then the hub publication, for one committed change.

    A failing local subscriber does not suppress the hub message: *publish*
    still runs, and the first failure is re-raised afterwards. This mirrors
    the failure rule of
    ``vmx.components._container_helpers.deliver_collection_changed``.

    Unlike that helper, this one has no disposal check: *publish* always runs.
    A collection that a local subscriber can dispose during delivery makes
    *publish* skip the hub send once it is disposed, as
    ``ObservableDictionary`` does (#1431).
    """
    first_error: BaseException | None = None
    try:
        deliver()
    except BaseException as error:
        first_error = error
    try:
        publish()
    except BaseException as error:
        if first_error is None:
            first_error = error
    if first_error is not None:
        raise first_error
