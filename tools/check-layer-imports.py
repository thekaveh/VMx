#!/usr/bin/env python3
"""Phase 6 cross-layer import check (all three notes-showcase flavors).

Enforces the Pure-VM layering of spec §6.1:

* Models → may import Models only.
* ViewModels → may import Models + ViewModels (and the *adapter sub-layer*
  of Views, but never plain Views).
* Views → may import anywhere.

Why the adapter exception:

The C# Avalonia flavor places its INPC sidecars (``BindableDerived<T>``,
``BindableVm``, etc.) under ``Views/Adapter/`` because they're framework-
specific binding helpers, but the VM layer references them directly (the
WPF/Avalonia binding model requires INPC-aware properties to live on the
VM, not on the view). The Python and TypeScript flavors avoid this with
adapter-side helpers (``bind_derived_property`` / ``useDerivedProperty``)
because their binding models don't require an INPC sidecar.

To stay symmetric *and* faithful to the Pure-VM contract, the adapter
sub-layer (``Views.Adapter`` / ``views.adapter`` / ``views/adapter``) is
treated as a peer of the VM layer for import purposes. Plain Views (and
Views.Modals, etc.) are still off-limits.

Run from repo root:

    python3 tools/check-layer-imports.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Each flavor describes its import syntax + the layer roots within its src tree.
FLAVORS = {
    "csharp": {
        "root": "examples/csharp/avalonia/NotesShowcase",
        "suffixes": {".cs"},
        # `using NotesShowcase.Foo.Bar;` and `using static NotesShowcase.Foo.Bar;`
        "import_re": re.compile(r"^\s*using(?:\s+static)?\s+NotesShowcase\.([A-Za-z0-9_.]+)\s*;"),
        "layers": ["Models", "ViewModels", "Views"],
        "adapter_segment": "Views.Adapter",
    },
    "python": {
        "root": "examples/python/textual/notes_showcase/src/notes_showcase",
        "suffixes": {".py"},
        # `from notes_showcase.foo.bar import X` / `import notes_showcase.foo.bar`
        "import_re": re.compile(r"^\s*(?:from|import)\s+notes_showcase\.([A-Za-z0-9_.]+)"),
        "layers": ["models", "viewmodels", "views"],
        "adapter_segment": "views.adapter",
    },
    "typescript": {
        "root": "examples/typescript/react/notes-showcase/src",
        "suffixes": {".ts", ".tsx"},
        # `import … from "../viewmodels/foo.js"` etc. We use the path
        # specifier directly (no package name); the layer is taken from path
        # segments after resolving against the importing file's directory.
        # Also match the closing line of a MULTI-LINE import
        # (`} from "../views/x.js";`) — requiring the line to start with
        # `import` silently exempted the prevailing multi-line style.
        "import_re": re.compile(
            r'^\s*(?:import\s+(?:[^"\']+from\s+)?|\}?\s*from\s+)["\']([^"\']+)["\']'
        ),
        "layers": ["models", "viewmodels", "views"],
        "adapter_segment": "views/adapter",
    },
}


def _layer_of(path_parts: tuple[str, ...], layers: list[str]) -> str | None:
    """Return the first matching layer name found in the path parts (case-insensitive)."""
    lower = [p.lower() for p in path_parts]
    layer_lower = [layer.lower() for layer in layers]
    for p in lower:
        if p in layer_lower:
            return layers[layer_lower.index(p)]
    return None


def _ts_resolved_layer(
    importing: Path, specifier: str, base: Path, layers: list[str]
) -> str | None:
    """Resolve a TS relative/absolute import to the layer it targets.

    Returns the layer name (``models`` / ``viewmodels`` / ``views``) or ``None``
    if the specifier resolves outside the layered src tree (e.g. an npm package
    or ``vmx``).
    """
    if not specifier.startswith(("./", "../")):
        return None
    try:
        target = (importing.parent / specifier).resolve()
    except (OSError, RuntimeError):
        return None
    try:
        rel = target.relative_to(base)
    except ValueError:
        return None
    return _layer_of(rel.parts, layers)


def _csharp_layer_from_import(ns: str, layers: list[str]) -> str | None:
    """`Models.Foo` → 'Models'; `Views.Adapter.Foo` → 'Views' (adapter handled separately)."""
    head = ns.split(".", 1)[0]
    return head if head in layers else None


def _python_layer_from_import(module: str, layers: list[str]) -> str | None:
    head = module.split(".", 1)[0]
    return head if head in layers else None


def check_flavor(flavor: str, cfg: dict, repo_root: Path) -> list[str]:
    base = repo_root / cfg["root"]
    if not base.exists():
        return [f"{flavor}: source root not found: {base}"]

    layers: list[str] = cfg["layers"]
    adapter_segment: str = cfg["adapter_segment"]
    # Segment separator for the anchored adapter-exception check ("." for
    # C#/Python namespaces, "/" for TS paths) — an unanchored startswith
    # would also exempt e.g. `Views.AdapterEvil`.
    sep = "/" if "/" in adapter_segment else "."
    violations: list[str] = []

    for src in base.rglob("*"):
        if src.suffix not in cfg["suffixes"]:
            continue
        if not src.is_file():
            continue
        # Skip build artefacts.
        if any(part in {"bin", "obj", "node_modules", "dist", "__pycache__"} for part in src.parts):
            continue

        rel = src.relative_to(base)
        own_layer = _layer_of(rel.parts, layers)
        if own_layer is None:
            continue

        own_idx = layers.index(own_layer)
        forbidden_layers = layers[own_idx + 1 :]  # everything strictly above

        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            m = cfg["import_re"].match(line)
            if not m:
                continue

            target = m.group(1)

            if flavor == "typescript":
                # Resolve the relative import.
                tgt_layer = _ts_resolved_layer(src, target, base, layers)
                # Allow adapter even when importing from a VM:
                # check the resolved path against the adapter segment.
                if tgt_layer is None:
                    continue
                if tgt_layer == "views":
                    # Adapter sub-layer exception:
                    try:
                        resolved = (src.parent / target).resolve().relative_to(base)
                        # Anchored: "views/adapter" must appear as whole
                        # segments, not as a prefix of e.g. "views/adapterx".
                        if f"/{adapter_segment}/" in f"/{resolved.as_posix()}/":
                            continue
                    except (ValueError, OSError, RuntimeError):
                        pass
                if tgt_layer in forbidden_layers:
                    violations.append(
                        f"{flavor}: {rel}:{line_no}: forbidden import of {tgt_layer} "
                        f"from {own_layer}: {line.strip()}"
                    )

            elif flavor == "csharp":
                tgt_layer = _csharp_layer_from_import(target, layers)
                if tgt_layer is None:
                    continue
                # Adapter exception — `Views.Adapter.*` is allowed from VMs.
                if target == adapter_segment or target.startswith(adapter_segment + sep):
                    continue
                if tgt_layer in forbidden_layers:
                    violations.append(
                        f"{flavor}: {rel}:{line_no}: forbidden import of {tgt_layer} "
                        f"from {own_layer}: {line.strip()}"
                    )

            elif flavor == "python":
                tgt_layer = _python_layer_from_import(target, layers)
                if tgt_layer is None:
                    continue
                if target == adapter_segment or target.startswith(adapter_segment + sep):
                    continue
                if tgt_layer in forbidden_layers:
                    violations.append(
                        f"{flavor}: {rel}:{line_no}: forbidden import of {tgt_layer} "
                        f"from {own_layer}: {line.strip()}"
                    )

    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: current dir)")
    args = ap.parse_args()
    repo_root = Path(args.root).resolve()

    failures: list[str] = []
    checked = 0
    for flavor, cfg in FLAVORS.items():
        base = repo_root / cfg["root"]
        if base.exists():
            checked += 1
        failures.extend(check_flavor(flavor, cfg, repo_root))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(
            f"\n[FAIL] {len(failures)} layer violation(s) across {checked} flavors",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] cross-layer imports clean across {checked} flavors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
