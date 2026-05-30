"""Internal helper — resolve a VM's :class:`MessageHub`.

VMx's :class:`vmx.components.base._ComponentVMBase` stores the hub on the
private attribute ``_hub`` (per spec ch. 3); only some VMs expose a public
``hub`` property (the notes-showcase VMs do — Phase 3.b convention). Adapter
code targets the broadest possible VM surface, so we prefer the public
``hub`` accessor and fall back to ``_hub`` for plain VMx VMs (e.g.
:class:`~vmx.ComponentVM`).
"""

from __future__ import annotations

from typing import Any, cast

from vmx.services.message_hub import MessageHub


def resolve_hub(vm: Any) -> MessageHub[Any]:
    """Return *vm*'s hub, or raise :class:`AttributeError` if it has none.

    Tries the public ``hub`` property first, then the protected ``_hub``
    fallback. Both are widely-supported VMx idioms; raising at bind time gives
    a clearer trace than a silent no-op subscription.
    """
    hub = getattr(vm, "hub", None)
    if hub is None:
        hub = getattr(vm, "_hub", None)
    if hub is None:
        raise AttributeError(
            f"VM {vm!r} exposes neither a public 'hub' property nor a '_hub' "
            "attribute; adapter bridges cannot subscribe."
        )
    return cast(MessageHub[Any], hub)
