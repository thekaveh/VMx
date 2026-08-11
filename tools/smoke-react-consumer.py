#!/usr/bin/env python3
"""Pack VMx + its React adapter and verify a fresh ESM/CJS SSR consumer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, cache: Path) -> str:
    env = {**os.environ, "npm_config_cache": str(cache)}
    return subprocess.run(
        command, cwd=cwd, check=True, text=True, capture_output=True, env=env, timeout=300
    ).stdout


def pack(package: Path, destination: Path) -> Path:
    payload = json.loads(
        run(
            [
                "npm",
                "pack",
                "--json",
                "--ignore-scripts",
                "--pack-destination",
                str(destination),
            ],
            package,
            destination / ".npm-cache",
        )
    )
    return destination / payload[0]["filename"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--react", default="19.2.8")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="vmx-react-consumer-") as directory:
        work = Path(directory)
        core = pack(ROOT / "langs" / "typescript", work)
        adapter = pack(ROOT / "packages" / "react", work)
        (work / "package.json").write_text(
            json.dumps({"private": True, "type": "module"}), encoding="utf-8"
        )
        run(
            [
                "npm",
                "install",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                str(core),
                str(adapter),
                f"react@{args.react}",
                f"react-dom@{args.react}",
                "rxjs@7.8.2",
                "use-sync-external-store@1.6.0",
            ],
            work,
            work / ".npm-cache",
        )
        source = """
import React from 'react';
import { renderToString } from 'react-dom/server';
import { MessageHub } from '@thekaveh/vmx';
import { createVmxStore, useVmx } from '@thekaveh/vmx-react';
const store = createVmxStore(new MessageHub());
function App() { return React.createElement('span', null, useVmx(store, () => 'vmx-react')); }
if (renderToString(React.createElement(App)) !== '<span>vmx-react</span>') process.exit(1);
store.dispose();
"""
        (work / "smoke.mjs").write_text(source, encoding="utf-8")
        run(["node", "smoke.mjs"], work, work / ".npm-cache")
        cjs = """
const adapter = require('@thekaveh/vmx-react');
const valid = typeof adapter.createVmxStore === 'function'
  && typeof adapter.useVm === 'function';
if (!valid) process.exit(1);
"""
        (work / "smoke.cjs").write_text(cjs, encoding="utf-8")
        run(["node", "smoke.cjs"], work, work / ".npm-cache")
    print(f"OK: fresh React {args.react} ESM/CJS consumer passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
