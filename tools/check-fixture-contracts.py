#!/usr/bin/env python3
"""Validate canonical fixtures against their published schemas and the rules left over.

Each fixture in spec/fixtures is validated against its JSON Schema in
spec/schemas/fixtures (ADR-0243). This tool then checks only the rules that JSON
Schema cannot express: the exact inventory of case, scenario and transition keys
(each key appears once across array items), and the cross-field rules of the
derived-property scenarios.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMAS = ROOT / "spec" / "schemas" / "fixtures"

FIXTURE_SCHEMAS: dict[str, str] = {
    "command-truthtable.json": "command-truthtable-v1.schema.json",
    "derived-properties.json": "derived-properties-v1.schema.json",
    "lifecycle-transitions.json": "lifecycle-transitions-v1.schema.json",
    "message-ordering.json": "message-ordering-v1.schema.json",
}

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


def _schema(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _inventory_errors(name: str, value: dict[str, Any]) -> list[str]:
    """Return the inventory and cross-field errors that a JSON Schema cannot express."""
    if name == "lifecycle-transitions.json":
        keys = [(row["from"], row["via"]) for row in value["transitions"]]
        if set(keys) != LIFECYCLE_KEYS or len(keys) != len(set(keys)):
            return [f"{name}: transitions must contain each of the 20 state/operation keys once"]
        return []
    array_name, id_name, expected = EXPECTED_IDS[name]
    identifiers = [row[id_name] for row in value[array_name]]
    if set(identifiers) != expected or len(identifiers) != len(set(identifiers)):
        return [
            f"{name}: {array_name} must contain the complete unique inventory {sorted(expected)}"
        ]
    if name != "derived-properties.json":
        return []
    errors: list[str] = []
    for row in value["scenarios"]:
        if row["transform"] not in value["transforms"]:
            errors.append(f"{name}: scenario {row['name']} references an unknown transform")
        if len(row["expected_values"]) != len(row["mutations"]) + 1:
            errors.append(
                f"{name}: scenario {row['name']} expected_values must cover initial plus mutations"
            )
        for index, _ in row["mutations"]:
            if index >= len(row["sources_initial"]):
                errors.append(
                    f"{name}: scenario {row['name']} mutation index {index} names no source"
                )
    return list(dict.fromkeys(errors))


def validate_fixture(path: Path, schemas: Path = DEFAULT_SCHEMAS) -> list[str]:
    """Return all contract errors for one canonical fixture."""
    schema_path = schemas / FIXTURE_SCHEMAS[path.name]
    try:
        validator = _schema(schema_path)
    except (OSError, json.JSONDecodeError, SchemaError) as error:
        return [f"{path.name}: no published schema could be read from {schema_path}: {error}"]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"{path.name}: {error}"]
    schema_errors = [
        f"{path.name}: {error.json_path}: {error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda item: item.json_path)
    ]
    if schema_errors:
        return schema_errors
    return _inventory_errors(path.name, value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=Path("spec/fixtures"))
    parser.add_argument("--schemas", type=Path, default=DEFAULT_SCHEMAS)
    args = parser.parse_args(argv)
    known = tuple(FIXTURE_SCHEMAS)
    errors = [
        f"{path.name}: no contract entry in tools/check-fixture-contracts.py"
        for path in sorted(args.fixtures.glob("*.json"))
        if path.name not in known
    ]
    errors += [
        f"{path.name}: no fixture for this published schema"
        for path in sorted(args.schemas.glob("*.json"))
        if path.name not in FIXTURE_SCHEMAS.values()
    ]
    errors += [
        error for name in known for error in validate_fixture(args.fixtures / name, args.schemas)
    ]
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: canonical fixtures match their published schemas and inventories are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
