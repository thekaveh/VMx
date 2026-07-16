#!/usr/bin/env python3
"""Resolve and run VMx from a fresh public SwiftPM consumer package."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_RESOURCES = frozenset(
    {
        "command-truthtable.json",
        "derived-properties.json",
        "lifecycle-transitions.json",
        "message-ordering.json",
    }
)
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _validate_inputs(url: str, version: str) -> None:
    if not url.startswith("https://"):
        raise ValueError("SwiftPM package URL must use https://")
    if _SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"expected an X.Y.Z semantic version, received {version!r}")


def render_manifest(url: str, version: str) -> str:
    """Render a standalone executable pinned to one exact SwiftPM release."""
    _validate_inputs(url, version)
    swift_url = json.dumps(url)
    swift_version = json.dumps(version)
    return f"""// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VMxSmoke",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: {swift_url}, exact: {swift_version}),
    ],
    targets: [
        .executableTarget(
            name: "VMxSmoke",
            dependencies: [.product(name: "VMx", package: "vmx")]
        ),
    ]
)
"""


def render_main(version: str) -> str:
    """Render a consumer executable that proves version and lifecycle behavior."""
    if _SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"expected an X.Y.Z semantic version, received {version!r}")
    swift_version = json.dumps(version)
    return f"""import VMx

guard VMxVersion.current == {swift_version} else {{
    fatalError("resolved VMx \\(VMxVersion.current), expected {version}")
}}

do {{
    let vm = try ComponentVM.builder()
        .name("swiftpm-remote-smoke")
        .withNullServices()
        .build()
    try vm.construct()
    guard vm.status == .constructed else {{
        fatalError("construct did not reach constructed")
    }}
    try vm.destruct()
    guard vm.status == .destructed else {{
        fatalError("destruct did not reach destructed")
    }}
    vm.dispose()
    guard vm.status == .disposed else {{
        fatalError("dispose did not reach disposed")
    }}
    print("VMx SwiftPM {version} lifecycle smoke passed")
}} catch {{
    fatalError("VMx lifecycle smoke failed: \\(error)")
}}
"""


def validate_resources(build_root: Path) -> None:
    """Require every VMx fixture inside a built SwiftPM resource bundle."""
    bundled = {
        path.name
        for path in build_root.rglob("*.json")
        if any(part.endswith((".bundle", ".resources")) for part in path.parts)
    }
    missing = sorted(EXPECTED_RESOURCES - bundled)
    if missing:
        raise RuntimeError("built VMx resource bundle is missing: " + ", ".join(missing))


def _run(args: list[str], *, cwd: Path, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def run_smoke(
    url: str,
    version: str,
    *,
    keep_directory: bool = False,
) -> Path | None:
    """Create, build, and run a disposable remote SwiftPM consumer."""
    _validate_inputs(url, version)
    workdir = Path(tempfile.mkdtemp(prefix="vmx-swiftpm-smoke-"))
    try:
        sources = workdir / "Sources" / "VMxSmoke"
        sources.mkdir(parents=True)
        (workdir / "Package.swift").write_text(
            render_manifest(url, version),
            encoding="utf-8",
        )
        (sources / "main.swift").write_text(render_main(version), encoding="utf-8")

        _run(["swift", "build"], cwd=workdir)
        validate_resources(workdir / ".build")
        bin_path = Path(
            _run(
                ["swift", "build", "--show-bin-path"],
                cwd=workdir,
                capture=True,
            )
        )
        _run([str(bin_path / "VMxSmoke")], cwd=workdir)
        print(f"OK: public SwiftPM consumer resolved VMx {version} and bundled all fixtures")
        if keep_directory:
            print(f"Kept smoke package at {workdir}")
            return workdir
        return None
    finally:
        if not keep_directory:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--keep-directory", action="store_true")
    args = parser.parse_args(argv)

    try:
        run_smoke(
            args.url,
            args.version,
            keep_directory=args.keep_directory,
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: SwiftPM consumer smoke failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
