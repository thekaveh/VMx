//
// ThreadingTests.swift — threading / scheduler-marshaling conformance.
//
// Claimed IDs: THR-001, THR-002, THR-003, THR-004.
//
// Each test asserts the deferral pair the cross-flavor THR suite checks:
// the delivery (or terminal transition) is BUFFERED — zero before the
// scheduler advances, exactly one after. This proves the marshaling is real
// (a synchronous trampoline would pass even with the marshaling removed).
// Swift uses the hand-rolled `ManualScheduler` / `ManualDispatcher`
// (Sources/VMx/Services/ManualScheduler.swift) because Combine ships no
// virtual-time `TestScheduler` analogue — see spec/11-threading.md and the
// Task 9 ADR.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class ThreadingTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // A minimal hub envelope for the generic THR-004 case — mirrors the
    // bare `IMessage` used by the sibling TypeScript test.
    private struct TestMessage: Message {
        let senderObject: AnyObject
        let senderName: String
    }

    // ── THR-001 ──────────────────────────────────────────────────────────

    /// THR-001 — PropertyChanged observed on the foreground scheduler buffers
    /// until the scheduler advances.
    func testTHR001PropertyChangedBuffersUntilForegroundAdvances() throws {
        let hub = MessageHub()
        let foreground = ManualScheduler()

        let vm = try ComponentVMOf<String>.builder()
            .name("v")
            .model("m1")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()

        var received: [String] = []
        hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "model" }
            .receive(on: foreground)
            .sink { received.append($0.propertyName) }
            .store(in: &cancellables)

        vm.model = "m2"

        // The model setter publishes synchronously to the hub, but delivery is
        // marshaled onto the manual foreground scheduler — buffered until flush.
        XCTAssertEqual(received.count, 0,
                       "receive(on: foreground) must buffer delivery until the scheduler advances")

        foreground.flush()

        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received.first, "model")
    }

    // ── THR-002 ──────────────────────────────────────────────────────────

    /// THR-002 — Background construct returns synchronously in `.constructing`
    /// and completes the `.constructed` transition only after the background
    /// scheduler advances.
    func testTHR002BackgroundConstructDefersConstructedUntilBackgroundFlush() throws {
        let hub = MessageHub()
        let manual = ManualDispatcher()

        let vm = try ComponentVMOf<String>.builder()
            .name("v")
            .model("m")
            .services(hub: hub, dispatcher: manual)
            .background(true)
            .build()

        try vm.construct()

        // construct() returns immediately mid-transition: the synchronous
        // `.constructing` emission has happened, but the `_onConstruct` hook and
        // terminal `.constructed` transition are buffered on the background queue.
        XCTAssertEqual(vm.status, .constructing,
                       "background construct emits only Constructing synchronously")

        manual.flushBackground()

        XCTAssertEqual(vm.status, .constructed,
                       "after the background scheduler advances the transition completes")
    }

    // ── THR-003 ──────────────────────────────────────────────────────────

    /// THR-003 — CollectionChanged observed on the foreground scheduler buffers
    /// until the scheduler advances.
    func testTHR003CollectionChangedBuffersUntilForegroundAdvances() throws {
        let hub = MessageHub()
        let foreground = ManualScheduler()

        let child = try ComponentVM.builder()
            .name("c")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("comp")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [] }
            .build()
        try composite.construct()

        var received: [CollectionChangedAction] = []
        composite.collectionChanged
            .receive(on: foreground)
            .sink { received.append($0.action) }
            .store(in: &cancellables)

        composite.add(child)

        XCTAssertEqual(received.count, 0,
                       "receive(on: foreground) must buffer delivery until the scheduler advances")

        foreground.flush()

        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received.first, .add)
    }

    // ── THR-004 ──────────────────────────────────────────────────────────

    /// THR-004 — A subscriber observing the hub on a chosen scheduler via
    /// `receive(on:)` sees a sent message only after the scheduler advances.
    func testTHR004HubMessageBuffersUntilSchedulerAdvances() throws {
        let hub = MessageHub()
        let scheduler = ManualScheduler()
        let sender = NSObject()

        var received: [any Message] = []
        hub.messages
            .receive(on: scheduler)
            .sink { received.append($0) }
            .store(in: &cancellables)

        hub.send(TestMessage(senderObject: sender, senderName: "test"))

        XCTAssertEqual(received.count, 0,
                       "receive(on: scheduler) must buffer delivery until the scheduler advances")

        scheduler.flush()

        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received.first?.senderName, "test")
    }
}
