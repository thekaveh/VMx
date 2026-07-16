"""hello_vmx — minimal console example for the VMx Python library.

Demonstrates:
  1. Building a ComponentVMOf[UserModel] with the fluent builder.
  2. Subscribing to hub messages (ConstructionStatusChangedMessage + PropertyChangedMessage).
  3. The full lifecycle: Destruct → Construct → model mutations → Destruct → Dispose.
  4. The equality guard: setting the same model value emits no hub message.

Run with:
    uv run python -m hello_vmx          (from examples/python/)
    python -m hello_vmx                 (with vmx on sys.path)
"""

from __future__ import annotations

from dataclasses import dataclass

from vmx.components.builders import ComponentVMOfBuilder
from vmx.components.component_vm import ComponentVMOf
from vmx.messages import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserModel:
    """Simple immutable domain model used as the VM's model type."""

    name: str
    age: int

    def __str__(self) -> str:
        return f"UserModel(name={self.name!r}, age={self.age})"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def run() -> None:
    print("=== hello_vmx ===")
    print()

    # ── Infrastructure: shared hub + immediate dispatcher ─────────────────
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()

    # ── Subscribe to hub messages ─────────────────────────────────────────
    def on_hub_message(msg: object) -> None:
        if isinstance(msg, ConstructionStatusChangedMessage):
            print(f"  [hub] {msg.sender_name}  status → {msg.status.name}")
        elif isinstance(msg, PropertyChangedMessage):
            print(f"  [hub] {msg.sender_name}  property '{msg.property_name}' changed")

    hub_sub = hub.messages.subscribe(on_next=on_hub_message)

    # ── Build the VM ──────────────────────────────────────────────────────
    print("Building ComponentVMOf[UserModel] ...")

    builder: ComponentVMOfBuilder[UserModel] = ComponentVMOf.builder()
    vm: ComponentVMOf[UserModel] = (
        builder.name("user-vm")
        .hint("Displays the current user")
        .services(hub, dispatcher)
        .model(UserModel("Alice", 30))
        .modeled_hinter(lambda u: f"{u.name} ({u.age})")
        .on_construct(lambda: print("  [lifecycle] on_construct callback fired"))
        .on_destruct(lambda: print("  [lifecycle] on_destruct callback fired"))
        .build()
    )

    print(f"  vm.name   = {vm.name}")
    print(f"  vm.status = {vm.status.name}")
    print(f"  vm.model  = {vm.model}")
    print()

    # ── Construct ─────────────────────────────────────────────────────────
    print("Calling construct() ...")
    vm.construct()
    print(f"  vm.status         = {vm.status.name}")
    print(f"  vm.is_constructed = {vm.is_constructed}")
    print(f"  vm.modeled_hint   = {vm.modeled_hint!r}")
    print()

    # ── Mutate the model ──────────────────────────────────────────────────
    print("Mutating model → Bob, 25 ...")
    vm.model = UserModel("Bob", 25)
    print(f"  vm.model        = {vm.model}")
    print(f"  vm.modeled_hint = {vm.modeled_hint!r}")
    print()

    print("Mutating model → Carol, 40 ...")
    vm.model = UserModel("Carol", 40)
    print(f"  vm.model        = {vm.model}")
    print(f"  vm.modeled_hint = {vm.modeled_hint!r}")
    print()

    # ── No-op: setting the same model value ───────────────────────────────
    print("Setting the SAME model value (equality guard — no hub message expected) ...")
    vm.model = UserModel("Carol", 40)
    print()

    # ── Destruct ──────────────────────────────────────────────────────────
    print("Calling destruct() ...")
    vm.destruct()
    print(f"  vm.status         = {vm.status.name}")
    print(f"  vm.is_constructed = {vm.is_constructed}")
    print()

    # ── Cleanup ───────────────────────────────────────────────────────────
    hub_sub.dispose()
    vm.dispose()
    hub.dispose()

    print("=== Done ===")


if __name__ == "__main__":
    run()
