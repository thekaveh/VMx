"""Unit tests for tools/check-swift-package-sync.py."""

from copy import deepcopy

import check_swift_package_sync as csps


def _dump(*, prefix: str = "") -> dict[str, object]:
    return {
        "name": "VMx",
        "platforms": [
            {"platformName": "ios", "version": "16.0", "options": []},
            {"platformName": "macos", "version": "13.0", "options": []},
        ],
        "products": [
            {
                "name": "VMx",
                "targets": ["VMx"],
                "type": {"library": ["automatic"]},
            }
        ],
        "targets": [
            {
                "name": "VMx",
                "path": f"{prefix}Sources/VMx",
                "resources": [
                    {"path": "Resources", "rule": {"process": {}}},
                ],
                "type": "regular",
            },
            {
                "name": "VMxTests",
                "path": f"{prefix}Tests/VMxTests",
                "resources": [],
                "type": "test",
            },
        ],
        "toolsVersion": {"_version": "5.9.0"},
    }


def test_normalize_dump_strips_only_root_target_path_prefix() -> None:
    payload = _dump(prefix="langs/swift/")
    payload["identityEvidence"] = "langs/swift/must-not-change"

    normalized = csps.normalize_dump(payload, root_prefix="langs/swift/")

    targets = normalized["targets"]
    assert isinstance(targets, list)
    assert [target["path"] for target in targets] == [
        "Sources/VMx",
        "Tests/VMxTests",
    ]
    assert normalized["identityEvidence"] == "langs/swift/must-not-change"


def test_manifest_diff_is_empty_for_structurally_equal_manifests() -> None:
    root = _dump(prefix="langs/swift/")
    root["packageKind"] = {"root": ["/repo"]}
    nested = _dump()
    nested["packageKind"] = {"root": ["/repo/langs/swift"]}

    assert csps.manifest_diff(root, nested) == ""


def test_manifest_diff_reports_platform_drift() -> None:
    nested = _dump()
    platforms = nested["platforms"]
    assert isinstance(platforms, list)
    platforms[1] = {"platformName": "macos", "version": "14.0", "options": []}

    diff = csps.manifest_diff(_dump(prefix="langs/swift/"), nested)

    assert "--- root/Package.swift" in diff
    assert "+++ langs/swift/Package.swift" in diff
    assert '"13.0"' in diff
    assert '"14.0"' in diff


def test_manifest_diff_reports_resource_rule_drift() -> None:
    nested = deepcopy(_dump())
    targets = nested["targets"]
    assert isinstance(targets, list)
    resources = targets[0]["resources"]
    assert isinstance(resources, list)
    resources.append(
        {"path": "message-ordering.json", "rule": {"copy": {}}},
    )

    diff = csps.manifest_diff(_dump(prefix="langs/swift/"), nested)

    assert "message-ordering.json" in diff
    assert '"copy"' in diff
