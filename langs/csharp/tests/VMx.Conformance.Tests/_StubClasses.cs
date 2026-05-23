namespace VMx.Conformance.Tests;

// These stubs are filled in by later tasks (Task 6 for ComponentVMConformanceTests,
// Task 7 for CompositeVMConformanceTests). They exist now only so LIFE-NNN
// delegation compiles. The class names + method names below are the contract
// that the later tasks MUST honor.

internal sealed class ComponentVMConformanceTests
{
    public void CVM_001_Construct_Emits_Status_Messages() => throw new NotImplementedException("Task 6");
    public void LIFE_002_Destruct_Transitions() => throw new NotImplementedException("Task 6");
    public void LIFE_003_Reconstruct() => throw new NotImplementedException("Task 6");
    public void LIFE_004_Dispose_From_Any_State() => throw new NotImplementedException("Task 6");
    public void LIFE_007_IsConstructed_Invariant() => throw new NotImplementedException("Task 6");
    public void LIFE_008_Concurrent_Operation_Raises() => throw new NotImplementedException("Task 6");
    public void LIFE_009_Idempotent_Construct() => throw new NotImplementedException("Task 6");
    public void LIFE_010_Idempotent_Destruct() => throw new NotImplementedException("Task 6");
    public void LIFE_012_Dispose_From_Disposed_Silent() => throw new NotImplementedException("Task 6");
    public void PROP_001_Setter_Publishes() => throw new NotImplementedException("Task 6");
    public void PROP_002_Setter_Same_Value_Silent() => throw new NotImplementedException("Task 6");
    public void PROP_003_Sender_Identity() => throw new NotImplementedException("Task 6");
    public void PROP_004_PropertyName_SenderName() => throw new NotImplementedException("Task 6");
}

internal sealed class CompositeVMConformanceTests
{
    public void LIFE_013_Dispose_Cascade() => throw new NotImplementedException("Task 7");
}
