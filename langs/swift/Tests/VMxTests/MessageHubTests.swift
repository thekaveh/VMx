//
// MessageHub tests — HUB-007 per-subscriber exception isolation.
//
// Claimed IDs: HUB-007 (the *catchable* half — a subscriber that throws a
// Swift `Error` via `subscribe(_:)` is isolated). A subscriber that *traps*
// rather than throws is an uncatchable process kill in Swift (parity with a
// segfault in the other flavors) and is a documented divergence (ADR-0037,
// langs/swift/README §5).
//
import XCTest
import Combine
@testable import VMx

final class MessageHubTests: XCTestCase {

    private func msg(_ name: String) -> PropertyChangedMessage {
        PropertyChangedMessage(sender: NSObject(), senderName: "h", propertyName: name)
    }

    /// HUB-007 / VMX-027 — a throwing subscriber registered via `subscribe(_:)`
    /// is isolated: its thrown error is swallowed inside its own sink, so it
    /// neither stops the hub nor blocks delivery to the other subscribers.
    func testThrowingSubscriberIsIsolated() {
        struct SubError: Error {}
        let hub = MessageHub()
        var firstReceived = 0
        var secondReceived = 0

        let c1 = hub.subscribe { _ in
            firstReceived += 1
            throw SubError()           // this subscriber always throws
        }
        let c2 = hub.subscribe { _ in
            secondReceived += 1        // ...the other must still receive
        }

        hub.send(msg("x"))
        hub.send(msg("y"))

        XCTAssertEqual(firstReceived, 2, "throwing subscriber keeps receiving")
        XCTAssertEqual(secondReceived, 2, "other subscriber is unaffected by the thrower")
        c1.cancel()
        c2.cancel()
    }

    /// `subscribe(_:)` delivers messages posted after subscription (HUB-002)
    /// to a non-throwing handler, and cancelling stops delivery.
    func testSubscribeDeliversThenCancelStops() {
        let hub = MessageHub()
        var seen: [String] = []
        let c = hub.subscribe { message in
            if let pc = message as? PropertyChangedMessage {
                seen.append(pc.propertyName)
            }
        }

        hub.send(msg("a"))
        c.cancel()
        hub.send(msg("b"))     // after cancel — not delivered

        XCTAssertEqual(seen, ["a"])
    }
}
