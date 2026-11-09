"""Cross-cutting CI coverage contracts."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_every_workflow_job_has_a_hard_timeout() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        workflow = path.read_text(encoding="utf-8").split("\njobs:\n", maxsplit=1)[1]
        starts = list(re.finditer(r"(?m)^  ([A-Za-z0-9_-]+):\n", workflow))
        for index, start in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(workflow)
            job = workflow[start.start() : end]
            assert re.search(r"(?m)^    timeout-minutes: [1-9]\d*$", job), (
                f"{path.name}:{start.group(1)} lacks timeout"
            )


# #1440: these workflows run on pull requests, and a superseded run holds
# runners that the newer head needs.
_PULL_REQUEST_CI_WORKFLOWS = (
    "python",
    "csharp",
    "typescript",
    "swift",
    "rust",
    "conformance",
    "spec-discipline",
    "security-audit",
    "examples-contract-checks",
)


def workflow_concurrency(text: str) -> tuple[str, str] | None:
    """The workflow-level concurrency (group, cancel-in-progress), whitespace-folded."""
    header = text.split("\njobs:\n", maxsplit=1)[0]
    match = re.search(r"(?ms)^concurrency:\n(?P<body>(?:  .*\n|\n)*)", header + "\n")
    if match is None:
        return None
    body = match.group("body")
    group = re.search(r"(?ms)^  group:(?P<value>.*?)(?=^  \S|\Z)", body)
    cancel = re.search(r"(?m)^  cancel-in-progress:(?P<value>.*)$", body)
    if group is None or cancel is None:
        return None
    return " ".join(group.group("value").replace(">-", "").split()), cancel.group("value").strip()


def test_pull_request_runs_cancel_superseded_runs_and_branch_runs_never_share_a_group() -> None:
    for name in _PULL_REQUEST_CI_WORKFLOWS:
        concurrency = workflow_concurrency((WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8"))
        assert concurrency is not None, f"{name}.yml declares no workflow-level concurrency"
        group, cancel = concurrency
        # A pull_request run groups by workflow and pull-request number and
        # cancels the older run of that pull request.
        assert group.startswith("${{ github.event_name == 'pull_request' && "), name
        assert "format('{0}-pr-{1}', github.workflow, github.event.pull_request.number)" in group, (
            name
        )
        assert cancel == "${{ github.event_name == 'pull_request' }}", name
        # Every other event (push to develop or main, schedule,
        # workflow_dispatch) gets a group of its own, so it is never cancelled
        # or replaced as a pending run (#534).
        assert group.endswith("|| format('{0}-run-{1}', github.workflow, github.run_id) }}"), name


def test_concurrency_reader_rejects_a_workflow_without_a_group() -> None:
    assert workflow_concurrency("name: x\non: push\njobs:\n  a:\n") is None
    assert workflow_concurrency(
        "name: x\nconcurrency:\n  group: x-${{ github.ref }}\n  cancel-in-progress: false\n"
        "\njobs:\n  a:\n"
    ) == ("x-${{ github.ref }}", "false")


def test_recipe_suites_run_once_inside_the_package_test_steps() -> None:
    # #783: the C# Test step (VMx.sln) and both Swift package test steps already
    # run the recipe suites, so a filtered rerun step only repeats them.
    def commands(name: str) -> str:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        return re.sub(r"(?m)^\s*#.*\n", "", text)

    csharp = commands("csharp.yml")
    swift = commands("swift.yml")
    assert "XamlRecipeTests" not in csharp
    assert "SwiftUIRecipeTests" not in swift
    assert "dotnet test VMx.sln" in csharp
    assert "run: swift test --parallel\n" in swift
    assert "run: swift test --parallel --xunit-output" in swift


def test_release_verification_deadlines_fit_inside_job_timeouts() -> None:
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    cases = (
        ("csharp-verify-published", 25, 1200),
        ("typescript-verify-published", 20, 900),
        ("rust-verify-published", 45, 2100),
    )
    for name, job_minutes, helper_seconds in cases:
        match = re.search(
            rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
            workflow,
        )
        assert match is not None
        job = match.group("body")
        assert f"    timeout-minutes: {job_minutes}\n" in job
        assert f"--timeout {helper_seconds}" in job
        assert helper_seconds + 300 <= job_minutes * 60


def test_csharp_and_typescript_library_coverage_is_enforced() -> None:
    csharp = (WORKFLOWS / "csharp.yml").read_text(encoding="utf-8")
    typescript = (REPO_ROOT / "langs/typescript/vitest.config.ts").read_text(encoding="utf-8")

    assert "tools/check-cobertura-threshold.py" in csharp
    assert "minimum-line 90" in csharp
    assert "minimum-branch 82" in csharp
    for package in ("VMx", "VMx.Extensions.DependencyInjection", "VMx.Notifications"):
        assert f"--package {package}" in csharp
    assert "thresholds:" in typescript
    for threshold in ("statements: 85", "branches: 78", "functions: 85", "lines: 88"):
        assert threshold in typescript


def test_every_workflow_change_triggers_the_pin_inventory() -> None:
    conformance = (WORKFLOWS / "conformance.yml").read_text(encoding="utf-8")

    assert conformance.count('- ".github/workflows/**"') == 1
    assert "-- tools/check-workflow-pins.py" in conformance


def test_protected_branch_checks_are_always_present_and_aggregate_every_job() -> None:
    required = {
        "conformance.yml": ("required: conformance", None),
        "csharp.yml": ("required: csharp", "needs: [build, package, examples, wpf-example]"),
        "python.yml": (
            "required: python",
            "needs: [build, examples, small-examples, inspector, nicegui, package]",
        ),
        "rust.yml": ("required: rust", "needs: [audit, build, msrv, examples, package, coverage]"),
        "swift.yml": ("required: swift", "needs: [build, platforms, examples, coverage]"),
        "typescript.yml": (
            "required: typescript",
            "needs: [build, runtime-floor, react, react-runtime-floor, package, examples]",
        ),
        "docs.yml": ("required: docs", "needs: [build]"),
        "examples-contract-checks.yml": ("required: examples", None),
        "security-audit.yml": (
            "required: security",
            "needs: [secrets, codeql, npm, cargo, python, docs, nuget]",
        ),
        "spec-discipline.yml": ("required: spec discipline", None),
    }

    for filename, (context, needs) in required.items():
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        pull_request = workflow.split("  pull_request:\n", maxsplit=1)[1].split(
            "\njobs:", maxsplit=1
        )[0]
        assert "    paths:" not in pull_request, f"{filename} can skip its required check"
        assert f'name: "{context}"' in workflow
        if needs is not None:
            assert needs in workflow
            assert "    if: always()" in workflow
            assert "RESULTS: ${{ toJSON(needs) }}" in workflow


def test_wpf_example_builds_on_windows_with_real_xaml_enabled() -> None:
    csharp = (WORKFLOWS / "csharp.yml").read_text(encoding="utf-8")

    assert "wpf-example:" in csharp
    assert "runs-on: windows-latest" in csharp
    assert "dotnet build examples/csharp/wpf/TodoApp/WpfTodoApp.csproj -c Release" in csharp


def test_react_showcase_runs_complete_static_and_production_gates() -> None:
    typescript = (WORKFLOWS / "typescript.yml").read_text(encoding="utf-8")
    prefix = "--prefix examples/typescript/react/notes-showcase"

    assert f"npm run typecheck {prefix}" in typescript
    assert f"npm run lint {prefix}" in typescript
    assert f"npm run build {prefix}" in typescript


def test_spec_discipline_enforces_develop_first_gitflow() -> None:
    workflow = (WORKFLOWS / "spec-discipline.yml").read_text(encoding="utf-8")

    assert "Enforce develop-first gitflow" in workflow
    assert "BASE_REF: ${{ github.event.pull_request.base.ref }}" in workflow
    assert "HEAD_REF: ${{ github.event.pull_request.head.ref }}" in workflow
    assert "HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}" in workflow
    assert 'if [ "$BASE_REF" = "develop" ]; then' in workflow
    assert (
        'if [ "$HEAD_REPO" = "$GITHUB_REPOSITORY" ] && [ "$HEAD_REF" = "develop" ]; then'
        in workflow
    )
    assert "release-please--branches--main--components--python" in workflow
    assert "git diff --name-status" in workflow
    assert "git ls-tree" in workflow
    for path in (
        ".release-please-manifest.json",
        "compatibility-matrix.md",
        "langs/python/CHANGELOG.md",
        "langs/python/src/vmx/__about__.py",
    ):
        assert path in workflow


def test_spec_discipline_matches_only_the_exact_adr_bypass_label() -> None:
    workflow = (WORKFLOWS / "spec-discipline.yml").read_text(encoding="utf-8")

    assert "PR_LABELS_JSON: ${{ toJson(github.event.pull_request.labels.*.name) }}" in workflow
    assert "jq -e 'index(\"no-adr-needed\") != null'" in workflow
    assert "grep -q 'no-adr-needed'" not in workflow


def test_python_release_updates_the_compatibility_matrix() -> None:
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra_files = config["packages"]["langs/python"]["extra-files"]
    assert {"type": "generic", "path": "/compatibility-matrix.md"} in extra_files

    matrix = (REPO_ROOT / "compatibility-matrix.md").read_text(encoding="utf-8")
    header = next(line for line in matrix.splitlines() if line.startswith("| spec"))
    assert header.index("python") < header.index("csharp")
    current = next(line for line in matrix.splitlines() if line.startswith("| 3.30.x"))
    assert "x-release-please-version" in current


def test_release_yml_alone_creates_the_python_github_release() -> None:
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    assert config["packages"]["langs/python"]["skip-github-release"] is True

    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    notes = release.split("\n  python-release-notes:\n", 1)[1].split("\n  typescript:\n", 1)[0]
    assert "    needs: python-verify-published\n" in notes
    assert 'gh release create "$tag"' in notes

    runbook = (REPO_ROOT / "langs/python/RELEASING.md").read_text(encoding="utf-8")
    assert "skip-github-release: true" in runbook
    assert "autorelease: tagged" in runbook
    assert "tools/release-please-labels.py" in runbook


def _release_job(workflow: str, name: str) -> str:
    return workflow.split(f"\n  {name}:\n", 1)[1].split("\n\n  ", 1)[0]


def test_python_release_notes_job_relabels_after_the_github_release() -> None:
    # #1447: release-please builds no Python release, so release.yml relabels.
    job = _release_job(
        (WORKFLOWS / "release.yml").read_text(encoding="utf-8"), "python-release-notes"
    )

    assert "    permissions:\n      contents: write\n      pull-requests: write\n" in job
    create = job.index('gh release create "$tag"')
    relabel = job.index("python3 tools/release-please-labels.py relabel")
    assert create < relabel
    assert '--version "${GITHUB_REF#refs/tags/python-v}"' in job


def test_release_please_workflow_fails_on_a_stale_pending_label() -> None:
    workflow = (WORKFLOWS / "release-please.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read\n  pull-requests: read\n" in workflow
    check = workflow.index("run: python3 tools/release-please-labels.py check")
    action = workflow.index("googleapis/release-please-action@")
    assert check < action
    step = workflow[workflow.rindex("      - name:", 0, check) : check]
    assert "if:" not in step
    assert "GH_TOKEN: ${{ github.token }}" in step


def test_release_please_explicitly_targets_main_when_develop_is_default() -> None:
    workflow = (WORKFLOWS / "release-please.yml").read_text(encoding="utf-8")

    assert "    branches: [main]" in workflow
    assert "          target-branch: main" in workflow


def test_release_please_restores_unreleased_on_existing_internal_pr_branch() -> None:
    workflow = (WORKFLOWS / "release-please.yml").read_text(encoding="utf-8")

    assert "      - name: Maintain Python release PR\n        id: release\n" in workflow
    assert "      - name: Locate the open Python release PR\n        id: release-pr\n" in workflow
    assert "gh api --method GET" in workflow
    assert '"repos/$GITHUB_REPOSITORY/pulls"' in workflow
    assert '-f "head=$GITHUB_REPOSITORY_OWNER:$RELEASE_PR_HEAD"' in workflow
    assert "-f state=open" in workflow
    assert "-f base=main" in workflow
    assert 'echo "found=false" >> "$GITHUB_OUTPUT"' in workflow
    assert "expected at most one" in workflow
    assert "fromJSON(steps.release.outputs.pr)" not in workflow
    assert "if: steps.release-pr.outputs.found == 'true'" in workflow
    assert "ref: ${{ steps.release-pr.outputs.head }}" in workflow
    assert "token: ${{ secrets.RELEASE_PLEASE_TOKEN }}" in workflow
    assert "path: release-pr" in workflow
    assert (
        "python3 tools/ensure-release-changelog-unreleased.py \\\n"
        "            release-pr/langs/python/CHANGELOG.md" in workflow
    )
    assert "git -C release-pr diff --quiet -- langs/python/CHANGELOG.md" in workflow
    assert 'git -C release-pr commit -m "chore: restore unreleased changelog section"' in workflow
    assert 'git -C release-pr push origin "HEAD:${RELEASE_PR_HEAD}"' in workflow


def test_swift_coverage_counts_concurrently_executed_regions_exactly() -> None:
    # A region after a guard counts as entry minus early returns. Plain
    # counter updates lose increments when tests call the same function from
    # many threads, so the region can read as unexecuted (#513).
    swift = (WORKFLOWS / "swift.yml").read_text(encoding="utf-8")
    coverage = swift.split("\n  coverage:\n", maxsplit=1)[1].split("\n  required:\n")[0]
    coverage = " ".join(coverage.split())  # read folded `run: >-` commands as one line

    assert (
        "swift test --package-path langs/swift --enable-code-coverage"
        " -Xswiftc -Xllvm -Xswiftc -instrprof-atomic-counter-update-all"
    ) in coverage


def test_swift_example_tests_fail_fast_and_name_a_hung_case() -> None:
    # A hung NotesShowcase case once held the job until its 30-minute timeout
    # with no name in the log (#533). The watchdog kills and names it instead.
    swift = (WORKFLOWS / "swift.yml").read_text(encoding="utf-8")
    examples = swift.split("\n  examples:\n", maxsplit=1)[1].split("\n  coverage:\n")[0]
    examples = " ".join(examples.split())  # read folded `run: >-` commands as one line

    assert (
        "python3 ../../../tools/swift-test-watchdog.py --per-test-timeout 120"
        " -- swift test --parallel"
    ) in examples
    assert '"tools/swift-test-watchdog.py"' in swift.split("\njobs:\n", maxsplit=1)[0]


def _dotnet_test_commands(workflow: str) -> list[str]:
    """Each `dotnet test` command with its continuation and folded lines."""
    lines = workflow.splitlines()
    commands = []
    for index, line in enumerate(lines):
        if "dotnet test" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        command = [line.strip()]
        for follow in lines[index + 1 :]:
            stripped = follow.strip()
            follow_indent = len(follow) - len(follow.lstrip())
            if not stripped or follow_indent < indent or stripped.startswith(("done", "- ", "#")):
                break
            command.append(stripped)
        commands.append(" ".join(command))
    return commands


def test_filtered_csharp_test_steps_fail_when_no_test_matches() -> None:
    csharp = (WORKFLOWS / "csharp.yml").read_text(encoding="utf-8")
    filtered = [command for command in _dotnet_test_commands(csharp) if "--filter" in command]
    assert filtered, "csharp.yml has no filtered dotnet test command"
    for command in filtered:
        assert "RunConfiguration.TreatNoTestsAsError=true" in command, command


# #1333: a step in a job with id-token: write can request the publishing OIDC
# token, so such a job must not install, build or test third-party code.
_OIDC_FORBIDDEN = (
    re.compile(r"\bnpm ci\b"),
    re.compile(r"\bnpm (?:run|test)\b"),
    re.compile(r"\bnpm install\b(?! --global npm@\d+\.\d+\.\d+\s*$)"),
    re.compile(r"\buv (?:sync|build|run|pip|tool|venv)\b"),
    re.compile(r"\buvx\b"),
    re.compile(r"\bpytest\b"),
    re.compile(r"\bcargo (?:test|build|clippy|install)\b"),
    re.compile(r"\bdotnet (?:restore|build|test|pack)\b"),
    re.compile(r"tools/smoke-[a-z-]+\.py"),
)


def _workflow_jobs(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", maxsplit=1)[1]
    body = re.sub(r"(?m)^\s*#.*\n", "", body)
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):\n", body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def oidc_job_violations(text: str) -> list[str]:
    """Return 'job: line' for each forbidden command in a job with id-token: write."""
    violations: list[str] = []
    for name, job in _workflow_jobs(text).items():
        if not re.search(r"(?m)^      id-token: write$", job):
            continue
        violations.extend(
            f"{name}: {line.strip()}"
            for line in job.splitlines()
            if any(pattern.search(line) for pattern in _OIDC_FORBIDDEN)
        )
    return violations


def test_release_jobs_with_id_token_install_build_and_test_nothing() -> None:
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert oidc_job_violations(workflow) == []


def test_oidc_job_check_rejects_each_forbidden_command() -> None:
    for command in (
        "npm ci",
        "npm test --prefix packages/react",
        "uv sync --project langs/python --locked --all-extras",
        "uv build --project langs/python --out-dir dist",
        "uv run python -m pytest",
        "python3 tools/smoke-rust-consumer.py --package-dir langs/rust",
        "npm install left-pad",
    ):
        workflow = (
            "on: push\njobs:\n  publish:\n    permissions:\n      id-token: write\n"
            f"    steps:\n      - run: {command}\n"
        )
        assert oidc_job_violations(workflow) == [f"publish: - run: {command}"], command
    allowed = (
        "on: push\njobs:\n  publish:\n    permissions:\n      id-token: write\n"
        "    steps:\n      - run: npm install --global npm@11.18.0\n"
        "  build:\n    permissions:\n      contents: read\n"
        "    steps:\n      - run: npm ci\n"
    )
    assert oidc_job_violations(allowed) == []


def test_registry_publish_jobs_alone_hold_id_token_and_an_environment() -> None:
    jobs = _workflow_jobs((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
    oidc = {name for name, job in jobs.items() if "      id-token: write\n" in job}
    environments = {name for name, job in jobs.items() if "    environment:\n" in job}
    publishers = {
        "csharp-publish",
        "python-publish",
        "typescript-publish",
        "react-publish",
        "rust-publish",
    }
    assert oidc == environments == publishers
    for flavor, artifact in (
        ("python", "python-dist-${{ github.run_id }}"),
        ("typescript", "typescript-release-${{ github.run_id }}"),
        ("react", "react-release-${{ github.run_id }}"),
    ):
        build = jobs[f"{flavor}-build"]
        publish = jobs[f"{flavor}-publish"]
        assert "actions/upload-artifact@" in build
        assert f"name: {artifact}" in build
        assert "actions/download-artifact@" in publish
        assert f"name: {artifact}" in publish
        assert f"needs: [{flavor}-build, release-metadata]" in publish
        assert "actions/checkout@" not in publish
    for flavor in ("typescript", "react"):
        publish = jobs[f"{flavor}-publish"]
        assert publish.count('npm publish "$TARBALL" --access public') == 2
    assert "smoke-rust-consumer.py" in jobs["rust-test"]
