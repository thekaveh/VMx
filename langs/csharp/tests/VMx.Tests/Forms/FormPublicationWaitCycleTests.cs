using System.Reactive.Linq;
using FluentAssertions;
using VMx.Forms;
using VMx.Internal;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Forms;

/// <summary>
/// A form publication scope and a hub drain share one wait-for graph (#1170,
/// spec/20 §5.5, ADR-0176). Thread Y drains hub <c>H</c>, and its subscriber
/// calls the form. Thread X publishes a form notification, and a sink on X
/// sends on <c>H</c>. Whichever wait records second closes the cycle and is
/// refused, so both threads finish and no call or message is lost.
/// </summary>
public class FormPublicationWaitCycleTests
{
    private sealed record Model(string Value);

    private sealed record Marker(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    /// <summary>The notification whose sink on X sends on <c>H</c>.</summary>
    public enum Row
    {
        /// <summary>X's <c>SetModel("bad")</c> delivers <c>ErrorsChanged</c>.</summary>
        ErrorsChanged,

        /// <summary>X approves a dirty form, and its <c>OnApproved</c> sink sends.</summary>
        OnApproved,

        /// <summary>The <c>OnApproved</c> sink calls <c>SetModel</c> on a form whose hub is <c>H</c>.</summary>
        OnApprovedSetsModel,

        /// <summary>The approval reset returns <c>"bad"</c>, and the settlement <c>ErrorsChanged</c> sink sends.</summary>
        Reset,

        /// <summary>The settlement <c>CanExecuteChanged</c> sink sends.</summary>
        Settlement,
    }

    /// <summary>Y's call from its <c>H</c> subscriber.</summary>
    public enum Call
    {
        /// <summary><c>SetModel("y")</c>.</summary>
        SetModel,

        /// <summary><c>DenyCommand.Execute()</c>.</summary>
        Deny,

        /// <summary><c>Dispose()</c>.</summary>
        Dispose,

        /// <summary><c>ApproveAsync()</c>.</summary>
        Approve,
    }

    public static TheoryData<Row, Call, bool> Rows()
    {
        var data = new TheoryData<Row, Call, bool>();
        (Row, Call)[] rows =
        [
            (Row.ErrorsChanged, Call.SetModel),
            (Row.ErrorsChanged, Call.Deny),
            (Row.ErrorsChanged, Call.Dispose),
            (Row.OnApproved, Call.SetModel),
            (Row.OnApproved, Call.Deny),
            (Row.OnApproved, Call.Dispose),
            (Row.OnApproved, Call.Approve),
            (Row.OnApprovedSetsModel, Call.SetModel),
            (Row.Reset, Call.SetModel),
            (Row.Settlement, Call.SetModel),
        ];
        foreach (var (row, call) in rows)
        {
            // xFirst: X's hub wait records its edge before Y calls the form,
            // so Y's form wait is refused. Otherwise Y's form wait records
            // first, and X's send is refused and enqueues for Y's drain.
            data.Add(row, call, true);
            data.Add(row, call, false);
        }
        return data;
    }

    [Theory]
    [MemberData(nameof(Rows))]
    public void Form_Publication_And_Hub_Drain_Do_Not_Deadlock(Row row, Call call, bool xFirst)
    {
        var hub = new MessageHub();
        var persisted = 0;
        var formBuilder = FormVM<Model>.Builder()
            .Initial(new Model("initial"))
            .Persister(_ =>
            {
                Interlocked.Increment(ref persisted);
                return Task.CompletedTask;
            })
            .Snapshotter(model => model)
            .Validator("Value", model => model.Value == "bad" ? "rejected" : null);
        if (row == Row.OnApprovedSetsModel) formBuilder = formBuilder.Hub(hub);
        if (row == Row.Reset) formBuilder = formBuilder.ResetOnApproved(_ => new Model("bad"));
        var form = formBuilder.Build();
        if (row != Row.ErrorsChanged) form.SetModel(new Model("dirty"));

        var xThread = 0;
        var yThread = 0;
        var armed = 0;
        var errorsCompleted = 0;
        var approvedCompleted = 0;
        var completedDuringSink = false;
        var yRecordedFirst = true;
        var xRecordedFirst = true;
        var xMarkers = 0;
        var formMessages = 0;
        Exception? xError = null;
        Exception? yError = null;
        using var yDraining = new ManualResetEventSlim();
        using var releaseY = new ManualResetEventSlim();
        using var yDone = new ManualResetEventSlim();

        // X's sink: hand the turn to Y, then send on H. For the Y-first order,
        // X sends only after Y's form wait is in the graph.
        void Sink()
        {
            if (Interlocked.Exchange(ref armed, 0) == 0) return;
            releaseY.Set();
            if (!xFirst)
            {
                yRecordedFirst = SpinWait.SpinUntil(
                    () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref yThread)),
                    HangGuard);
            }
            if (row == Row.OnApprovedSetsModel)
                form.SetModel(new Model("z"));
            else
                hub.Send(new Marker("x"));
            completedDuringSink = Volatile.Read(ref errorsCompleted) != 0 ||
                Volatile.Read(ref approvedCompleted) != 0;
        }

