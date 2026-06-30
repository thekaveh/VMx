//
// MessageHubConformanceTests.swift — HUB-001..006 conformance.
//
// Claimed IDs: HUB-001, HUB-002, HUB-003, HUB-004, HUB-005, HUB-006.
// HUB-007 (throwing-subscriber isolation via the opt-in `subscribe(_:)` helper)
// is claimed in MessageHubTests.swift.
//
// The existing MessageHub (PassthroughSubject) already delivers synchronously,
// hot (no replay), in FIFO order, to all current subscribers, with cancel-in-
// sink safety — so HUB-001..005 are test-only assertions over existing behaviour.
// HUB-006 drives all four scenarios in the bundled message-ordering.json fixture.
//
// REFERENCE-TYPE RECORDERS: every observation log captured inside an @escaping
// Combine sink closure uses a reference-type Recorder (final class) to avoid
// value-capture semantics on var arrays.
//
import XCTest
import Combine
@testable import VMx

// MARK: - Helpers

/// Observation log. A reference type so @escaping sink closures share the same
/// mutable storage without value-copy semantics.
private final class Recorder {
    var entries: [String] = []
}

/// Holds an optional AnyObject for identity assertions.
private final class ObjectBox {
    var value: AnyObject?
}

/// Holds an optional AnyCancellable so a sink closure can cancel its own
/// subscription without needing to capture a var local (HUB-004 / HUB-006
/// unsubscribe-during-emit scenario).
private final class CancelBox {
    var cancellable: AnyCancellable?
}

// MARK: - Fixture model (HUB-006)

private struct OrderingScenario: Decodable {
    let id: String
    let producerSends: [String]?
    let producerSendsBeforeSubscribe: [String]?
    let producerSendsAfterSubscribe: [String]?
    let subscriberCount: Int?
    let expectedObserved: [String]?
    let expectedObservedPerSubscriber: [String]?
    let unsubscribeAfterFirst: Bool?

    enum CodingKeys: String, CodingKey {
        case id
        case producerSends = "producer_sends"
        case producerSendsBeforeSubscribe = "producer_sends_before_subscribe"
        case producerSendsAfterSubscribe = "producer_sends_after_subscribe"
        case subscriberCount = "subscriber_count"
        case expectedObserved = "expected_observed"
        case expectedObservedPerSubscriber = "expected_observed_per_subscriber"
        case unsubscribeAfterFirst = "unsubscribe_after_first"
    }
}

private struct OrderingFixture: Decodable {
    let scenarios: [OrderingScenario]
}

// MARK: - Test class

final class MessageHubConformanceTests: XCTestCase {

    // Convenience: produce a PropertyChangedMessage tagged by senderName.
    private func makeMsg(_ name: String) -> PropertyChangedMessage {
        PropertyChangedMessage(sender: NSObject(), senderName: name, propertyName: "p")
    }

    // MARK: HUB-001

    /// HUB-001 — Send delivers to current subscribers synchronously before
    /// `send` returns; the received message carries the original sender object
    /// (reference identity preserved across the hub).
    func testSynchronousDeliveryAndIdentity() {
        let hub = MessageHub()
        let recorder = Recorder()
        let senderBox = ObjectBox()
        let sender = NSObject()
        var cancellables = Set<AnyCancellable>()

        hub.messages.sink { [recorder, senderBox] message in
            if let pc = message as? PropertyChangedMessage {
                recorder.entries.append(pc.senderName)
                senderBox.value = pc.senderObject
            }
        }.store(in: &cancellables)

        hub.send(PropertyChangedMessage(sender: sender, senderName: "A", propertyName: "p"))

        // Synchronous: both assertions hold immediately after send() returns.
        XCTAssertEqual(recorder.entries, ["A"], "HUB-001: delivered synchronously")
        XCTAssertTrue(senderBox.value === sender, "HUB-001: sender identity preserved")
    }

    // MARK: HUB-002

    /// HUB-002 — Late subscribers do not see prior messages (PassthroughSubject
    /// is hot; there is no replay buffer).
    func testLateSubscriberNoReplay() {
        let hub = MessageHub()
        let recorder = Recorder()
        var cancellables = Set<AnyCancellable>()

        hub.send(makeMsg("A"))  // sent before any subscriber is attached

        hub.messages.sink { [recorder] message in
            if let pc = message as? PropertyChangedMessage {
                recorder.entries.append(pc.senderName)
            }
        }.store(in: &cancellables)

        hub.send(makeMsg("B"))
        hub.send(makeMsg("C"))

        XCTAssertEqual(
            recorder.entries, ["B", "C"],
            "HUB-002: late subscriber sees only post-subscribe messages; no replay"
        )
    }

    // MARK: HUB-003

    /// HUB-003 — Single-producer FIFO order: messages are delivered in the
    /// exact order they were sent.
    func testSingleProducerFIFOOrder() {
        let hub = MessageHub()
        let recorder = Recorder()
        var cancellables = Set<AnyCancellable>()

        hub.messages.sink { [recorder] message in
            if let pc = message as? PropertyChangedMessage {
                recorder.entries.append(pc.senderName)
            }
        }.store(in: &cancellables)

        hub.send(makeMsg("A"))
        hub.send(makeMsg("B"))
        hub.send(makeMsg("C"))

        XCTAssertEqual(recorder.entries, ["A", "B", "C"], "HUB-003: FIFO order preserved")
    }

    // MARK: HUB-004

