import Combine
import XCTest
@testable import VMx

private enum CleanupFailure: Error { case boom }

private final class OwnedProbeVM: ComponentVMBase {
    private let disposeHook: (() -> Void)?
    override var type: ViewModelType { .component }

    init(hub: MessageHubProtocol, disposeHook: (() -> Void)? = nil) {
        self.disposeHook = disposeHook
        super.init(
            name: "probe",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    func register(_ cleanup: @escaping () throws -> Void) {
        own(cleanup)
    }

    func register(_ cancellable: any Cancellable) {
        own(cancellable)
    }

    override func _onDispose() {
        disposeHook?()
    }
}

final class OwnedResourceConformanceTests: XCTestCase {
    /// DISP-007 — owned resources are cleaned in LIFO order.
    func testDisp007OwnedResourcesAreLifo() {
        var trace: [String] = []
        let vm = OwnedProbeVM(hub: MessageHub()) { trace.append("hook") }
        vm.register { trace.append("closure") }
        vm.register(AnyCancellable { trace.append("cancellable") })
        vm.register { trace.append("last") }

        vm.dispose()

        XCTAssertEqual(trace, ["hook", "last", "cancellable", "closure"])
    }

    /// DISP-008 — repeated VM disposal cleans each resource exactly once.
    func testDisp008RepeatedDisposeCleansOnce() {
        var calls = 0
        let vm = OwnedProbeVM(hub: MessageHub())
        vm.register { calls += 1 }
        vm.dispose()
        vm.dispose()
        XCTAssertEqual(calls, 1)
    }

    /// DISP-009 — cleanup failure is swallowed and later resources still run.
    func testDisp009CleanupFailureIsIsolated() {
        var trace: [String] = []
        let vm = OwnedProbeVM(hub: MessageHub())
        vm.register { trace.append("first") }
        vm.register { throw CleanupFailure.boom }
        vm.register { trace.append("last") }

        vm.dispose()

        XCTAssertEqual(trace, ["last", "first"])
    }

    /// DISP-010 — registration after disposal is cleaned immediately once.
    func testDisp010PostDisposeRegistrationCleansImmediately() {
        var calls = 0
        let vm = OwnedProbeVM(hub: MessageHub())
        vm.dispose()
        vm.register { calls += 1 }
        vm.dispose()
        XCTAssertEqual(calls, 1)
    }

    /// DISP-011 — disposal-lifetime resources survive reconstruct.
    func testDisp011OwnedResourceSurvivesReconstruct() throws {
        var calls = 0
        let vm = OwnedProbeVM(hub: MessageHub())
        vm.register { calls += 1 }
        try vm.construct()
        try vm.reconstruct()
        XCTAssertEqual(calls, 0)
        vm.dispose()
        XCTAssertEqual(calls, 1)
    }

    /// DISP-012 — injected hub is publicly visible and read-only.
    func testDisp012HubIsPubliclyVisible() {
        let hub = MessageHub()
        let vm = OwnedProbeVM(hub: hub)
        XCTAssertTrue(vm.hub === hub)
    }

    /// DISP-013 — VM disposal does not dispose the shared injected hub.
    func testDisp013VmDoesNotOwnHub() {
        let hub = MessageHub()
        let vm = OwnedProbeVM(hub: hub)
        var received = 0
        let cancellable = hub.messages.sink { _ in received += 1 }
        vm.dispose()
        let baseline = received

        hub.send(ConstructionStatusChangedMessage(
            sender: vm,
            senderName: vm.name,
            status: vm.status
        ))

        XCTAssertEqual(received, baseline + 1)
        cancellable.cancel()
    }
}
