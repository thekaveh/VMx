"""Tests for the release-please Python release PR relabel and check (#1447)."""

import pytest
import release_please_labels as rpl


def _pull(number: int, version: str, *labels: str, merged: bool = True) -> dict[str, object]:
    return {
        "number": number,
        "title": f"chore(main): release python {version}",
        "merged_at": "2026-11-09T00:00:00Z" if merged else None,
        "labels": [{"name": label} for label in labels],
    }


def test_parse_keeps_merged_release_prs_and_their_versions() -> None:
    prs = rpl.parse_release_prs(
        [
            _pull(187, "3.2.0", rpl.PENDING, merged=False),
            _pull(298, "3.23.1", rpl.TAGGED),
            {"number": 300, "title": "chore: something else", "merged_at": "x", "labels": []},
        ]
    )
    assert prs == [
        rpl.ReleasePr(298, "3.23.1", frozenset({rpl.TAGGED})),
        rpl.ReleasePr(300, None, frozenset()),
    ]


@pytest.mark.parametrize(
    ("tags", "releases", "state"),
    [
        (set(), set(), "no-tag"),
        ({"python-v3.31.0"}, set(), "tag-without-release"),
    ],
    ids=["merged-before-the-tag-push", "tag-awaiting-publish-approval"],
)
def test_check_passes_while_the_release_is_in_progress(
    tags: set[str], releases: set[str], state: str, capsys: pytest.CaptureFixture[str]
) -> None:
    prs = rpl.parse_release_prs([_pull(400, "3.31.0", rpl.PENDING)])

    assert rpl.check(prs, tags.__contains__, releases.__contains__) == []
    assert f"#400 keeps 'autorelease: pending'; release in progress ({state})." in (
        capsys.readouterr().out
    )


def test_check_fails_and_names_a_pending_pr_whose_release_exists() -> None:
    prs = rpl.parse_release_prs(
        [_pull(400, "3.31.0", rpl.PENDING), _pull(298, "3.23.1", rpl.TAGGED)]
    )
    released = {"python-v3.31.0", "python-v3.23.1"}

    errors = rpl.check(prs, released.__contains__, released.__contains__)

    assert len(errors) == 1
    assert errors[0].startswith("#400 keeps 'autorelease: pending'")
    assert "python-v3.31.0" in errors[0]


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def remove_label(self, number: int, label: str) -> None:
        self.calls.append(("remove", number, label))

    def add_label(self, number: int, label: str) -> None:
        self.calls.append(("add", number, label))


def test_relabel_moves_only_the_matching_pr_to_tagged() -> None:
    prs = rpl.parse_release_prs(
        [_pull(400, "3.31.0", rpl.PENDING), _pull(298, "3.23.1", rpl.PENDING)]
    )
    recorder = _Recorder()

    assert rpl.relabel(prs, "3.31.0", recorder) == [400]
    assert recorder.calls == [("remove", 400, rpl.PENDING), ("add", 400, rpl.TAGGED)]


def test_relabel_is_idempotent_and_accepts_a_manual_tag_release() -> None:
    recorder = _Recorder()
    tagged = rpl.parse_release_prs([_pull(400, "3.31.0", rpl.TAGGED)])

    assert rpl.relabel(tagged, "3.31.0", recorder) == [400]
    assert rpl.relabel(tagged, "3.32.0", recorder) == []
    assert recorder.calls == []