    /// HUB-004 — A subscriber that cancels its AnyCancellable inside its own
    /// handler observes only the first message; a subsequent send does not crash.
    func testCancelInHandlerIsSafe() {
        let hub = MessageHub()
        let recorder = Recorder()
        let box = CancelBox()

        box.cancellable = hub.messages.sink { [recorder, box] message in
            if let pc = message as? PropertyChangedMessage {
                recorder.entries.append(pc.senderName)
            }
            box.cancellable?.cancel()   // cancel self inside delivery
        }

        hub.send(makeMsg("A"))
        hub.send(makeMsg("B"))  // must not crash; subscription already cancelled

        XCTAssertEqual(
            recorder.entries, ["A"],
            "HUB-004: only first message observed; cancel-in-handler is safe and idempotent"
        )
    }

    // MARK: HUB-005

    /// HUB-005 — N≥2 subscribers each observe every post-subscribe message
    /// exactly once.
    func testMultipleSubscribersEachObserveEveryMessage() {
        let hub = MessageHub()
        let r1 = Recorder()
        let r2 = Recorder()
        let r3 = Recorder()
        var cancellables = Set<AnyCancellable>()

        hub.messages.sink { [r1] m in
            if let pc = m as? PropertyChangedMessage { r1.entries.append(pc.senderName) }
        }.store(in: &cancellables)
        hub.messages.sink { [r2] m in
            if let pc = m as? PropertyChangedMessage { r2.entries.append(pc.senderName) }
        }.store(in: &cancellables)
        hub.messages.sink { [r3] m in
            if let pc = m as? PropertyChangedMessage { r3.entries.append(pc.senderName) }
        }.store(in: &cancellables)

        hub.send(makeMsg("A"))
        hub.send(makeMsg("B"))

        XCTAssertEqual(r1.entries, ["A", "B"], "HUB-005: subscriber 1")
        XCTAssertEqual(r2.entries, ["A", "B"], "HUB-005: subscriber 2")
        XCTAssertEqual(r3.entries, ["A", "B"], "HUB-005: subscriber 3")
    }

    // MARK: HUB-006

    /// HUB-006 — Hub matches the bundled `message-ordering.json` fixture
    /// (all 4 heterogeneous scenarios: single-producer-fifo,
    /// late-subscribe-no-replay, multiple-subscribers-same-message,
    /// unsubscribe-during-emit).
    ///
    /// The fixture is loaded from `Bundle.module` (the VMx library bundle).
    /// No resources are declared on the test target so the library's bundle
    /// is not shadowed (see Package.swift comment).
    func testMessageOrderingFixture() throws {
        let url = try XCTUnwrap(
            Bundle.module.url(forResource: "message-ordering", withExtension: "json"),
            "message-ordering.json not found in Bundle.module"
        )
        let data = try Data(contentsOf: url)
        let fixture = try JSONDecoder().decode(OrderingFixture.self, from: data)

        XCTAssertFalse(fixture.scenarios.isEmpty, "fixture must contain at least one scenario")

        for scenario in fixture.scenarios {
            let hub = MessageHub()

            switch scenario.id {

            case "single-producer-fifo":
                let recorder = Recorder()
                var cancellables = Set<AnyCancellable>()
                hub.messages.sink { [recorder] m in
                    if let pc = m as? PropertyChangedMessage { recorder.entries.append(pc.senderName) }
                }.store(in: &cancellables)
                for id in scenario.producerSends ?? [] { hub.send(makeMsg(id)) }
                XCTAssertEqual(
                    recorder.entries, scenario.expectedObserved ?? [],
                    "HUB-006/\(scenario.id)"
                )

            case "late-subscribe-no-replay":
                // Send before subscribing — these must NOT appear in observed.
                for id in scenario.producerSendsBeforeSubscribe ?? [] { hub.send(makeMsg(id)) }
                let recorder = Recorder()
                var cancellables = Set<AnyCancellable>()
                hub.messages.sink { [recorder] m in
                    if let pc = m as? PropertyChangedMessage { recorder.entries.append(pc.senderName) }
                }.store(in: &cancellables)
                for id in scenario.producerSendsAfterSubscribe ?? [] { hub.send(makeMsg(id)) }
                XCTAssertEqual(
                    recorder.entries, scenario.expectedObserved ?? [],
                    "HUB-006/\(scenario.id)"
                )

            case "multiple-subscribers-same-message":
                let count = scenario.subscriberCount ?? 0
                let recorders = (0..<count).map { _ in Recorder() }
                var cancellables = Set<AnyCancellable>()
                for rec in recorders {
                    hub.messages.sink { [rec] m in
                        if let pc = m as? PropertyChangedMessage { rec.entries.append(pc.senderName) }
                    }.store(in: &cancellables)
                }
                for id in scenario.producerSends ?? [] { hub.send(makeMsg(id)) }
                for (i, rec) in recorders.enumerated() {
                    XCTAssertEqual(
                        rec.entries, scenario.expectedObservedPerSubscriber ?? [],
                        "HUB-006/\(scenario.id) subscriber \(i)"
                    )
                }

            case "unsubscribe-during-emit":
                let recorder = Recorder()
                let box = CancelBox()
                let shouldUnsub = scenario.unsubscribeAfterFirst ?? false
                box.cancellable = hub.messages.sink { [recorder, box] m in
                    if let pc = m as? PropertyChangedMessage { recorder.entries.append(pc.senderName) }
                    if shouldUnsub { box.cancellable?.cancel() }
                }
                for id in scenario.producerSends ?? [] { hub.send(makeMsg(id)) }
                XCTAssertEqual(
                    recorder.entries, scenario.expectedObserved ?? [],
                    "HUB-006/\(scenario.id)"
                )

            default:
                XCTFail("HUB-006: unrecognised scenario '\(scenario.id)' — fixture may have drifted")
            }
        }
    }
}
