#!/usr/bin/env python3
"""Build clean VMx consumers from local packages or the public NuGet feed."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

PACKAGE_IDS = {
    "VMx",
    "VMx.Notifications",
    "VMx.Extensions.DependencyInjection",
}
CORE_VERSION = "3.22.0"
NUGET_SOURCE = "https://api.nuget.org/v3/index.json"
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def parse_packages(specifications: list[str]) -> dict[str, str]:
    """Parse repeated ID=version arguments and add the companion core floor."""
    packages: dict[str, str] = {}
    for specification in specifications:
        if "=" not in specification:
            raise ValueError(f"expected PACKAGE=VERSION, received {specification!r}")
        package_id, version = specification.split("=", maxsplit=1)
        if package_id not in PACKAGE_IDS or _SEMVER.fullmatch(version) is None:
            raise ValueError(f"unknown package or non-release version: {specification!r}")
        packages[package_id] = version
    if not packages:
        raise ValueError("at least one --package is required")
    if any(package_id != "VMx" for package_id in packages):
        existing = packages.setdefault("VMx", CORE_VERSION)
        if existing != CORE_VERSION:
            raise ValueError(f"companions require VMx={CORE_VERSION}")
    return dict(sorted(packages.items()))


def discover_packages(project_root: Path) -> dict[str, str]:
    """Read current package IDs and versions from the public C# projects."""
    specifications: list[str] = []
    for project in sorted(project_root.glob("*/*.csproj")):
        root = ET.parse(project).getroot()
        package_id = root.findtext("PropertyGroup/PackageId")
        version = root.findtext("PropertyGroup/Version")
        if package_id and version:
            specifications.append(f"{package_id}={version}")
    return parse_packages(specifications)


def render_project(packages: dict[str, str], framework: str) -> str:
    """Render a package-only disposable consumer project."""
    references = "\n".join(
        f'    <PackageReference Include="{package_id}" Version="[{version}]" />'
        for package_id, version in packages.items()
    )
    output_type = "<OutputType>Exe</OutputType>" if framework == "net8.0" else ""
    return f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>{framework}</TargetFramework>
    {output_type}
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
  <ItemGroup>
{references}
  </ItemGroup>
</Project>
"""


def render_source(packages: dict[str, str], framework: str = "net8.0") -> str:
    """Render compile/runtime probes for the requested public assemblies."""
    usings = ["using System.Reflection;", "using VMx.Services;"]
    probes = [f'Check(typeof(MessageHub), "{packages["VMx"]}")']
    statements = ["using var hub = new MessageHub();"]
    if "VMx.Notifications" in packages:
        usings.append("using VMx.Notifications;")
        statements.append("using var notifications = new NotificationHub();")
        probes.append(f'Check(typeof(NotificationHub), "{packages["VMx.Notifications"]}")')
    if "VMx.Extensions.DependencyInjection" in packages:
        usings.extend(
            [
                "using Microsoft.Extensions.DependencyInjection;",
                "using VMx.Extensions.DependencyInjection;",
            ]
        )
        statements.append("Action<IServiceCollection> configure = services => services.AddVMx();")
        statements.append("_ = configure;")
        di_version = packages["VMx.Extensions.DependencyInjection"]
        probes.append(f'Check(typeof(ServiceCollectionExtensions), "{di_version}")')
    joined_probes = ", ".join(probes)
    check = """static string Check(Type type, string expected)
{
    var value = type.Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()
        ?.InformationalVersion.Split('+')[0];
    if (value != expected)
        throw new InvalidOperationException($"{type.Assembly.GetName().Name}: {value}");
    return value;
}"""
    if framework == "netstandard2.0":
        body = "\n".join(f"        {statement}" for statement in statements)
        return (
            "\n".join(usings)
            + f"""

namespace VmxNugetSmoke;

public static class Probe
{{
    public static string Run()
    {{
{body}
        return string.Join(",", {joined_probes});
    }}

    private {check}
}}
"""
        )
    return (
        "\n".join(usings)
        + f"\n\n{check}\n\n{chr(10).join(statements)}\n"
        + (f'Console.WriteLine(string.Join(",", {joined_probes}));\n')
    )


def flat_container_url(package_id: str) -> str:
    return f"https://api.nuget.org/v3-flatcontainer/{package_id.lower()}/index.json"


def _registry_has(package_id: str, version: str) -> bool:
    try:
        with urllib.request.urlopen(flat_container_url(package_id), timeout=20) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return version in payload.get("versions", [])


def wait_for_packages(
    packages: dict[str, str],
    timeout_seconds: float,
    *,
    interval_seconds: float = 15,
    lookup: Callable[[str, str], bool] = _registry_has,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Poll until every exact package version is visible."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if all(lookup(package_id, version) for package_id, version in packages.items()):
            return
        if time.monotonic() >= deadline:
            values = ", ".join(f"{key}@{value}" for key, value in packages.items())
            raise TimeoutError(f"timed out waiting for {values} on NuGet")
        sleeper(interval_seconds)


def run_smoke(
    packages: dict[str, str],
    framework: str,
    *,
    package_dir: Path | None = None,
    poll_timeout: float = 900,
) -> None:
    """Restore, compile, and where possible run a disposable consumer."""
    if package_dir is None:
        wait_for_packages(packages, poll_timeout)
    workdir = Path(tempfile.mkdtemp(prefix="vmx-nuget-smoke-"))
    try:
        (workdir / "Smoke.csproj").write_text(render_project(packages, framework), encoding="utf-8")
        (workdir / "Program.cs").write_text(render_source(packages, framework), encoding="utf-8")
        restore = ["dotnet", "restore", "Smoke.csproj", "--source", NUGET_SOURCE]
        if package_dir is not None:
            restore.extend(["--source", str(package_dir.resolve())])
        subprocess.run(restore, cwd=workdir, check=True)
        subprocess.run(
            ["dotnet", "build", "Smoke.csproj", "-c", "Release", "--no-restore", "--nologo"],
            cwd=workdir,
            check=True,
        )
        if framework == "net8.0":
            subprocess.run(
                ["dotnet", "run", "--project", "Smoke.csproj", "-c", "Release", "--no-build"],
                cwd=workdir,
                check=True,
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", default=[])
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--framework", choices=("net8.0", "netstandard2.0"), required=True)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--poll-timeout", type=float, default=900)
    args = parser.parse_args(argv)
    try:
        if bool(args.package) == bool(args.project_root):
            raise ValueError("use exactly one of --package or --project-root")
        packages = (
            parse_packages(args.package) if args.package else discover_packages(args.project_root)
        )
        run_smoke(
            packages,
            args.framework,
            package_dir=args.package_dir,
            poll_timeout=args.poll_timeout,
        )
    except (OSError, ValueError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"ERROR: NuGet consumer smoke failed: {error}", file=sys.stderr)
        return 1
    print(f"OK: NuGet {args.framework} consumer verified {len(packages)} exact package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
