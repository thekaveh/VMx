//
// ReleaseOutsideLockTests.swift — a user object released by a VMx primitive
// must be released after the primitive's non-recursive critical section, so a
// deinit that re-enters the owner neither deadlocks nor traps.
//
// Each scenario runs on a background thread and waits with a timeout, so a
// regression fails instead of hanging the suite.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class ReleaseOutsideLockTests: XCTestCase {
    private struct Plain: Message {
        var senderName: String { "plain" }
        var senderObject: AnyObject { NSNull() }
    }

    /// Sends on its hub from deinit.
    private final class Payload {
        let hub: MessageHub
        init(_ hub: MessageHub) { self.hub = hub }
        deinit { hub.send(Plain()) }
    }

    private struct Carrier: Message {
        let payload: Payload
        var senderName: String { "carrier" }
        var senderObject: AnyObject { payload }
    }

    private func runOffMain(
        _ description: String,
        _ body: @escaping @Sendable () throws -> Void
    ) {
        let done = expectation(description: description)
        let failure = LockedBox<Error?>(nil)
        Thread.detachNewThread {
            do { try body() } catch { failure.value = error }
            done.fulfill()
        }
        wait(for: [done], timeout: 5)
        if let error = failure.value { XCTFail("\(description) threw \(error)") }
    }

    /// HUB-010 — a re-entrantly sent message whose deinit sends on the hub is
    /// released outside the hub's gate after the drain delivers it.
    func testHubDrainReleasesMessagesOutsideGate() {
        runOffMain("nested drain") {
            let hub = MessageHub()
            let received = LockedBox(0)
            var once = true
            let subscription = hub.messages.sink { message in
                received.value += 1
                if once && message is Plain {
                    once = false
                    hub.send(Carrier(payload: Payload(hub)))
                }
            }
            hub.send(Plain())
            withExtendedLifetime(subscription) {}
            XCTAssertGreaterThanOrEqual(received.value, 2)
        }
    }

    /// HUB-012 — messages dropped by a dispose inside a transaction are
    /// released outside the hub's gate.
    func testHubDisposeReleasesDroppedMessagesOutsideGate() {
        runOffMain("dispose in transaction") {
            let hub = MessageHub()
            try hub.batch {
                hub.send(Carrier(payload: Payload(hub)))
                hub.dispose()
            }
        }
    }

    /// Cancelling a `propertyChanged` subscription releases its subscriber
    /// outside the subject's lock, so the subscriber's deinit can subscribe.
    func testSubjectCancelReleasesSubscriberOutsideLock() {
        runOffMain("subject cancel") {
            let vm = ComponentVMBase(name: "vm", hub: MessageHub(), dispatcher: DefaultDispatcher())
            let box = LockedBox<Subscription?>(nil)
            vm.propertyChanged.subscribe(ReentrantSubscriber(vm: vm, box: box))
            box.value?.cancel()
            box.value = nil
            vm.dispose()
        }
    }

    /// COL-065 — a token refresh that replaces the accumulator releases the
    /// prior items after the state queue, so an item's deinit can read it.
    func testTokenRefreshReleasesReplacedItemsOutsideStateQueue() {
        runOffMain("refresh items") {
            let calls = LockedBox(0)
            let owner = WeakBox<TokenPagedComposition<ReadingItem, Int>>()
            let comp = TokenPagedComposition<ReadingItem, Int>(fetchNext: { _ in
                calls.value += 1
                let count = calls.value == 1 ? 2 : 1
                return ((0..<count).map { _ in ReadingItem(owner) }, nil)
            })
            owner.value = comp
            try Self.await { try await comp.refreshCommand.executeAsync() }
            try Self.await { try await comp.refreshCommand.executeAsync() }
            XCTAssertEqual(comp.items.count, 1)
        }
    }

    /// COL-065 — a token refresh releases the replaced continuation token
    /// after the state queue, so the token's deinit can read `currentToken`.
    func testTokenRefreshReleasesReplacedTokenOutsideStateQueue() {
        runOffMain("refresh token") {
            let owner = WeakBox<TokenPagedComposition<Int, ReadingToken>>()
            let comp = TokenPagedComposition<Int, ReadingToken>(fetchNext: { _ in ([1], ReadingToken(owner)) })
            owner.value = comp
            try Self.await { try await comp.refreshCommand.executeAsync() }
            try Self.await { try await comp.refreshCommand.executeAsync() }
            XCTAssertNotNil(comp.currentToken)
        }
    }

    // MARK: - Helpers

    private static func await(_ operation: @escaping @Sendable () async throws -> Void) throws {
        let done = DispatchSemaphore(value: 0)
        let failure = LockedBox<Error?>(nil)
        Task {
            do { try await operation() } catch { failure.value = error }
            done.signal()
        }
        done.wait()
        if let error = failure.value { throw error }
    }

    private final class ReentrantSubscriber: Subscriber {
        typealias Input = String
        typealias Failure = Never
        let vm: ComponentVMBase
        let box: LockedBox<Subscription?>
        init(vm: ComponentVMBase, box: LockedBox<Subscription?>) {
            self.vm = vm
            self.box = box
        }
        func receive(subscription: Subscription) {
            subscription.request(.unlimited)
            box.value = subscription
        }
        func receive(_ input: String) -> Subscribers.Demand { .none }
        func receive(completion: Subscribers.Completion<Never>) {}
        deinit { vm.propertyChanged.sink { _ in }.cancel() }
    }

    /// Reads its composition's `items` from deinit.
    private final class ReadingItem {
        let owner: WeakBox<TokenPagedComposition<ReadingItem, Int>>
        init(_ owner: WeakBox<TokenPagedComposition<ReadingItem, Int>>) { self.owner = owner }
        deinit { _ = owner.value?.items }
    }

    /// Reads its composition's `currentToken` from deinit.
    private final class ReadingToken {
        let owner: WeakBox<TokenPagedComposition<Int, ReadingToken>>
        init(_ owner: WeakBox<TokenPagedComposition<Int, ReadingToken>>) { self.owner = owner }
        deinit { _ = owner.value?.currentToken }
    }
}

private final class WeakBox<Value: AnyObject>: @unchecked Sendable {
    private let lock = NSLock()
    private weak var stored: Value?
    var value: Value? {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}

private final class LockedBox<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Value
    init(_ value: Value) { stored = value }
    var value: Value {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}
