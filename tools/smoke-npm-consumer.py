#!/usr/bin/env python3
"""Install and verify VMx from a local tarball or the public npm registry."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

PACKAGE_NAME = "@thekaveh/vmx"
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _require_version(version: str) -> None:
    if _SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"expected an X.Y.Z release version, received {version!r}")


def render_package_json(package_spec: str) -> str:
    """Render the disposable consumer manifest."""
    return (
        json.dumps(
            {
                "name": "vmx-npm-smoke",
                "version": "0.0.0",
                "private": True,
                "type": "module",
                "dependencies": {
                    PACKAGE_NAME: package_spec,
                    "rxjs": "^7.8.0",
                },
                "devDependencies": {"typescript": "^5.4.0"},
            },
            indent=2,
        )
        + "\n"
    )


def render_esm(version: str) -> str:
    """Render ESM runtime probes for every public package entry."""
    _require_version(version)
    expected = json.dumps(version)
    return f"""import {{ __version__, MessageHub }} from "@thekaveh/vmx";
import {{ NotificationHub }} from "@thekaveh/vmx/notifications";
import {{ consumerConformanceSchema }} from "@thekaveh/vmx/conformance";

if (__version__ !== {expected}) throw new Error(`expected {version}, received ${{__version__}}`);
if (typeof MessageHub !== "function") throw new Error("missing root MessageHub export");
if (typeof NotificationHub !== "function") throw new Error("missing notifications export");
if (typeof consumerConformanceSchema !== "object") throw new Error("missing conformance export");
console.log("VMx npm ESM smoke passed");
"""


def render_commonjs(version: str) -> str:
    """Render CommonJS runtime probes for every public package entry."""
    _require_version(version)
    expected = json.dumps(version)
    return f"""const vmx = require("@thekaveh/vmx");
const notifications = require("@thekaveh/vmx/notifications");
const conformance = require("@thekaveh/vmx/conformance");

if (vmx.__version__ !== {expected}) {{
  throw new Error(`expected {version}, received ${{vmx.__version__}}`);
}}
if (typeof vmx.MessageHub !== "function") throw new Error("missing root MessageHub export");
if (typeof notifications.NotificationHub !== "function") {{
  throw new Error("missing notifications export");
}}
if (typeof conformance.consumerConformanceSchema !== "object") {{
  throw new Error("missing conformance export");
}}
console.log("VMx npm CommonJS smoke passed");
"""


def render_types() -> str:
    """Render a NodeNext declaration probe for every public package entry."""
    return """import { __version__, type IMessageHub } from "@thekaveh/vmx";
import { type INotificationHub } from "@thekaveh/vmx/notifications";
import { type ConsumerConformanceSuite } from "@thekaveh/vmx/conformance";

declare const hub: IMessageHub;
declare const notifications: INotificationHub;
declare const suite: ConsumerConformanceSuite;
const version: string = __version__;
void [hub, notifications, suite, version];
"""


def typescript_command() -> list[str]:
    """Return the declaration probe command at VMx's public TypeScript floor."""
    return [
        "npx",
        "--no-install",
        "tsc",
        "--noEmit",
        "--strict",
        "--module",
        "NodeNext",
        "--moduleResolution",
        "NodeNext",
        "--target",
        "ES2020",
        "types.mts",
        "--lib",
        "ES2020,ES2022.Error,ESNext.Disposable,DOM",
    ]


def _registry_version(package: str, version: str) -> str | None:
    result = subprocess.run(
        ["npm", "view", f"{package}@{version}", "version", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = json.loads(result.stdout)
    return value if isinstance(value, str) else None


def wait_for_version(
    package: str,
    version: str,
    timeout_seconds: float,
    *,
    interval_seconds: float = 10,
    lookup: Callable[[str, str], str | None] = _registry_version,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Poll npm until the exact immutable package version is visible."""
    _require_version(version)
    deadline = time.monotonic() + timeout_seconds
    while True:
        if lookup(package, version) == version:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {package}@{version} on npm")
        sleeper(interval_seconds)


def json_array(output: str) -> list[object]:
    """Return the trailing JSON array after any npm lifecycle output."""
    for index in range(len(output) - 1, -1, -1):
        if output[index] != "[":
            continue
        try:
            payload = json.loads(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return payload
    raise ValueError("npm command did not emit a valid JSON array")


def _pack(package_dir: Path, destination: Path) -> Path:
    result = subprocess.run(
        ["npm", "pack", "--json", "--pack-destination", str(destination)],
        cwd=package_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json_array(result.stdout)
    if len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError("npm pack JSON must contain exactly one package")
    filename = payload[0].get("filename")
    if not isinstance(filename, str):
        raise ValueError("npm pack JSON has no filename")
    tarball = destination / filename
    if not tarball.is_file():
        raise ValueError(f"npm pack did not create {tarball}")
    return tarball


def _run(args: list[str], *, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def run_smoke(
    version: str,
    *,
    package_dir: Path | None = None,
    poll_timeout: float = 600,
    keep_directory: bool = False,
) -> Path | None:
    """Install and probe a local packed package or exact public version."""
    _require_version(version)
    workdir = Path(tempfile.mkdtemp(prefix="vmx-npm-smoke-"))
    try:
        if package_dir is None:
            wait_for_version(PACKAGE_NAME, version, poll_timeout)
            package_spec = version
        else:
            tarball = _pack(package_dir.resolve(), workdir)
            package_spec = tarball.as_uri()

        (workdir / "package.json").write_text(render_package_json(package_spec), encoding="utf-8")
        (workdir / "smoke.mjs").write_text(render_esm(version), encoding="utf-8")
        (workdir / "smoke.cjs").write_text(render_commonjs(version), encoding="utf-8")
        (workdir / "types.mts").write_text(render_types(), encoding="utf-8")

        _run(
            ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=workdir,
        )
        _run(["node", "smoke.mjs"], cwd=workdir)
        _run(["node", "smoke.cjs"], cwd=workdir)
        _run(typescript_command(), cwd=workdir)
        print(
            f"OK: npm consumer verified {PACKAGE_NAME}@{version} "
            "as ESM, CommonJS, and NodeNext declarations"
        )
        if keep_directory:
            print(f"Kept smoke consumer at {workdir}")
            return workdir
        return None
    finally:
        if not keep_directory:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--poll-timeout", type=float, default=600)
    parser.add_argument("--keep-directory", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_smoke(
            args.version,
            package_dir=args.package_dir,
            poll_timeout=args.poll_timeout,
            keep_directory=args.keep_directory,
        )
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"ERROR: npm consumer smoke failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
