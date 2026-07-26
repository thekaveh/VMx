#!/usr/bin/env python3
"""Validate the canonical fixture inventories and structural contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_IDS: dict[str, tuple[str, str, set[str]]] = {
    "command-truthtable.json": (
        "cases",
        "id",
        {
            "no-predicate-no-trigger",
            "predicate-true",
            "predicate-false",
            "trigger-fires-can-execute-event",
            "null-task",
        },
    ),
    "message-ordering.json": (
        "scenarios",
        "id",
        {
            "single-producer-fifo",
            "late-subscribe-no-replay",
            "multiple-subscribers-same-message",
            "unsubscribe-during-emit",
        },
    ),
    "derived-properties.json": (
        "scenarios",
        "name",
        {
            "single-source-initial-value",
            "single-source-one-mutation",
            "two-sources-additive",
            "five-sources-additive",
            "distinct-until-changed",
            "concat-string-sources",
        },
    ),
}

LIFECYCLE_KEYS = {
    (state, operation)
    for state, operations in {
        "Destructed": ("construct", "dispose", "destruct", "reconstruct"),
        "Constructed": ("construct", "destruct", "reconstruct", "dispose"),
        "Constructing": ("construct", "destruct", "reconstruct", "dispose"),
        "Destructing": ("construct", "destruct", "reconstruct", "dispose"),
        "Disposed": ("construct", "destruct", "reconstruct", "dispose"),
    }.items()
    for operation in operations
}

COMMAND_FIELDS = {
    "id",
    "predicate",
    "task",
    "trigger_emits",
    "can_execute",
    "execute_invokes_task",
    "can_execute_changed_fires",
}
DERIVED_FIELDS = {"name", "sources_initial", "transform", "mutations", "expected_values"}
MESSAGE_FIELDS = {
    "single-producer-fifo": {"id", "description", "producer_sends", "expected_observed"},
    "late-subscribe-no-replay": {
        "id",
        "description",
        "producer_sends_before_subscribe",
        "producer_sends_after_subscribe",
        "expected_observed",
    },
    "multiple-subscribers-same-message": {
        "id",
        "description",
        "producer_sends",
        "subscriber_count",
        "expected_observed_per_subscriber",
    },
    "unsubscribe-during-emit": {
        "id",
        "description",
        "producer_sends",
        "unsubscribe_after_first",
        "expected_observed",
    },
}
LIFECYCLE_STATES = [
    "Disposed",
    "Destructing",
    "Destructed",
    "Constructing",
    "Constructed",
]
LIFECYCLE_OPERATIONS = {"construct", "destruct", "reconstruct", "dispose"}


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("root must be a JSON object")
    if value.get("$schema-version") != "1.0.0":
        raise ValueError("$schema-version must be exactly '1.0.0'")
    return value


def validate_fixture(path: Path) -> list[str]:
    """Return all contract errors for one canonical fixture."""
    try:
        value = _object(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return [f"{path.name}: {error}"]
    errors: list[str] = []
    if path.name == "lifecycle-transitions.json":
        if value.get("states") != LIFECYCLE_STATES:
            errors.append(f"{path.name}: states must contain the exact lifecycle state inventory")
        if value.get("initial_state") != "Destructed":
            errors.append(f"{path.name}: initial_state must be 'Destructed'")
        if value.get("terminal_states") != ["Disposed"]:
            errors.append(f"{path.name}: terminal_states must be ['Disposed']")
        if not isinstance(value.get("notes"), dict):
            errors.append(f"{path.name}: notes must be an object")
        rows = value.get("transitions")
        if not isinstance(rows, list):
            return [f"{path.name}: transitions must be an array"]
        keys = [(row.get("from"), row.get("via")) for row in rows if isinstance(row, dict)]
        if len(keys) != len(rows) or set(keys) != LIFECYCLE_KEYS or len(keys) != len(set(keys)):
            errors.append(
                f"{path.name}: transitions must contain each of the 20 state/operation keys once"
            )
        if any(
            not isinstance(row, dict)
            or set(row) != {"from", "via", "to_intermediate", "to_final", "legal"}
            for row in rows
        ):
            errors.append(f"{path.name}: every transition must contain the exact required fields")
        states = set(LIFECYCLE_STATES)
        if any(
            not isinstance(row, dict)
            or row.get("from") not in states
            or row.get("via") not in LIFECYCLE_OPERATIONS
            or row.get("to_intermediate") not in states | {None}
            or row.get("to_final") not in states | {None}
            or not _is_bool(row.get("legal"))
            or (
                row.get("legal") is False
                and (row.get("to_intermediate") is not None or row.get("to_final") is not None)
            )
            or (row.get("legal") is True and row.get("to_final") is None)
            for row in rows
        ):
            errors.append(f"{path.name}: transition values violate lifecycle domains")
        return errors

    array_name, id_name, expected = EXPECTED_IDS[path.name]
    rows = value.get(array_name)
    if not isinstance(rows, list):
        return [f"{path.name}: {array_name} must be an array"]
    identifiers = [row.get(id_name) for row in rows if isinstance(row, dict)]
    if (
        len(identifiers) != len(rows)
        or set(identifiers) != expected
        or len(identifiers) != len(set(identifiers))
    ):
        errors.append(
            f"{path.name}: {array_name} must contain the complete unique inventory "
            f"{sorted(expected)}"
        )
    required_fields = {
        "command-truthtable.json": lambda row: COMMAND_FIELDS,
        "derived-properties.json": lambda row: DERIVED_FIELDS,
        "message-ordering.json": lambda row: MESSAGE_FIELDS.get(str(row.get("id")), set()),
    }[path.name]
    if any(not isinstance(row, dict) or set(row) != required_fields(row) for row in rows):
        errors.append(f"{path.name}: every row must contain its exact required fields")
    if path.name == "command-truthtable.json":
        if any(
            not isinstance(row, dict)
            or not (row.get("predicate") is None or _is_bool(row.get("predicate")))
            or row.get("task") not in {"noop", None}
            or any(
                not _is_bool(row.get(field))
                for field in (
                    "trigger_emits",
                    "can_execute",
                    "execute_invokes_task",
                    "can_execute_changed_fires",
                )
            )
            for row in rows
        ):
            errors.append(f"{path.name}: row values violate command field domains")
    elif path.name == "derived-properties.json":
        transforms = value.get("transforms")
        if not isinstance(transforms, dict) or not all(
            isinstance(name, str) and isinstance(expression, str)
            for name, expression in transforms.items()
        ):
            errors.append(f"{path.name}: transforms must be an object")
        else:
            for row in rows:
                if isinstance(row, dict) and row.get("transform") not in transforms:
                    errors.append(f"{path.name}: scenario references an unknown transform")
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("expected_values"), list)
                    and isinstance(row.get("mutations"), list)
                    and len(row["expected_values"]) != len(row["mutations"]) + 1
                ):
                    errors.append(f"{path.name}: expected_values must cover initial plus mutations")
        if any(
            not isinstance(row, dict)
            or not isinstance(row.get("sources_initial"), list)
            or not row["sources_initial"]
            or not isinstance(row.get("transform"), str)
            or not isinstance(row.get("mutations"), list)
            or not isinstance(row.get("expected_values"), list)
            or any(
                not isinstance(mutation, list)
                or len(mutation) != 2
                or not isinstance(mutation[0], int)
                or isinstance(mutation[0], bool)
                or mutation[0] < 0
                or mutation[0] >= len(row["sources_initial"])
                for mutation in row.get("mutations", [])
            )
            for row in rows
        ):
            errors.append(f"{path.name}: scenario values violate derived-property domains")
    elif path.name == "message-ordering.json":
        for row in rows:
            if not isinstance(row, dict):
                continue
            arrays = [
                value
                for key, value in row.items()
                if key.startswith("producer_sends") or key.startswith("expected_observed")
            ]
            if (
                not isinstance(row.get("description"), str)
                or not row["description"].strip()
                or any(not _is_string_list(items) for items in arrays)
                or (
                    "subscriber_count" in row
                    and (
                        not isinstance(row["subscriber_count"], int)
                        or isinstance(row["subscriber_count"], bool)
                        or row["subscriber_count"] < 1
                    )
                )
                or (
                    "unsubscribe_after_first" in row
                    and not _is_bool(row["unsubscribe_after_first"])
                )
            ):
                errors.append(f"{path.name}: scenario values violate message field domains")
                break
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=Path("spec/fixtures"))
    args = parser.parse_args(argv)
    errors = [
        error
        for name in (*EXPECTED_IDS, "lifecycle-transitions.json")
        for error in validate_fixture(args.fixtures / name)
    ]
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: canonical fixture contracts and inventories are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
