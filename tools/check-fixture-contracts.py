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
    if path.name == "derived-properties.json":
        transforms = value.get("transforms")
        if not isinstance(transforms, dict):
            errors.append(f"{path.name}: transforms must be an object")
        else:
            for row in rows:
                if isinstance(row, dict) and row.get("transform") not in transforms:
                    errors.append(f"{path.name}: scenario references an unknown transform")
                if (
                    isinstance(row, dict)
                    and len(row.get("expected_values", [])) != len(row.get("mutations", [])) + 1
                ):
                    errors.append(f"{path.name}: expected_values must cover initial plus mutations")
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