        using var errorsSubscription = form.ErrorsChanged.Subscribe(
            _ =>
            {
                if (row is Row.ErrorsChanged or Row.Reset) Sink();
            },
            () => Interlocked.Exchange(ref errorsCompleted, 1));
        using var approvedSubscription = form.OnApproved.Subscribe(
            _ =>
            {
                if (row is Row.OnApproved or Row.OnApprovedSetsModel) Sink();
            },
            () => Interlocked.Exchange(ref approvedCompleted, 1));
        // The settlement notification is the one that finds the form idle.
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (row == Row.Settlement && form.ApproveCommand.CanExecute(null)) Sink();
        };

        using var hubSubscription = hub.Messages.Subscribe(message =>
        {
            if (message is Marker { Tag: "x" })
            {
                Interlocked.Increment(ref xMarkers);
                return;
            }
            if (message is PropertyChangedMessage<FormVM<Model>>)
            {
                Interlocked.Increment(ref formMessages);
                return;
            }
            if (message is not Marker { Tag: "y" }) return;

            // Thread Y drains H here.
            yDraining.Set();
            releaseY.Wait(HangGuard).Should().BeTrue();
            if (xFirst)
            {
                xRecordedFirst = SpinWait.SpinUntil(
                    () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref xThread)),
                    HangGuard);
            }
            try
            {
                switch (call)
                {
                    case Call.SetModel:
                        form.SetModel(new Model("y"));
                        break;
                    case Call.Deny:
                        form.DenyCommand.Execute(null);
                        break;
                    case Call.Dispose:
                        form.Dispose();
                        break;
                    case Call.Approve:
                        form.ApproveAsync().Wait(HangGuard).Should().BeTrue();
                        break;
                }
            }
            catch (Exception error)
            {
                yError = error;
            }
            finally
            {
                yDone.Set();
            }
        });
        Interlocked.Exchange(ref formMessages, 0);

        var y = new Thread(() =>
        {
            Volatile.Write(ref yThread, Environment.CurrentManagedThreadId);
            hub.Send(new Marker("y"));
        })
        { IsBackground = true };
        y.Start();
        yDraining.Wait(HangGuard).Should().BeTrue();

        var x = new Thread(() =>
        {
            Volatile.Write(ref xThread, Environment.CurrentManagedThreadId);
            Volatile.Write(ref armed, 1);
            try
            {
                if (row == Row.ErrorsChanged)
                    form.SetModel(new Model("bad"));
                else
                    form.ApproveAsync().Wait(HangGuard).Should().BeTrue();
            }
            catch (Exception error)
            {
                xError = error;
            }
        })
        { IsBackground = true };
        x.Start();

        // On a regression both threads stay blocked. They are background
        // threads, so they end with the test process. Disposing H here would
        // wait for the stuck drainer and hang the run.
        var finished = x.Join(HangGuard) && y.Join(HangGuard);
        finished.Should().BeTrue("the form publication and the hub drain must not deadlock");
        hub.Dispose();
        xError.Should().BeNull();
        yError.Should().BeNull();
        yDone.IsSet.Should().BeTrue();
        (xFirst ? xRecordedFirst : yRecordedFirst).Should().BeTrue("the first wait is in the graph");
        completedDuringSink.Should().BeFalse("a refused Dispose leaves the teardown to the publisher");
        if (row == Row.OnApprovedSetsModel)
            Volatile.Read(ref formMessages).Should().Be(2, "X's and Y's updates each publish once");
        else
            Volatile.Read(ref xMarkers).Should().Be(1, "X's send reaches the subscriber exactly once");

        switch (call)
        {
            case Call.SetModel:
                form.Model.Should().Be(new Model("y"), "Y's update is applied, not lost");
                break;
            case Call.Deny:
                form.Model.Should().Be(form.Snapshot, "Y's deny is applied, not lost");
                break;
            case Call.Dispose:
                Volatile.Read(ref errorsCompleted).Should().Be(1);
                Volatile.Read(ref approvedCompleted).Should().Be(1);
                break;
            case Call.Approve:
                Volatile.Read(ref persisted).Should().Be(2, "Y's approval is admitted, not dropped");
                break;
        }
        if (call != Call.Dispose) form.Dispose();
    }

    // spec/20 §5.5: a refused update joins the publisher's queue and replays
    // after the publisher's last notification, also when that update fails.
    // The publisher's own failure wins and reaches its caller.
    [Fact]
    public void A_Refused_Update_Replays_When_The_Publishers_Update_Fails()
    {
        var hub = new MessageHub();
        // Not `using`: on a regression X holds the form's lock, and an
        // implicit Dispose would block past the hang guard.
        var form = FormVM<Model>.Builder()
            .Initial(new Model("initial"))
            .Persister(_ => Task.CompletedTask)
            .Snapshotter(model => model)
            .Validator("Value", model => model.Value == "bad" ? "rejected" : null)
            .Build();
        var sinkError = new InvalidOperationException("sink");
        var xThread = 0;
        var armed = 0;
        var yReturnedBeforeReplay = false;
        Exception? xError = null;
        Exception? yError = null;
        using var yDraining = new ManualResetEventSlim();
        using var releaseY = new ManualResetEventSlim();
        using var errorsSubscription = form.ErrorsChanged.Subscribe(_ =>
        {
            if (Interlocked.Exchange(ref armed, 0) == 0) return;
            releaseY.Set();
            hub.Send(new Marker("x"));
            throw sinkError;
        });
        using var hubSubscription = hub.Messages.OfType<Marker>().Subscribe(message =>
        {
            if (message.Tag != "y") return;
            yDraining.Set();
            releaseY.Wait(HangGuard).Should().BeTrue();
            SpinWait.SpinUntil(
                () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref xThread)),
                HangGuard).Should().BeTrue();
            try
            {
                form.SetModel(new Model("y"));
                // Refused: the call is queued on X and has not taken effect.
                yReturnedBeforeReplay = form.Model == new Model("bad");
            }
            catch (Exception error)
            {
                yError = error;
            }
        });

        var y = new Thread(() => hub.Send(new Marker("y"))) { IsBackground = true };
        y.Start();
        yDraining.Wait(HangGuard).Should().BeTrue();
        var x = new Thread(() =>
        {
            Volatile.Write(ref xThread, Environment.CurrentManagedThreadId);
            Volatile.Write(ref armed, 1);
            try { form.SetModel(new Model("bad")); }
            catch (Exception error) { xError = error; }
        })
        { IsBackground = true };
        x.Start();

        (x.Join(HangGuard) && y.Join(HangGuard)).Should().BeTrue("the threads must not deadlock");
        hub.Dispose();

        yError.Should().BeNull();
        yReturnedBeforeReplay.Should().BeTrue("a refused update returns before it takes effect");
        xError.Should().BeSameAs(sinkError, "the publisher's own failure wins");
        form.Model.Should().Be(new Model("y"), "the queued update still replays");
        form.Dispose();
    }

    // spec/20 §5.5: a call in its own thread's pre-publication window joins
    // that thread's queue, even when its wait for another thread's scope is
    // refused. X's update ErrorsChanged sink sends on H while Y drains H.
    // Y's approval is admitted and settles in a second scope. Its step 3
    // CanExecuteChanged observer calls SetModel("y2"). The call replays on Y
    // after Y's OnApproved, is refused again, and moves to X's queue.
    [Fact]
    public void An_Own_Window_Call_Joins_Its_Own_Queue_When_Its_Wait_Is_Refused()
    {
        var hub = new MessageHub();
        var validations = new System.Collections.Concurrent.ConcurrentQueue<string>();
        var xThread = 0;
        var yThread = 0;
        var xArmed = 0;
        var yArmed = 0;
        var approvedBeforeReplay = false;
        Exception? xError = null;
        Exception? yError = null;
        // Not `using`: on a regression an implicit Dispose could block.
        var form = FormVM<Model>.Builder()
            .Initial(new Model("bad"))
            .Persister(_ => Task.CompletedTask)
            .Snapshotter(model => model)
            .Validator("Value", model =>
            {
                if (model.Value == "y2")
                {
                    var thread = Environment.CurrentManagedThreadId;
                    validations.Enqueue(thread == Volatile.Read(ref xThread) ? "x"
                        : thread == Volatile.Read(ref yThread) ? "y" : "other");
                }
                return model.Value == "bad" ? "rejected" : null;
            })
            .Build();
        using var yDraining = new ManualResetEventSlim();
        using var releaseY = new ManualResetEventSlim();
        using var errorsSubscription = form.ErrorsChanged.Subscribe(_ =>
        {
            if (Environment.CurrentManagedThreadId != Volatile.Read(ref xThread)) return;
            if (Interlocked.Exchange(ref xArmed, 0) == 0) return;
            releaseY.Set();
            hub.Send(new Marker("x"));
        });
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId != Volatile.Read(ref yThread)) return;
            if (!form.ApproveCommand.CanExecute(null)) return;
            if (Interlocked.Exchange(ref yArmed, 0) == 0) return;
            form.SetModel(new Model("y2"));
        };
        using var approvedSubscription = form.OnApproved.Subscribe(_ =>
        {
            if (Environment.CurrentManagedThreadId != Volatile.Read(ref yThread)) return;
            approvedBeforeReplay = validations.ToArray().SequenceEqual(["y"]);
        });
        using var hubSubscription = hub.Messages.OfType<Marker>().Subscribe(message =>
        {
            if (message.Tag != "y") return;
            yDraining.Set();
            releaseY.Wait(HangGuard).Should().BeTrue();
            SpinWait.SpinUntil(
                () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref xThread)),
                HangGuard).Should().BeTrue();
            try
            {
                Volatile.Write(ref yArmed, 1);
                form.ApproveAsync().Wait(HangGuard).Should().BeTrue();
            }
            catch (Exception error)
            {
                yError = error;
            }
        });

        var y = new Thread(() =>
        {
            Volatile.Write(ref yThread, Environment.CurrentManagedThreadId);
            hub.Send(new Marker("y"));
        })
        { IsBackground = true };
        y.Start();
        yDraining.Wait(HangGuard).Should().BeTrue();
        var x = new Thread(() =>
        {
            Volatile.Write(ref xThread, Environment.CurrentManagedThreadId);
            Volatile.Write(ref xArmed, 1);
            try { form.SetModel(new Model("good")); }
            catch (Exception error) { xError = error; }
        })
        { IsBackground = true };
        x.Start();

        (x.Join(HangGuard) && y.Join(HangGuard)).Should().BeTrue("the threads must not deadlock");
        hub.Dispose();

        xError.Should().BeNull();
        yError.Should().BeNull();
        approvedBeforeReplay.Should().BeTrue("Y's queue holds the call until Y's OnApproved");
        validations.Should().Equal(["y", "y", "x"],
            "the call is prepared on Y, replays on Y, and then moves to X's queue");
        form.Model.Should().Be(new Model("y2"), "the queued update is applied, not lost");
        form.Dispose();
    }

    /// <summary>
    /// What a nested call meeting another thread's open scope observed
    /// (spec/20 §5.4, ADR-0180, #1472).
    /// </summary>
    private sealed class NestedRun
    {
        public required FormVM<Model> Form { get; init; }
        public int NestedCalls { get; set; }
        public int[] RequestsDuringNestedCall { get; set; } = [];
        public bool YRequestRefused { get; set; }
        public Model? ModelAfterNestedCall { get; set; }
        public bool XScopeOpenAfterNestedCall { get; set; }
        public List<bool> ApprovedCompletions { get; } = [];
    }

    // Thread Y holds the drain of hub H. Thread X's SetModel("bad") delivers
    // ErrorsChanged in its scope, and X's sink sends on H, so the send waits
    // for Y. Y's subscriber then calls SetModel("outer"). Its wait for X's
    // scope closes a cycle and is refused, so the call prepares at once
    // (spec/20 §5.5). Y's validator then makes the nested call, which never
    // waits for X's scope (spec/20 §5.4). The wait-for graph seam records
    // every wait request, accepted or refused.
    private static NestedRun RunNestedCall(bool dispose)
    {
        var hub = new MessageHub();
        var xThread = 0;
        var yThread = 0;
        var xArmed = 1;
        var nestedActive = 0;
        var requests = new List<(int Thread, bool Accepted, bool Nested)>();
        Exception? xError = null;
        Exception? yError = null;
        using var xSinkReturned = new ManualResetEventSlim();
        using var yDraining = new ManualResetEventSlim();
        using var releaseY = new ManualResetEventSlim();
        NestedRun? run = null;
        // Not `using`: on a regression an implicit Dispose could block.
        var form = FormVM<Model>.Builder()
            .Initial(new Model("initial"))
            .Persister(_ => Task.CompletedTask)
            .Snapshotter(model => model)
            .Validator("Value", model =>
            {
                if (model.Value == "outer" && Environment.CurrentManagedThreadId == Volatile.Read(ref yThread))
                {
                    var current = run!.Form;
                    run.NestedCalls++;
                    Volatile.Write(ref nestedActive, 1);
                    if (dispose)
                    {
                        current.Dispose();
                    }
                    else
                    {
                        current.SetModel(new Model("nested"));
                        run.ModelAfterNestedCall = current.Model;
                    }
                    Volatile.Write(ref nestedActive, 0);
                    run.XScopeOpenAfterNestedCall = !xSinkReturned.IsSet;
                }
                return model.Value == "bad" ? "rejected" : null;
            })
            .Build();
        run = new NestedRun { Form = form };
        void OnWaitDecided(int thread, bool accepted)
        {
            if (thread != Volatile.Read(ref yThread)) return;
            lock (requests) requests.Add((thread, accepted, Volatile.Read(ref nestedActive) == 1));
        }
        WaitForGraph.Shared.WaitDecidedForTesting += OnWaitDecided;
        try
        {
            using var approvedSubscription = form.OnApproved.Subscribe(
                _ => { },
                () => run.ApprovedCompletions.Add(xSinkReturned.IsSet));
            using var errorsSubscription = form.ErrorsChanged.Subscribe(_ =>
            {
                if (Environment.CurrentManagedThreadId != Volatile.Read(ref xThread)) return;
                if (Interlocked.Exchange(ref xArmed, 0) == 0) return;
                releaseY.Set();
                // Y drains H, so this send waits for Y.
                hub.Send(new Marker("x"));
                xSinkReturned.Set();
            });
            using var hubSubscription = hub.Messages.OfType<Marker>().Subscribe(message =>
            {
                if (message.Tag != "go") return;
                yDraining.Set();
                if (!releaseY.Wait(HangGuard)) return;
                // X's hub send waits for Y before Y calls the form.
                if (!SpinWait.SpinUntil(
                    () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref xThread)),
                    HangGuard)) return;
                form.SetModel(new Model("outer"));
            });

            var y = new Thread(() =>
            {
                Volatile.Write(ref yThread, Environment.CurrentManagedThreadId);
                try { hub.Send(new Marker("go")); }
                catch (Exception error) { yError = error; }
            })
            { IsBackground = true };
            y.Start();
            yDraining.Wait(HangGuard).Should().BeTrue();
            var x = new Thread(() =>
            {
                Volatile.Write(ref xThread, Environment.CurrentManagedThreadId);
                try { form.SetModel(new Model("bad")); }
                catch (Exception error) { xError = error; }
            })
            { IsBackground = true };
            x.Start();

            x.Join(HangGuard * 2).Should().BeTrue("thread X must not deadlock");
            y.Join(HangGuard * 2).Should().BeTrue("thread Y must not deadlock");
        }
        finally
        {
            WaitForGraph.Shared.WaitDecidedForTesting -= OnWaitDecided;
            releaseY.Set();
            hub.Dispose();
        }

        xError.Should().BeNull();
        yError.Should().BeNull();
        lock (requests)
        {
            run.YRequestRefused = requests.Any(request => !request.Accepted);
            run.RequestsDuringNestedCall = requests
                .Where(request => request.Nested)
                .Select(request => request.Thread)
                .ToArray();
        }
        run.YRequestRefused.Should().BeTrue("Y's outer wait for X's scope is refused");
        run.NestedCalls.Should().Be(1);
        run.XScopeOpenAfterNestedCall.Should().BeTrue("the nested call returns while X holds its scope");
        run.RequestsDuringNestedCall.Should().BeEmpty("a nested call makes no wait request");
        return run;
    }

    [Fact]
    public void A_Nested_SetModel_Never_Waits_For_Another_Threads_Scope()
    {
        var run = RunNestedCall(dispose: false);

        run.ModelAfterNestedCall.Should().NotBeNull();
        run.ModelAfterNestedCall.Should().NotBe(new Model("nested"), "the nested call returns before it takes effect");
        run.Form.Model.Should().Be(new Model("nested"), "the nested call replays after X's scope ends");
        run.Form.IsValid.Should().BeTrue();
        run.Form.Dispose();
    }

    [Fact]
    public void A_Nested_Dispose_Never_Waits_For_Another_Threads_Scope()
    {
        var run = RunNestedCall(dispose: true);

        run.ApprovedCompletions.Should().Equal(
            [true], "OnApproved completes once, after X's sink returned inside X's scope");
    }
}
