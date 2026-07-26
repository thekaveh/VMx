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


def _registry_version(package: str, version: str, timeout_seconds: float) -> str | None:
    try:
        result = subprocess.run(
            ["npm", "view", f"{package}@{version}", "version", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    value = json.loads(result.stdout)
    return value if isinstance(value, str) else None


def _registry_has_provenance(package: str, version: str, timeout_seconds: float) -> bool:
    try:
        result = subprocess.run(
            ["npm", "view", f"{package}@{version}", "dist.attestations", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return False
    if result.returncode != 0:
        return False
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    provenance = value.get("provenance") if isinstance(value, dict) else None
    return bool(
        isinstance(value, dict)
        and value.get("url")
        and isinstance(provenance, dict)
        and provenance.get("predicateType")
    )


def wait_for_version(
    package: str,
    version: str,
    timeout_seconds: float,
    *,
    interval_seconds: float = 10,
    lookup: Callable[[str, str, float], str | None] = _registry_version,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Poll npm until the exact immutable package version is visible."""
    _require_version(version)
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {package}@{version} on npm")
        if lookup(package, version, remaining) == version:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {package}@{version} on npm")
        sleeper(min(interval_seconds, remaining))


def wait_for_provenance(
    package: str,
    version: str,
    timeout_seconds: float,
    *,
    interval_seconds: float = 10,
    lookup: Callable[[str, str, float], bool] = _registry_has_provenance,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Poll npm until provenance metadata for the exact version is visible."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {package}@{version} provenance")
        if lookup(package, version, remaining):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {package}@{version} provenance")
        sleeper(min(interval_seconds, remaining))


def _remaining(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("npm consumer verification exceeded its end-to-end timeout")
    return min(maximum, remaining)


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


def _pack(package_dir: Path, destination: Path, *, timeout: float = 120) -> Path:
    result = subprocess.run(
        ["npm", "pack", "--json", "--pack-destination", str(destination)],
        cwd=package_dir,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
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


def _run(args: list[str], *, cwd: Path, timeout: float = 120) -> None:
    subprocess.run(args, cwd=cwd, check=True, timeout=timeout)


def run_smoke(
    version: str,
    *,
    package_dir: Path | None = None,
    poll_timeout: float = 600,
    timeout_seconds: float = 900,
    require_provenance: bool = False,
    keep_directory: bool = False,
) -> Path | None:
    """Install and probe a local packed package or exact public version."""
    _require_version(version)
    deadline = time.monotonic() + timeout_seconds
    workdir = Path(tempfile.mkdtemp(prefix="vmx-npm-smoke-"))
    try:
        if package_dir is None:
            wait_for_version(PACKAGE_NAME, version, _remaining(deadline, poll_timeout))
            package_spec = version
        else:
            tarball = _pack(package_dir.resolve(), workdir, timeout=_remaining(deadline, 120))
            package_spec = tarball.as_uri()

        (workdir / "package.json").write_text(render_package_json(package_spec), encoding="utf-8")
        (workdir / "smoke.mjs").write_text(render_esm(version), encoding="utf-8")
        (workdir / "smoke.cjs").write_text(render_commonjs(version), encoding="utf-8")
        (workdir / "types.mts").write_text(render_types(), encoding="utf-8")

        _run(
            ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=workdir,
            timeout=_remaining(deadline, 120),
        )
        _run(["node", "smoke.mjs"], cwd=workdir, timeout=_remaining(deadline, 120))
        _run(["node", "smoke.cjs"], cwd=workdir, timeout=_remaining(deadline, 120))
        _run(typescript_command(), cwd=workdir, timeout=_remaining(deadline, 120))
        if require_provenance:
            wait_for_provenance(
                PACKAGE_NAME,
                version,
                _remaining(deadline, poll_timeout),
            )
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
    parser.add_argument("--timeout", type=float, default=900, dest="timeout_seconds")
    parser.add_argument("--require-provenance", action="store_true")
    parser.add_argument("--keep-directory", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_smoke(
            args.version,
            package_dir=args.package_dir,
            poll_timeout=args.poll_timeout,
            timeout_seconds=args.timeout_seconds,
            require_provenance=args.require_provenance,
            keep_directory=args.keep_directory,
        )
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"ERROR: npm consumer smoke failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
