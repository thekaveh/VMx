// HelloVMx — minimal console example for the VMx library.
//
// Demonstrates:
//   1. Building a ComponentVM<UserModel> with the fluent builder.
//   2. Subscribing to hub messages (PropertyChanged + ConstructionStatusChanged).
//   3. The full Destruct → Construct → Model-mutate → Destruct lifecycle.
//
// Console apps have no SynchronizationContext, so we use ImmediateScheduler
// for both fg and bg rather than RxDispatcher.CreateForCurrentContext().

using System.Reactive.Concurrency;
using VMx.Components;
using VMx.Messages;
using VMx.Services;

Demo.Run();

// ── Demo entry point ─────────────────────────────────────────────────────────

static class Demo
{
    public static void Run()
    {
        Console.WriteLine("=== HelloVMx ===");
        Console.WriteLine();

        // ── Infrastructure: shared hub + immediate dispatcher ─────────────────

        var hub        = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);

        // ── Subscribe to hub messages ─────────────────────────────────────────

        using var hubSub = hub.Messages.Subscribe(msg =>
        {
            if (msg is IConstructionStatusChangedMessage csm)
            {
                Console.WriteLine($"  [hub] {csm.SenderName}  status → {csm.Status}");
            }
            else if (msg is PropertyChangedMessage<ComponentVMBaseOfM<UserModel>> pcm)
            {
                Console.WriteLine($"  [hub] {pcm.SenderName}  property '{pcm.PropertyName}' changed");
            }
        });

        // ── Build the VM ──────────────────────────────────────────────────────

        Console.WriteLine("Building ComponentVM<UserModel> ...");

        var vm = ComponentVM<UserModel>.Builder()
            .Name("user-vm")
            .Hint("Displays the current user")
            .Services(hub, dispatcher)
            .Model(new UserModel("Alice", 30))
            .ModeledHinter(u => $"{u.Name} ({u.Age})")
            .OnConstruct(() => Console.WriteLine("  [lifecycle] OnConstruct callback fired"))
            .OnDestruct( () => Console.WriteLine("  [lifecycle] OnDestruct callback fired"))
            .Build();

        Console.WriteLine($"  vm.Name   = {vm.Name}");
        Console.WriteLine($"  vm.Status = {vm.Status}");
        Console.WriteLine($"  vm.Model  = {vm.Model}");
        Console.WriteLine();

        // ── Construct ─────────────────────────────────────────────────────────

        Console.WriteLine("Calling Construct() ...");
        vm.Construct();
        Console.WriteLine($"  vm.Status        = {vm.Status}");
        Console.WriteLine($"  vm.IsConstructed = {vm.IsConstructed}");
        Console.WriteLine($"  vm.ModeledHint   = {vm.ModeledHint}");
        Console.WriteLine();

        // ── Mutate the model ──────────────────────────────────────────────────

        Console.WriteLine("Mutating Model → Bob, 25 ...");
        vm.Model = new UserModel("Bob", 25);
        Console.WriteLine($"  vm.Model       = {vm.Model}");
        Console.WriteLine($"  vm.ModeledHint = {vm.ModeledHint}");
        Console.WriteLine();

        Console.WriteLine("Mutating Model → Carol, 40 ...");
        vm.Model = new UserModel("Carol", 40);
        Console.WriteLine($"  vm.Model       = {vm.Model}");
        Console.WriteLine($"  vm.ModeledHint = {vm.ModeledHint}");
        Console.WriteLine();

        // ── No-op: setting the same model value ───────────────────────────────

        Console.WriteLine("Setting the SAME model value (equality-guard: no hub message) ...");
        vm.Model = new UserModel("Carol", 40);
        Console.WriteLine();

        // ── Destruct ──────────────────────────────────────────────────────────

        Console.WriteLine("Calling Destruct() ...");
        vm.Destruct();
        Console.WriteLine($"  vm.Status        = {vm.Status}");
        Console.WriteLine($"  vm.IsConstructed = {vm.IsConstructed}");
        Console.WriteLine();

        // ── Cleanup ───────────────────────────────────────────────────────────

        vm.Dispose();
        hub.Dispose();

        Console.WriteLine("=== Done ===");
    }
}

// ── Domain model ─────────────────────────────────────────────────────────────

/// <summary>Simple POCO representing a user. Used as the VM's model type.</summary>
public record UserModel(string Name, int Age);
