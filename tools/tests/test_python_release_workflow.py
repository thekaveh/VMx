"""Contract tests for reproducible Python conformance and release jobs."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_python_release_jobs_use_the_tracked_lockfile() -> None:
    workflow = _workflow("release.yml")
    python_jobs = workflow.split("\n  python-test:\n", maxsplit=1)[1].split(
        "\n  typescript:\n", maxsplit=1
    )[0]

    assert "langs/python/uv.lock" in python_jobs
    assert "uv sync --locked --all-extras" in python_jobs
    assert "uv.lock is gitignored" not in python_jobs


def test_python_build_backend_is_exactly_pinned() -> None:
    pyproject = (REPO_ROOT / "langs" / "python" / "pyproject.toml").read_text(encoding="utf-8")
    build_system = pyproject.split("[build-system]\n", maxsplit=1)[1].split("\n[", maxsplit=1)[0]

    assert 'requires = ["hatchling==1.31.0"]' in build_system


def test_python_release_smokes_local_wheel_before_publish() -> None:
    workflow = _workflow("release.yml")
    publish_job = workflow.split("\n  python-build-and-publish:\n", maxsplit=1)[1].split(
        "\n  python-verify-published:\n", maxsplit=1
    )[0]

    build_index = publish_job.index("uv build --project langs/python --out-dir dist")
    install_index = publish_job.index("uv pip install --python .package-venv/bin/python dist/*.whl")
    smoke_index = publish_job.index(
        ".package-venv/bin/python tools/check-python-interpreter.py "
        "--expected-version 3.12 --venv .package-venv -- "
        'langs/python/scripts/smoke_test.py "$tag_version"'
    )
    publish_index = publish_job.index("pypa/gh-action-pypi-publish@")

    assert build_index < install_index < smoke_index < publish_index
    assert "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33" in publish_job


def test_python_ci_and_release_test_the_extracted_sdist() -> None:
    ci = _workflow("python.yml")
    release = _workflow("release.yml")

    for workflow in (ci, release):
        assert "tar -xzf" in workflow
        assert 'uv sync --project "$sdist_root" --locked --all-extras' in workflow
        assert (
            'uv run --project "$sdist_root" python tools/check-python-interpreter.py '
            '--venv "$sdist_root/.venv" -- -m pytest "$sdist_root/tests/conformance" -q' in workflow
        )


def test_python_ci_and_release_verify_exact_archives_and_ci_smokes_wheel() -> None:
    ci = _workflow("python.yml")
    release = _workflow("release.yml")
    checker = "-- tools/check-python-package.py --dist dist"

    assert checker in ci
    assert checker in release
    assert "uv pip install --python .package-venv/bin/python dist/*.whl" in ci
    assert (
        ".package-venv/bin/python tools/check-python-interpreter.py "
        "--expected-version 3.12 --venv .package-venv -- "
        'langs/python/scripts/smoke_test.py "$version"' in ci
    )


def test_conformance_job_uses_the_tracked_python_lockfile() -> None:
    workflow = _workflow("conformance.yml")

    assert "uv --project langs/python sync --locked --all-extras" in workflow
    assert "uv --project langs/python run --locked --extra tools" in workflow


def test_python_ci_and_release_cover_314_and_audit_runtime_dependencies() -> None:
    ci = _workflow("python.yml")
    release = _workflow("release.yml")

    assert 'python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]' in ci
    assert 'python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]' in release
    assert "uv export --locked --no-dev --no-emit-project" in ci
    assert (
        "uvx --from pip-audit==2.10.1 python "
        '"$GITHUB_WORKSPACE/tools/check-python-interpreter.py" --tool-context -- -m pip_audit' in ci
    )
    assert (
        "uvx --from pip-audit==2.10.1 python "
        '"$GITHUB_WORKSPACE/tools/check-python-interpreter.py" --tool-context -- -m pip_audit'
        in release
    )


def test_release_metadata_is_validated_before_python_publication() -> None:
    workflow = _workflow("release.yml")
    metadata = workflow.index("release-metadata:")
    checker = workflow.index("tools/check-version-consistency.py", metadata)
    publish_job = workflow.index("python-build-and-publish:")
    publish = workflow.index("pypa/gh-action-pypi-publish@", publish_job)

    assert "needs: [python-test, release-metadata]" in workflow
    assert "uv --project langs/python sync --locked --extra tools" in workflow
    assert "uv --project langs/python run --locked --extra tools" in workflow
    assert (
        'tools/check-version-consistency.py\n          --release-tag "$GITHUB_REF_NAME"' in workflow
    )
    assert metadata < checker < publish


def _jobs(name: str) -> dict[str, str]:
    import re

    parts = re.split(r"^  ([a-z][a-z-]*):\n", _workflow(name).split("\njobs:\n")[1], flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_every_uv_setup_selects_python() -> None:
    import re

    for name in (
        "python.yml",
        "release.yml",
        "conformance.yml",
        "examples-contract-checks.yml",
        "security-audit.yml",
    ):
        for job in _jobs(name).values():
            for setup in re.findall(r"uses: astral-sh/setup-uv@.*?(?=\n      -|\Z)", job, re.S):
                assert (
                    'python-version: "3.12"' in setup
                    or "python-version: ${{ matrix.python-version }}" in setup
                )


def test_both_matrices_capture_identity_and_exercise_mismatch_with_cache_evidence() -> None:
    for name, key in (("python.yml", "build"), ("release.yml", "python-test")):
        job = _jobs(name)[key]
        assert "id: setup-uv" in job
        assert "steps.setup-uv.outputs.cache-hit" in job
        assert "uv python install 3.14" in job
        assert "uv python list --only-installed --managed-python" in job
        assert "uv venv --python 3.14 .venv" in job
        assert (
            ".venv/bin/python ../../tools/check-python-interpreter.py "
            "--expected-version 3.14 --venv .venv" in job
        )
        assert "--capture-output" in job
        for module in (
            "ruff check src tests",
            "ruff format --check src tests",
            "mypy --strict src/vmx",
            "pytest",
        ):
            assert (
                '--expected-executable "${{ steps.interpreter.outputs.executable }}" '
                f"-- -m {module}" in job
            )
    assert '"tools/check-python-interpreter.py"' in _workflow("python.yml")


def test_release_dispatch_runs_only_python_validation_even_on_tag_refs() -> None:
    import re

    workflow = _workflow("release.yml")
    assert "  workflow_dispatch:" in workflow
    assert "group: release-${{ github.event_name }}-${{ github.ref }}" in workflow
    for name, job in _jobs("release.yml").items():
        condition = re.search(r"^    if: (.+)$", job, re.M)
        assert condition is not None, name
        expression = condition.group(1)
        # Evaluate the deliberately small event/ref expression grammar used by this workflow.
        for ref in (
            "refs/heads/develop",
            "refs/tags/python-v1.0.0",
            "refs/tags/csharp-v1.0.0",
            "refs/tags/react-v1.0.0",
            "refs/tags/swift-v1.0.0",
            "refs/tags/rust-v1.0.0",
            "refs/tags/typescript-v1.0.0",
        ):
            expr = expression.replace("github.event_name", repr("workflow_dispatch")).replace(
                "github.ref", repr(ref)
            )
            expr = expr.replace("&&", " and ").replace("||", " or ")
            allowed = eval(expr, {"__builtins__": {}, "startsWith": str.startswith})
            assert bool(allowed) == (name == "python-test"), (name, ref)
        if name != "python-test":
            assert expression.startswith("github.event_name == 'push'"), name
    test_job = _jobs("release.yml")["python-test"]
    assert "name: Verify tag commit is on main\n        if: github.event_name == 'push'" in test_job
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in test_job


def test_release_push_still_selects_only_the_matching_flavor() -> None:
    import re

    refs = [
        f"refs/tags/{flavor}-v1.0.0"
        for flavor in (
            "python",
            "csharp",
            "csharp-notifications",
            "csharp-dependency-injection",
            "typescript",
            "react",
            "rust",
            "swift",
        )
    ]
    for name, job in _jobs("release.yml").items():
        condition = re.search(r"^    if: (.+)$", job, re.M)
        assert condition is not None
        for ref in refs:
            expression = condition.group(1).replace("github.event_name", repr("push"))
            expression = expression.replace("github.ref", repr(ref))
            expression = expression.replace("&&", " and ").replace("||", " or ")
            allowed = eval(expression, {"__builtins__": {}, "startsWith": str.startswith})
            family = name.split("-")[0]
            expected = name == "release-metadata" or ref.startswith(f"refs/tags/{family}-")
            assert bool(allowed) == expected, (name, ref)


def test_matrix_shapes_and_quality_gates_remain_intact() -> None:
    ci = _jobs("python.yml")["build"]
    release = _jobs("release.yml")["python-test"]
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in ci
    assert "runs-on: ubuntu-latest" in release
    for job in (ci, release):
        assert "python-version: ${{ matrix.python-version }}" in job
        assert "uv sync --locked --all-extras" in job
        assert 'version: "0.11.28"' in job
        assert "continue-on-error" not in job
    assert "-m pytest --cov=vmx --cov-report=xml -v" in ci
    assert "files: langs/python/coverage.xml" in ci


def test_python_run_commands_assert_one_explicit_environment_context() -> None:
    for name in ("python.yml", "release.yml", "conformance.yml"):
        for line in _workflow(name).splitlines():
            if "uv " in line and " run " in line and " python " in line:
                assert line.count("check-python-interpreter.py") == 1, line
                assert "--venv " in line or "--tool-context" in line, line
