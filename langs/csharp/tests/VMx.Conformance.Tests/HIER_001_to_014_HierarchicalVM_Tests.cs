using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs: HIER-001..HIER-014 — HierarchicalVM recursive tree VM.
/// See spec/18-hierarchical-vm.md and ADR-0028. Substage 2A (spec foundation).
/// </summary>
public class HIER_001_to_014_HierarchicalVM_Tests
{
    // ── HIER-001 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-001: Recursive generic constraint compiles per flavor.</summary>
    [Fact(Skip = "HIER-001 not yet implemented")]
    [Trait("Conformance", "HIER-001")]
    public void HIER_001_Recursive_Generic_Constraint_Compiles()
    {
        throw new System.NotImplementedException("HIER-001");
    }

    // ── HIER-002 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-002: Parent is null for root, non-null for non-root.</summary>
    [Fact(Skip = "HIER-002 not yet implemented")]
    [Trait("Conformance", "HIER-002")]
    public void HIER_002_Parent_Null_For_Root_NonNull_For_Child()
    {
        throw new System.NotImplementedException("HIER-002");
    }

    // ── HIER-003 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-003: Depth derivation — root is 0, child is parent + 1.</summary>
    [Fact(Skip = "HIER-003 not yet implemented")]
    [Trait("Conformance", "HIER-003")]
    public void HIER_003_Depth_Derivation()
    {
        throw new System.NotImplementedException("HIER-003");
    }

    // ── HIER-004 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-004: Path materialization — returns root-first snapshot; cached until reparent.</summary>
    [Fact(Skip = "HIER-004 not yet implemented")]
    [Trait("Conformance", "HIER-004")]
    public void HIER_004_Path_Materialization_And_Cache()
    {
        throw new System.NotImplementedException("HIER-004");
    }

    // ── HIER-005 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-005: IsLeaf and IsRoot derivation match Parent/Children state.</summary>
    [Fact(Skip = "HIER-005 not yet implemented")]
    [Trait("Conformance", "HIER-005")]
    public void HIER_005_IsLeaf_And_IsRoot_Derivation()
    {
        throw new System.NotImplementedException("HIER-005");
    }

    // ── HIER-006 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-006: IsFirst and IsLast position predicates.</summary>
    [Fact(Skip = "HIER-006 not yet implemented")]
    [Trait("Conformance", "HIER-006")]
    public void HIER_006_IsFirst_And_IsLast_Position_Predicates()
    {
        throw new System.NotImplementedException("HIER-006");
    }

    // ── HIER-007 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-007: Default lazy child loading — children factory not called until first access.</summary>
    [Fact(Skip = "HIER-007 not yet implemented")]
    [Trait("Conformance", "HIER-007")]
    public void HIER_007_Default_Lazy_Child_Loading()
    {
        throw new System.NotImplementedException("HIER-007");
    }

    // ── HIER-008 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-008: Eager child loading via WithEagerChildren() builder option.</summary>
    [Fact(Skip = "HIER-008 not yet implemented")]
    [Trait("Conformance", "HIER-008")]
    public void HIER_008_Eager_Child_Loading_Via_Builder()
    {
        throw new System.NotImplementedException("HIER-008");
    }

    // ── HIER-009 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-009: Depth-first construction order — deepest node reaches Constructed first.</summary>
    [Fact(Skip = "HIER-009 not yet implemented")]
    [Trait("Conformance", "HIER-009")]
    public void HIER_009_Depth_First_Construction_Order()
    {
        throw new System.NotImplementedException("HIER-009");
    }

    // ── HIER-010 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-010: PropertyChangedMessage on Parent change.</summary>
    [Fact(Skip = "HIER-010 not yet implemented")]
    [Trait("Conformance", "HIER-010")]
    public void HIER_010_PropertyChangedMessage_On_Parent_Change()
    {
        throw new System.NotImplementedException("HIER-010");
    }

    // ── HIER-011 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-011: TreeStructureChangedMessage on add / remove / reparent.</summary>
    [Fact(Skip = "HIER-011 not yet implemented")]
    [Trait("Conformance", "HIER-011")]
    public void HIER_011_TreeStructureChangedMessage_On_Structural_Mutations()
    {
        throw new System.NotImplementedException("HIER-011");
    }

    // ── HIER-012 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-012: walk_expanded honors lazy boundaries when ExpandableState gate is composed.</summary>
    [Fact(Skip = "HIER-012 not yet implemented")]
    [Trait("Conformance", "HIER-012")]
    public void HIER_012_WalkExpanded_Honors_ExpandableState_Lazy_Boundary()
    {
        throw new System.NotImplementedException("HIER-012");
    }

    // ── HIER-013 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-013: Composition with SearchableState filters materialized portion.</summary>
    [Fact(Skip = "HIER-013 not yet implemented")]
    [Trait("Conformance", "HIER-013")]
    public void HIER_013_SearchableState_Composition_Filters_Materialized_Portion()
    {
        throw new System.NotImplementedException("HIER-013");
    }

    // ── HIER-014 ──────────────────────────────────────────────────────────────

    /// <summary>HIER-014: Composition with ModeledCrudCommands mutates the tree.</summary>
    [Fact(Skip = "HIER-014 not yet implemented")]
    [Trait("Conformance", "HIER-014")]
    public void HIER_014_ModeledCrudCommands_Composition_Mutates_Tree()
    {
        throw new System.NotImplementedException("HIER-014");
    }
}
