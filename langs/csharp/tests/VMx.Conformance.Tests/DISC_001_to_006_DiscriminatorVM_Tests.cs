using FluentAssertions;
using VMx.State;
using Xunit;

namespace VMx.Conformance.Tests;

public class DISC_001_to_006_DiscriminatorVM_Tests
{
    [Fact, Trait("Conformance", "DISC-001")]
    public void DISC_001_Initial_Active_Key_And_IsActive()
    {
        using var sut = new DiscriminatorVM<string>("nav");
        sut.ActiveKey.Should().Be("nav");
        sut.IsActive("nav").Should().BeTrue();
        sut.IsActive("modal").Should().BeFalse();
    }

    [Fact, Trait("Conformance", "DISC-002")]
    public void DISC_002_SetActiveKey_Emits_Change()
    {
        using var sut = new DiscriminatorVM<string>("nav");
        var seen = new List<string>();
        using var sub = sut.ActiveChanged.Subscribe(seen.Add);
        sut.SetActiveKey("detail");
        sut.ActiveKey.Should().Be("detail");
        seen.Should().Equal("detail");
    }

    [Fact, Trait("Conformance", "DISC-003")]
    public void DISC_003_Setting_Same_Key_Is_Noop()
    {
        using var sut = new DiscriminatorVM<string>("nav");
        var seen = new List<string>();
        using var sub = sut.ActiveChanged.Subscribe(seen.Add);
        sut.SetActiveKey("nav");
        seen.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "DISC-004")]
    public void DISC_004_ModalOpen_Activates_Modal_Key()
    {
        using var sut = new DiscriminatorVM<string>("nav");
        sut.ModalOpen("modal");
        sut.ActiveKey.Should().Be("modal");
        sut.IsActive("modal").Should().BeTrue();
    }

    [Fact, Trait("Conformance", "DISC-005")]
    public void DISC_005_ModalClose_Restores_Prior_Key()
    {
        using var sut = new DiscriminatorVM<string>("nav");
        sut.SetActiveKey("detail");
        sut.ModalOpen("modal");
        sut.ModalClose();
        sut.ActiveKey.Should().Be("detail");
    }

    [Fact, Trait("Conformance", "DISC-006")]
    public void DISC_006_Nested_Modal_Precedence_Restores_In_Lifo_Order()
    {
        using var sut = new DiscriminatorVM<string>("nav");
        sut.ModalOpen("modal-a");
        sut.ModalOpen("modal-b");
        sut.ModalClose();
        sut.ActiveKey.Should().Be("modal-a");
        sut.ModalClose();
        sut.ActiveKey.Should().Be("nav");
    }
}
