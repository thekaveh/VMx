#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import TypedDict


class Diagram(TypedDict):
    id: str
    title: str
    html: str
    svg: str
    png: str
    referencedBy: list[str]


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def load_registry(path: Path) -> list[Diagram]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path, registry_path: Path, *, assets_only: bool = False) -> list[str]:
    errors: list[str] = []
    diagrams_dir = registry_path.parent
    for item in load_registry(registry_path):
        for key in ("html", "svg", "png"):
            asset = diagrams_dir / item[key]  # type: ignore[literal-required]
            if not asset.exists():
                errors.append(f"{item['id']}: missing {asset}")
        png = diagrams_dir / item["png"]
        if png.exists():
            try:
                width, height = png_size(png)
                if width <= height:
                    errors.append(f"{item['id']}: PNG is not landscape ({width}x{height})")
                if width < 2400:
                    errors.append(f"{item['id']}: PNG width {width} is below 2400px")
            except ValueError as exc:
                errors.append(str(exc))
        if assets_only:
            continue
        for ref in item["referencedBy"]:
            ref_path = root / ref
            if not ref_path.exists():
                errors.append(f"{item['id']}: missing reference file {ref}")
                continue
            text = ref_path.read_text(encoding="utf-8")
            if item["svg"] not in text and item["png"] not in text and item["html"] not in text:
                errors.append(f"{item['id']}: {ref} does not reference diagram asset")
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
