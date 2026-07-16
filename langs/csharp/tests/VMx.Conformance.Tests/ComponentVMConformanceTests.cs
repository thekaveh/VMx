using System.Reflection;
using System.ComponentModel;
using FluentAssertions;
using VMx.Components;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for ComponentVM, covering CVM-001..009 and
/// delegated LIFE-*/PROP-* IDs. See spec/12-conformance.md.
/// </summary>
public class ComponentVMConformanceTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildVm(
        string name = "vm1", string model = "initial")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(model)
            .Build();
        return (vm, hub, dispatcher);
    }

    private static List<ConstructionStatusChangedMessage> RecordStatusMessages(TestHub hub)
    {
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        return messages;
    }

    // ── CVM-001 / LIFE-001 — Construct emits status messages ────────────────

    /// <summary>
    /// CVM-001 / LIFE-001: construct() from Destructed emits Constructing then Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-001")]
    public void CVM_001_Construct_Emits_Status_Messages()
    {
        var (vm, hub, _) = BuildVm();
        var messages = RecordStatusMessages(hub);

        vm.Construct();

        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Constructing);
        messages[1].Status.Should().Be(ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();
    }

    // ── CVM-002 / PROP-001 — Modeled component fires PropertyChanged("Model") ─

    /// <summary>
    /// CVM-002 / PROP-001: setting Model to a different value publishes PropertyChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-002")]
    public void CVM_002_Modeled_Component_Fires_PropertyChanged_Model_On_Set()
    {
        var (vm, hub, _) = BuildVm(model: "m1");
        var propMessages = new List<IMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                propMessages.Add(m);
        });

        vm.Model = "m2";

        propMessages.Should().HaveCount(1);
    }

    // ── CVM-003 — ReadonlyComponentVM has no Model setter ────────────────────

    /// <summary>
    /// CVM-003: ReadonlyComponentVM&lt;M&gt; exposes no public Model setter.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-003")]
    public void CVM_003_ReadonlyComponentVM_Has_No_Model_Setter()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ReadonlyComponentVM<string>.Builder()
            .Name("ro").Services(hub, dispatcher).Model("fixed").Build();

        // Model value is accessible.
        vm.Model.Should().Be("fixed");

        // No public setter exists.
        var prop = typeof(ReadonlyComponentVM<string>)
            .GetProperty(nameof(ReadonlyComponentVM<string>.Model),
                BindingFlags.Public | BindingFlags.Instance);
        prop.Should().NotBeNull();
        prop!.CanWrite.Should().BeFalse("ReadonlyComponentVM must have no public Model setter");
        prop.GetSetMethod(nonPublic: true).Should().BeNull(
            "ReadonlyComponentVM must have no non-public Model setter either");
    }

    // ── CVM-004 — ModeledHint recomputes when Model changes ──────────────────

    /// <summary>
    /// CVM-004: changing Model causes ModeledHint to recompute and emits
    /// PropertyChangedMessage("ModeledHint").
    /// </summary>
    [Fact, Trait("Conformance", "CVM-004")]
    public void CVM_004_ModeledHint_Recomputes_When_Model_Changes()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<int>.Builder()
            .Name("v").Services(hub, dispatcher).Model(7)
            .ModeledHinter(n => $"hint:{n}")
            .Build();

        var hintMessages = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm &&
                pcm.PropertyName == nameof(vm.ModeledHint))
                hintMessages.Add(pcm.PropertyName);
        });

        vm.Model = 8;

        vm.ModeledHint.Should().Be("hint:8");
        hintMessages.Should().HaveCount(1);
    }

    // ── CVM-005 — Name and Hint are immutable ────────────────────────────────

    /// <summary>
    /// CVM-005: Name and Hint have no public setters.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-005")]
    public void CVM_005_Name_And_Hint_Are_Immutable()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("orig").Hint("h").Services(hub, dispatcher).Model("m").Build();

        vm.Name.Should().Be("orig");
        vm.Hint.Should().Be("h");

        var nameProp = typeof(ComponentVM<string>)
            .GetProperty(nameof(ComponentVM<string>.Name), BindingFlags.Public | BindingFlags.Instance);
        nameProp!.CanWrite.Should().BeFalse("Name must be read-only");

        var hintProp = typeof(ComponentVM<string>)
            .GetProperty(nameof(ComponentVM<string>.Hint), BindingFlags.Public | BindingFlags.Instance);
        hintProp!.CanWrite.Should().BeFalse("Hint must be read-only");
    }

    // ── CVM-006 — SelectCommand CanExecute reflects selection state ───────────

    /// <summary>
    /// CVM-006: SelectCommand.CanExecute reflects the selection state.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-006")]
    public void CVM_006_SelectCommand_CanExecute_Reflects_Selection_State()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m").Build();
        vm.Construct();

        // No parent: CanSelect is false.
        vm.SelectCommand.CanExecute(null).Should().BeFalse();

        // Set up a mock parent that can select.
        var parent = new MockCompositeVM();
        vm.Parent = parent;

        // Parent has no current: CanSelect is true.
        vm.SelectCommand.CanExecute(null).Should().BeTrue();

        // Select through the real pathway (catalog: "after vm.select()") —
        // Select() delegates to the parent's SelectChild.
        vm.Select();
        vm.IsCurrent = true; // the mock parent doesn't flip the child flag

        // Now SelectCommand.CanExecute reflects the new state after trigger fires.
        // The trigger fires asynchronously based on status changes, but for selection
        // the predicate is evaluated on-demand via CanExecute().
        vm.SelectCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "CVM-007")]
    public void CVM_007_Notification_Helper_Emits_Hub_Then_Local_Exactly_Once()
    {
        var hub = new TestHub();
        var vm = new NotificationProbeVM(hub);
        var trace = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Value" })
                trace.Add($"hub:{vm.Value}");
        });
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, args) =>
            trace.Add($"local:{args.PropertyName}:{vm.Value}");

        vm.Value = 7;

        trace.Should().Equal("hub:7", "local:Value:7");
    }

    [Fact, Trait("Conformance", "CVM-007")]
    public void CVM_007_Deferred_Delivery_And_Reentrant_Disposal_Complete_The_Pair()
    {
        var batchedHub = new MessageHub();
        var batchedVm = new NotificationProbeVM(batchedHub);
        var batchedTrace = new List<string>();
        batchedHub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Value" })
                batchedTrace.Add("hub");
        });
        ((INotifyPropertyChanged)batchedVm).PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(NotificationProbeVM.Value)) batchedTrace.Add("local");
        };

        batchedHub.Batch(() => batchedVm.Value = 7);

        batchedTrace.Should().Equal("local", "hub");

        var disposingHub = new TestHub();
        var disposingVm = new NotificationProbeVM(disposingHub);
        var disposingTrace = new List<string>();
        disposingHub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Value" })
            {
                disposingTrace.Add("hub");
                disposingVm.Dispose();
            }
        });
        ((INotifyPropertyChanged)disposingVm).PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(NotificationProbeVM.Value)) disposingTrace.Add("local");
        };

        disposingVm.Value = 7;

        disposingTrace.Should().Equal("hub", "local");
    }

    [Fact, Trait("Conformance", "CVM-008")]
    public void CVM_008_Equality_Guard_Suppresses_Both_Channels()
    {
        var hub = new TestHub();
        var vm = new NotificationProbeVM(hub);
        var hubCount = 0;
        var localCount = 0;
        hub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Value" })
                hubCount++;
        });
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(NotificationProbeVM.Value)) localCount++;
        };

        vm.Value = 7;
        vm.Value = 7;

        hubCount.Should().Be(1);
        localCount.Should().Be(1);
    }

    [Fact, Trait("Conformance", "CVM-009")]
    public void CVM_009_Notification_Helper_Is_Inert_After_Disposal()
    {
        var hub = new TestHub();
        var vm = new NotificationProbeVM(hub);
        var hubCount = 0;
        var localCount = 0;
        hub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Value" })
                hubCount++;
        });
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(NotificationProbeVM.Value)) localCount++;
        };
        vm.Dispose();

        vm.EmitValueNotification();

        hubCount.Should().Be(0);
        localCount.Should().Be(0);
    }

    [Fact, Trait("Conformance", "CVM-010")]
    public void CVM_010_Modeled_Components_Explicitly_Republish_The_Retained_Model()
    {
        var hub = new MessageHub();
        var model = new ReferenceModel(7);
        var hinterCalls = 0;
        var callbackCalls = 0;
        var vm = ComponentVM<ReferenceModel>.Builder()
            .Name("writable")
            .Services(hub, new TestDispatcher())
            .Model(model)
            .ModeledHinter(value =>
            {
                hinterCalls++;
                return $"hint:{value.Value}";
            })
            .OnModelChanged(_ => callbackCalls++)
            .Build();
        var hint = vm.ModeledHint;
        var hinterCallsAfterBuild = hinterCalls;
        var equalityCallsBeforeRepublish = model.EqualityCalls;
        var trace = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM>
                {
                    PropertyName: "Model",
                    SenderObject: var sender
                } && ReferenceEquals(sender, vm))
                trace.Add("hub:model");
        });
        vm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(vm.Model)) trace.Add("local:model");
        };

        vm.RepublishModel();

        vm.Model.Should().BeSameAs(model);
        vm.ModeledHint.Should().Be(hint);
        hinterCalls.Should().Be(hinterCallsAfterBuild);
        model.EqualityCalls.Should().Be(equalityCallsBeforeRepublish);
        callbackCalls.Should().Be(0);
        trace.Should().Equal("hub:model", "local:model");

        trace.Clear();
        vm.Model = model;
        trace.Should().BeEmpty("ordinary equal assignment remains silent");

        var replacement = new ReferenceModel(8);
        trace.Clear();
        vm.Model = replacement;

        vm.Model.Should().BeSameAs(replacement);
        vm.ModeledHint.Should().Be("hint:8");
        hinterCalls.Should().Be(hinterCallsAfterBuild + 1);
        callbackCalls.Should().Be(1);
        model.EqualityCalls.Should().BeGreaterThan(equalityCallsBeforeRepublish);
        trace.Should().Equal("hub:model", "local:model");

        var readonlyHub = new MessageHub();
        var readonlyVm = ReadonlyComponentVM<ReferenceModel>.Builder()
            .Name("readonly")
            .Services(readonlyHub, new TestDispatcher())
            .Model(model)
            .Build();
        var readonlyTrace = new List<string>();
        readonlyHub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Model" })
                readonlyTrace.Add("hub:model");
        });
        readonlyVm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(readonlyVm.Model)) readonlyTrace.Add("local:model");
        };

        readonlyVm.RepublishModel();

        readonlyVm.Model.Should().BeSameAs(model);
        readonlyTrace.Should().Equal("hub:model", "local:model");

        var wrappedHub = new MessageHub();
        var wrapped = ComponentVM<ReferenceModel>.Builder()
            .Name("wrapped")
            .Services(wrappedHub, new TestDispatcher())
            .Model(model)
            .Build();
        var forwarding = new TestForwardingComponentVM<ReferenceModel>(wrapped);
        object? forwardedSender = null;
        var forwardedLocalCount = 0;
        wrappedHub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Model" } change)
                forwardedSender = change.SenderObject;
        });
        forwarding.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(forwarding.Model)) forwardedLocalCount++;
        };

        forwarding.RepublishModel();

        forwardedSender.Should().BeSameAs(wrapped);
        forwardedLocalCount.Should().Be(1);

        var nullVm = ComponentVM<ReferenceModel>.Builder()
            .Name("null")
            .Model(model)
            .WithNullServices()
            .Build();
        var nullLocalCount = 0;
        nullVm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(nullVm.Model)) nullLocalCount++;
        };

        nullVm.RepublishModel();

        nullLocalCount.Should().Be(1);

        var disposedHub = new MessageHub();
        var disposedVm = ComponentVM<ReferenceModel>.Builder()
            .Name("disposed")
            .Services(disposedHub, new TestDispatcher())
            .Model(model)
            .Build();
        var disposedHubCount = 0;
        var disposedLocalCount = 0;
        disposedHub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> { PropertyName: "Model" })
                disposedHubCount++;
        });
        disposedVm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(disposedVm.Model)) disposedLocalCount++;
        };
        disposedVm.Dispose();

        disposedVm.RepublishModel();

        disposedHubCount.Should().Be(0);
        disposedLocalCount.Should().Be(0);

        var reentrantHub = new MessageHub();
        var reentrantVm = ComponentVM<ReferenceModel>.Builder()
            .Name("reentrant")
            .Services(reentrantHub, new TestDispatcher())
            .Model(model)
            .Build();
        var reentered = false;
        var reentrantTrace = new List<string>();
        reentrantHub.Messages.Subscribe(message =>
        {
            if (message is not IPropertyChangedMessage<IComponentVM> { PropertyName: "Model" }) return;
            reentrantTrace.Add("hub:model");
            if (reentered) return;
            reentered = true;
            reentrantVm.RepublishModel();
        });
        reentrantVm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(reentrantVm.Model)) reentrantTrace.Add("local:model");
        };

        reentrantVm.RepublishModel();

        reentrantTrace.Should().Equal("hub:model", "local:model", "hub:model", "local:model");
    }

    // ── PROP-001 — Setter publishes PropertyChangedMessage ───────────────────

    /// <summary>
    /// PROP-001: setting Model to a different value publishes exactly one PropertyChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-001")]
    public void PROP_001_Setter_Publishes()
    {
        var (vm, hub, _) = BuildVm(name: "n1", model: "m1");
        var messages = new List<IMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                messages.Add(m);
        });

        vm.Model = "m2";

        messages.Should().HaveCount(1);
    }

    // ── PROP-002 — Setter same value is silent ────────────────────────────────

    /// <summary>
    /// PROP-002: setting Model to the same value emits no messages.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-002")]
    public void PROP_002_Setter_Same_Value_Silent()
    {
        var (vm, hub, _) = BuildVm(model: "m1");
        var count = 0;
        hub.Messages.Subscribe(_ => count++);

        vm.Model = "m1"; // same value

        count.Should().Be(0);
    }

    // ── PROP-003 — Sender identity ────────────────────────────────────────────

    /// <summary>
    /// PROP-003: the Sender in the PropertyChangedMessage is the VM instance.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-003")]
    public void PROP_003_Sender_Identity()
    {
        var (vm, hub, _) = BuildVm(name: "vm1", model: "m1");
        IMessage? observed = null;
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                observed = m;
        });

        vm.Model = "m2";

        observed.Should().NotBeNull();
        observed!.SenderObject.Should().BeSameAs(vm);
    }

    // ── PROP-004 — PropertyName and SenderName ────────────────────────────────

    /// <summary>
    /// PROP-004: PropertyName is "Model" and SenderName is the VM's Name.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-004")]
    public void PROP_004_PropertyName_SenderName()
    {
        var (vm, hub, _) = BuildVm(name: "n1", model: "m1");
        IPropertyChangedMessage<IComponentVM>? observed = null;
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                observed = pcm;
        });

        vm.Model = "m2";

        observed.Should().NotBeNull();
        observed!.PropertyName.Should().Be("Model");
        observed.SenderName.Should().Be("n1");
    }

    // ── LIFE-002 — Destruct transitions ──────────────────────────────────────

    /// <summary>
    /// LIFE-002: destruct() from Constructed emits Destructing then Destructed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-002")]
    public void LIFE_002_Destruct_Transitions()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Destruct();

        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Destructing);
        messages[1].Status.Should().Be(ConstructionStatus.Destructed);
        vm.IsConstructed.Should().BeFalse();
    }

    // ── LIFE-003 — Reconstruct emits full sequence ────────────────────────────

    /// <summary>
    /// LIFE-003: reconstruct() emits Destructing, Destructed, Constructing, Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-003")]
    public void LIFE_003_Reconstruct()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Reconstruct();

        messages.Should().HaveCount(4);
        messages.Select(m => m.Status).Should().ContainInOrder(
            ConstructionStatus.Destructing,
            ConstructionStatus.Destructed,
            ConstructionStatus.Constructing,
            ConstructionStatus.Constructed);
    }

    // ── LIFE-004 — Dispose from any state ────────────────────────────────────

    /// <summary>
    /// LIFE-004: dispose() from any non-Disposed state transitions to Disposed
    /// and emits a ConstructionStatusChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-004")]
    public void LIFE_004_Dispose_From_Any_State()
    {
        // Destructed
        {
            var (vm, hub, _) = BuildVm();
            var messages = RecordStatusMessages(hub);
            vm.Dispose();
            vm.Status.Should().Be(ConstructionStatus.Disposed);
            messages.Should().Contain(m => m.Status == ConstructionStatus.Disposed);
        }

        // Constructed
        {
            var (vm, hub, _) = BuildVm();
            vm.Construct();
            var messages = RecordStatusMessages(hub);
            vm.Dispose();
            vm.Status.Should().Be(ConstructionStatus.Disposed);
            messages.Should().Contain(m => m.Status == ConstructionStatus.Disposed);
        }
    }

    // ── LIFE-007 — IsConstructed invariant ───────────────────────────────────

    /// <summary>
    /// LIFE-007: IsConstructed == (Status == Constructed) at all times.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-007")]
    public void LIFE_007_IsConstructed_Invariant()
    {
        var (vm, _, _) = BuildVm();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);

        vm.Construct();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();

        vm.Destruct();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeFalse();

        vm.Dispose();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
    }

    // ── LIFE-008 — Concurrent operation raises ────────────────────────────────

    /// <summary>
    /// LIFE-008: invoking construct() while a construct() is already in progress raises.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-008")]
    public void LIFE_008_Concurrent_Operation_Raises()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        StatusTransitionException? caught = null;
        ComponentVM<string>? vm = null;

        vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m")
            .OnConstruct(() =>
            {
                // Re-enter construct while already constructing.
                try { vm!.Construct(); }
                catch (StatusTransitionException ex) { caught = ex; }
            })
            .Build();

        vm.Construct();

        caught.Should().NotBeNull("second concurrent Construct must raise StatusTransitionException");
    }

    // ── LIFE-009 — Idempotent construct ──────────────────────────────────────

    /// <summary>
    /// LIFE-009: construct() from Constructed is a no-op (no messages emitted).
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-009")]
    public void LIFE_009_Idempotent_Construct()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Construct(); // already Constructed — idempotent

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── LIFE-010 — Idempotent destruct ───────────────────────────────────────

    /// <summary>
    /// LIFE-010: destruct() from Destructed is a no-op (no messages emitted).
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-010")]
    public void LIFE_010_Idempotent_Destruct()
    {
        var (vm, hub, _) = BuildVm();
        var messages = RecordStatusMessages(hub);

        vm.Destruct(); // already Destructed — idempotent

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── LIFE-012 — Dispose from Disposed emits no message ────────────────────

    /// <summary>
    /// LIFE-012: dispose() from Disposed is a no-op (no messages emitted).
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-012")]
    public void LIFE_012_Dispose_From_Disposed_Silent()
    {
        var (vm, hub, _) = BuildVm();
        vm.Dispose();
        var messages = RecordStatusMessages(hub);

        vm.Dispose(); // already Disposed — no-op

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── Mock composite for CVM-006 ────────────────────────────────────────────

    /// <summary>
    /// Minimal mock composite that supports selection for CVM-006 testing.
    /// Implements IParentCompositeVM so it can be assigned to ComponentVMBase.Parent.
    /// </summary>
    private sealed class MockCompositeVM : IParentCompositeVM
    {
        private IComponentVM? _current;

        public bool SupportsChildSelection => true;

        public IComponentVM? Owner => null;

        public IParentCompositeVM? OwnerParent => null;

        public IComponentVM? CurrentChild => _current;

        public void SetCurrent(IComponentVM vm) => _current = vm;

        public void SelectChild(IComponentVM vm) => _current = vm;
        public void DeselectChild(IComponentVM vm) { if (_current == vm) _current = null; }
        public bool ContainsChild(IComponentVM vm) => false;
        public ParentTransferToken DetachForTransfer(IComponentVM vm)
            => throw new InvalidOperationException("Selection-only test parent cannot transfer children.");
    }

    private sealed class NotificationProbeVM : ComponentVMBase
    {
        private int _value;

        public NotificationProbeVM(IMessageHub hub)
            : base("probe", "", hub, new TestDispatcher(), null, null)
        {
        }

        public override ViewModelType Type => ViewModelType.Component;

        public int Value
        {
            get => _value;
            set
            {
                if (_value == value) return;
                _value = value;
                NotifyPropertyChanged(nameof(Value));
            }
        }

        public void EmitValueNotification() => NotifyPropertyChanged(nameof(Value));
    }

    private sealed class ReferenceModel(int value) : IEquatable<ReferenceModel>
    {
        public int Value { get; } = value;

        public int EqualityCalls { get; private set; }

        public bool Equals(ReferenceModel? other)
        {
            EqualityCalls++;
            return other is not null && Value == other.Value;
        }

        public override bool Equals(object? obj) => Equals(obj as ReferenceModel);

        public override int GetHashCode() => Value;
    }

    private sealed class TestForwardingComponentVM<M>(IComponentVM<M> wrapped)
        : ForwardingComponentVM<M>(wrapped)
    {
    }
}
