using Xunit;

namespace VMx.Conformance.Tests;

public class PropertyChangeConformanceTests
{
    [Fact, Trait("Conformance", "PROP-001")]
    public void PROP_001_Setter_Different_Value_Publishes()
        => new ComponentVMConformanceTests().PROP_001_Setter_Publishes();

    [Fact, Trait("Conformance", "PROP-002")]
    public void PROP_002_Setter_Same_Value_Does_Not_Publish()
        => new ComponentVMConformanceTests().PROP_002_Setter_Same_Value_Silent();

    [Fact, Trait("Conformance", "PROP-003")]
    public void PROP_003_Sender_Identity_Equals_VM()
        => new ComponentVMConformanceTests().PROP_003_Sender_Identity();

    [Fact, Trait("Conformance", "PROP-004")]
    public void PROP_004_PropertyName_And_SenderName()
        => new ComponentVMConformanceTests().PROP_004_PropertyName_SenderName();
}
