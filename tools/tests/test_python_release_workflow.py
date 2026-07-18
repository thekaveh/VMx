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
        '.package-venv/bin/python langs/python/scripts/smoke_test.py "$tag_version"'
    )
    publish_index = publish_job.index("pypa/gh-action-pypi-publish@")

    assert build_index < install_index < smoke_index < publish_index


def test_conformance_job_uses_the_tracked_python_lockfile() -> None:
    workflow = _workflow("conformance.yml")

    assert "uv --project langs/python sync --locked --all-extras" in workflow


def test_python_ci_and_release_cover_314_and_audit_runtime_dependencies() -> None:
    ci = _workflow("python.yml")
    release = _workflow("release.yml")

    assert 'python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]' in ci
    assert 'python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]' in release
    assert "uv export --locked --no-dev --no-emit-project" in ci
    assert "uvx --from pip-audit==2.10.1 pip-audit" in ci
    assert "uvx --from pip-audit==2.10.1 pip-audit" in release
