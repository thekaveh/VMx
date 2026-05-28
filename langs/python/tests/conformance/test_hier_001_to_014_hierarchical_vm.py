"""HIER-001..HIER-014 stubs — VMx absorption audit Stage 2 (HierarchicalVM).

Per spec/18-hierarchical-vm.md and ADR-0028. Substage 2A (spec foundation).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# HIER-001 — Recursive generic constraint compiles
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-001")
@pytest.mark.skip(reason="HIER-001 not yet implemented")
def test_hier_001_recursive_generic_constraint() -> None:
    raise NotImplementedError("HIER-001")


# ---------------------------------------------------------------------------
# HIER-002 — Parent is null for root, non-null for non-root
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-002")
@pytest.mark.skip(reason="HIER-002 not yet implemented")
def test_hier_002_parent_null_for_root_nonnull_for_child() -> None:
    raise NotImplementedError("HIER-002")


# ---------------------------------------------------------------------------
# HIER-003 — Depth derivation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-003")
@pytest.mark.skip(reason="HIER-003 not yet implemented")
def test_hier_003_depth_derivation() -> None:
    raise NotImplementedError("HIER-003")


# ---------------------------------------------------------------------------
# HIER-004 — Path materialization and cache identity
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-004")
@pytest.mark.skip(reason="HIER-004 not yet implemented")
def test_hier_004_path_materialization_and_cache() -> None:
    raise NotImplementedError("HIER-004")


# ---------------------------------------------------------------------------
# HIER-005 — IsLeaf and IsRoot derivation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-005")
@pytest.mark.skip(reason="HIER-005 not yet implemented")
def test_hier_005_isleaf_and_isroot_derivation() -> None:
    raise NotImplementedError("HIER-005")


# ---------------------------------------------------------------------------
# HIER-006 — IsFirst and IsLast position predicates
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-006")
@pytest.mark.skip(reason="HIER-006 not yet implemented")
def test_hier_006_isfirst_and_islast_position_predicates() -> None:
    raise NotImplementedError("HIER-006")


# ---------------------------------------------------------------------------
# HIER-007 — Default lazy child loading
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-007")
@pytest.mark.skip(reason="HIER-007 not yet implemented")
def test_hier_007_default_lazy_child_loading() -> None:
    raise NotImplementedError("HIER-007")


# ---------------------------------------------------------------------------
# HIER-008 — Eager child loading via builder option
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-008")
@pytest.mark.skip(reason="HIER-008 not yet implemented")
def test_hier_008_eager_child_loading_via_builder() -> None:
    raise NotImplementedError("HIER-008")


# ---------------------------------------------------------------------------
# HIER-009 — Depth-first construction order
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-009")
@pytest.mark.skip(reason="HIER-009 not yet implemented")
def test_hier_009_depth_first_construction_order() -> None:
    raise NotImplementedError("HIER-009")


# ---------------------------------------------------------------------------
# HIER-010 — PropertyChangedMessage on Parent change
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-010")
@pytest.mark.skip(reason="HIER-010 not yet implemented")
def test_hier_010_property_changed_message_on_parent_change() -> None:
    raise NotImplementedError("HIER-010")


# ---------------------------------------------------------------------------
# HIER-011 — TreeStructureChangedMessage on structural mutations
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-011")
@pytest.mark.skip(reason="HIER-011 not yet implemented")
def test_hier_011_tree_structure_changed_message() -> None:
    raise NotImplementedError("HIER-011")


# ---------------------------------------------------------------------------
# HIER-012 — walk_expanded honors lazy boundaries via ExpandableState
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-012")
@pytest.mark.skip(reason="HIER-012 not yet implemented")
def test_hier_012_walk_expanded_honors_expandable_state() -> None:
    raise NotImplementedError("HIER-012")


# ---------------------------------------------------------------------------
# HIER-013 — Composition with SearchableState filters materialized portion
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-013")
@pytest.mark.skip(reason="HIER-013 not yet implemented")
def test_hier_013_searchable_state_composition() -> None:
    raise NotImplementedError("HIER-013")


# ---------------------------------------------------------------------------
# HIER-014 — Composition with ModeledCrudCommands mutates the tree
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-014")
@pytest.mark.skip(reason="HIER-014 not yet implemented")
def test_hier_014_modeled_crud_commands_composition() -> None:
    raise NotImplementedError("HIER-014")
