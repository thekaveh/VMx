using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for threading and scheduler dispatch: THR-001..004.
/// All tests use <see cref="TestDispatcher"/> / <see cref="TestScheduler"/> for
/// deterministic virtual-time control.  See spec/11-threading.md and
/// spec/12-conformance.md §Threading.
/// </summary>
public class ThreadingConformanceTests
{
    // ── THR-001 — PropertyChanged observed on foreground scheduler ───────────

    /// <summary>
    /// THR-001: a subscriber that uses ObserveOn(dispatcher.Foreground) must not
    /// receive PropertyChangedMessage until the foreground scheduler is advanced.
    /// After advancing by 1 tick the message is delivered.
    /// </summary>
    [Fact, Trait("Conformance", "THR-001")]
    public void THR_001_PropertyChanged_Observed_On_Foreground_Scheduler()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm1")
            .Services(hub, dispatcher)
            .Model("initial")
            .Build();

        var observed = new List<string>();
        hub.Messages
            .OfType<IPropertyChangedMessage<IComponentVM>>()
            .Where(m => m.PropertyName == "Model")
            .ObserveOn(dispatcher.Foreground)
            .Subscribe(m => observed.Add(m.PropertyName));

        // Act: change the model — message is sent synchronously to the hub,
        // but the ObserveOn(Foreground) buffers delivery.
        vm.Model = "new";

        // Before advancing the foreground scheduler, the handler must not yet fire.
        observed.Should().BeEmpty("ObserveOn(Foreground) must buffer delivery until scheduler advances");

        // Advance foreground by 1 tick to flush the queued delivery.
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        observed.Should().HaveCount(1);
        observed[0].Should().Be("Model");
    }

    // ── THR-002 — Background construct dispatches on background scheduler ────

    /// <summary>
    /// THR-002: with <c>Background(true)</c> the construction work is dispatched
    /// on <see cref="TestDispatcher.Background"/>.
    ///
    /// Construct() emits Constructing synchronously (so subscribers immediately see
    /// the transition starting), then schedules <c>OnConstruct()</c> + the final
    /// Constructed transition on the background scheduler before returning.
    /// Callers observe Constructing immediately after Construct() returns; the VM
    /// only reaches Constructed after the background scheduler is advanced.
    /// </summary>
    [Fact, Trait("Conformance", "THR-002")]
    public void THR_002_Background_Construct_Dispatches_On_Background_Scheduler()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        using var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("initial")
            .Background(true)
            .Build();

        vm.Construct();

        // Construct() returns immediately; the VM is mid-transition (Constructing),
        // NOT yet in the terminal Constructed state.
        vm.Status.Should().Be(ConstructionStatus.Constructing,
            "Background(true) means OnConstruct() and the final Constructed transition " +
            "are scheduled on the background scheduler — only Constructing is emitted synchronously");

        // Advance the background scheduler — OnConstruct() runs on the background
        // scheduler, then the terminal Constructed emission is marshalled onto the
        // foreground scheduler (VMX-025), so the VM is still mid-transition here.
        dispatcher.BackgroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Constructing,
            "the terminal Constructed emission is marshalled onto the foreground scheduler (VMX-025)");

        // Advance the foreground scheduler — the marshalled terminal transition runs.
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Constructed,
            "after both schedulers advance, the transition must complete");
    }

    // ── THR-003 — CollectionChanged observed on foreground scheduler ─────────

    /// <summary>
    /// THR-003: a subscriber to CollectionChanged that uses ObserveOn(dispatcher.Foreground)
    /// must not receive the Add notification until the foreground scheduler is advanced.
    /// After advancing by 1 tick the notification is delivered.
    /// </summary>
    [Fact, Trait("Conformance", "THR-003")]
    public void THR_003_CollectionChanged_Observed_On_Foreground_Scheduler()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();

        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .Build();

        // Wrap the CollectionChanged event as an IObservable and ObserveOn foreground.
        var observed = new List<NotifyCollectionChangedAction>();
        Observable
            .FromEventPattern<NotifyCollectionChangedEventHandler, NotifyCollectionChangedEventArgs>(
                h => composite.CollectionChanged += h,
                h => composite.CollectionChanged -= h)
            .ObserveOn(dispatcher.Foreground)
            .Subscribe(ep => observed.Add(ep.EventArgs.Action));

        // Act: add a child — the .NET event fires synchronously, but ObserveOn(Foreground)
        // defers delivery to the foreground scheduler.
        composite.Add(child);

        // Before advancing the foreground scheduler, no notification has been delivered.
        observed.Should().BeEmpty("ObserveOn(Foreground) must buffer delivery until scheduler advances");

        // Advance foreground by 1 tick to deliver the queued notification.
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        observed.Should().HaveCount(1);
        observed[0].Should().Be(NotifyCollectionChangedAction.Add);
    }

    // ── THR-004 — Subscriber observes on chosen scheduler via ObserveOn ──────

    /// <summary>
    /// THR-004: a subscriber using hub.Messages.ObserveOn(scheduler) must not
    /// receive any message until the scheduler is advanced.
    /// After advancing by 1 tick the message is delivered.
    /// </summary>
    [Fact, Trait("Conformance", "THR-004")]
    public void THR_004_Subscriber_Observes_On_Chosen_Scheduler_Via_ObserveOn()
    {
        using var hub = new MessageHub();
        var scheduler = new TestScheduler();

        var observed = new List<IMessage>();
        hub.Messages
            .ObserveOn(scheduler)
            .Subscribe(observed.Add);

        var message = new StubMessage("thr-004");

        // Act: send the message.
        hub.Send(message);

        // Before advancing the scheduler, handler must not yet be invoked.
        observed.Should().BeEmpty("ObserveOn(scheduler) must buffer delivery until scheduler advances");

        // Advance the scheduler by 1 tick to flush.
        scheduler.AdvanceBy(1);

        observed.Should().HaveCount(1);
        observed[0].Should().BeSameAs(message);
    }

    // ── Private stub message ─────────────────────────────────────────────────

    private sealed record StubMessage(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }
}
