#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import TypedDict

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Diagram(TypedDict):
    id: str
    title: str
    html: str
    svg: str
    png: str
    referencedBy: list[str]


def type_name(value: object) -> str:
    return type(value).__name__


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG")
    if len(data) < 24:
        raise ValueError("truncated PNG")
    if data[12:16] != b"IHDR":
        raise ValueError("malformed PNG")
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error as exc:
        raise ValueError("truncated PNG") from exc
    if width == 0 or height == 0:
        raise ValueError(f"invalid PNG dimensions {width}x{height}")
    return width, height


def load_registry(path: Path) -> tuple[list[object], list[str]]:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"{path}: invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"]

    if not isinstance(registry, list):
        return [], [f"{path}: registry must be a JSON array"]

    return registry, []


def validate_diagram_row(item: object, index: int) -> tuple[Diagram | None, list[str]]:
    context = f"registry[{index}]"
    errors: list[str] = []
    if not isinstance(item, dict):
        return None, [f"{context}: expected object, got {type_name(item)}"]

    values: dict[str, str] = {}
    for key in ("id", "title", "html", "svg", "png"):
        if key not in item:
            errors.append(f"{context}: missing required key '{key}'")
            continue
        value = item[key]
        if not isinstance(value, str):
            errors.append(f"{context}.{key}: expected string, got {type_name(value)}")
            continue
        values[key] = value

    if "referencedBy" not in item:
        errors.append(f"{context}: missing required key 'referencedBy'")
    else:
        referenced_by = item["referencedBy"]
        if not isinstance(referenced_by, list):
            errors.append(
                f"{context}.referencedBy: expected list[str], got {type_name(referenced_by)}"
            )
        else:
            for ref_index, ref in enumerate(referenced_by):
                if not isinstance(ref, str):
                    errors.append(
                        f"{context}.referencedBy[{ref_index}]: expected string, got "
                        f"{type_name(ref)}"
                    )

    if errors:
        return None, errors

    diagram: Diagram = {
        "id": values["id"],
        "title": values["title"],
        "html": values["html"],
        "svg": values["svg"],
        "png": values["png"],
        "referencedBy": item["referencedBy"],
    }
    return diagram, []


def validate(root: Path, registry_path: Path, *, assets_only: bool = False) -> list[str]:
    errors: list[str] = []
    diagrams_dir = registry_path.parent
    registry, registry_errors = load_registry(registry_path)
    errors.extend(registry_errors)
    for index, item in enumerate(registry):
        diagram, row_errors = validate_diagram_row(item, index)
        errors.extend(row_errors)
        if diagram is None:
            continue
        for key in ("html", "svg", "png"):
            asset = diagrams_dir / diagram[key]
            if not asset.exists():
                errors.append(f"{diagram['id']}: missing {asset}")
        png = diagrams_dir / diagram["png"]
        if png.exists():
            try:
                width, height = png_size(png)
                if width <= height:
                    errors.append(f"{diagram['id']}: PNG is not landscape ({width}x{height})")
                if width < 2400:
                    errors.append(f"{diagram['id']}: PNG width {width} is below 2400px")
            except ValueError as exc:
                errors.append(f"{diagram['id']}: {exc}")
        if assets_only:
            continue
        for ref in diagram["referencedBy"]:
            ref_path = root / ref
            if not ref_path.exists():
                errors.append(f"{diagram['id']}: missing reference file {ref}")
                continue
            text = ref_path.read_text(encoding="utf-8")
            if (
                diagram["svg"] not in text
                and diagram["png"] not in text
                and diagram["html"] not in text
            ):
                errors.append(f"{diagram['id']}: {ref} does not reference diagram asset")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--registry", default="docs/assets/diagrams/diagram-registry.json")
    parser.add_argument("--assets-only", action="store_true")
    args = parser.parse_args()
    errors = validate(Path(args.root), Path(args.registry), assets_only=args.assets_only)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("diagram validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
