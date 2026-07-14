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


def test_conformance_job_uses_the_tracked_python_lockfile() -> None:
    workflow = _workflow("conformance.yml")

    assert "uv --project langs/python sync --locked --all-extras" in workflow
