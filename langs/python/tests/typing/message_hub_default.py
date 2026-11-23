"""Static contract: a bare hub form means the default parameter ``Message``.

CI runs ``mypy --strict`` on this file (``.github/workflows/python.yml``, step
"Mypy typing contract"). Each ``assert_type`` fails the check when the bare form
resolves to another parameter. ADR-0231 records the decision.

This file is not a pytest module; pytest collects only ``test_*.py``.
"""

from typing_extensions import assert_type

from vmx.messages import Message
from vmx.services import MessageHub, MessageHubProto, TransactionalMessageHubProto


def bare_construction_is_message_hub_of_message() -> None:
    hub = MessageHub()
    assert_type(hub, MessageHub[Message])


def bare_parameter_is_message_hub_of_message(hub: MessageHub) -> None:
    assert_type(hub, MessageHub[Message])


def explicit_parameterisation_is_unchanged(message: Message) -> None:
    explicit: MessageHub[Message] = MessageHub()
    assert_type(explicit, MessageHub[Message])
    explicit.send(message)


def protocol_forms_are_message_protocols(
    proto: MessageHubProto,
    transactional: TransactionalMessageHubProto,
) -> None:
    assert_type(proto, MessageHubProto[Message])
    assert_type(transactional, TransactionalMessageHubProto[Message])
