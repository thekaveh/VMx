//
// VMxConcurrentSubjectDemandTests.swift — subscriber demand on the subject
// behind every `FormVM` channel and the per-VM `propertyChanged`.
//
// `VMxConcurrentSubject` replaced `PassthroughSubject` on those channels
// (ADR-0174). It must keep `PassthroughSubject`'s demand contract: a value
// that arrives while a subscriber has no outstanding demand is dropped for
// that subscriber. Delivering it anyway breaks demand-limited subscribers;
// `for await x in form.errorsChanged.values` (AsyncPublisher requests
// `.max(1)`) traps with "Received an output without requesting demand".
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Bound for every wait in these tests.
private let demandTimeout: TimeInterval = 10

/// Records values; requests `initial` on subscription and returns `more`
/// from each `receive(_:)`.
private final class DemandSubscriber<Input>: Subscriber {
    typealias Failure = Never

    private let initial: Subscribers.Demand
    private let more: Subscribers.Demand
    private(set) var received: [Input] = []
    private(set) var subscription: Subscription?

    init(initial: Subscribers.Demand, more: Subscribers.Demand = .none) {
        self.initial = initial
        self.more = more
    }

    func receive(subscription: Subscription) {
        self.subscription = subscription
        subscription.request(initial)
    }

    func receive(_ input: Input) -> Subscribers.Demand {
        received.append(input)
        return more
    }

    func receive(completion: Subscribers.Completion<Never>) {}
}

final class VMxConcurrentSubjectDemandTests: XCTestCase {
    func testValuesBeyondRequestedDemandAreDropped() {
        let subject = VMxConcurrentSubject<Int, Never>()
        let subscriber = DemandSubscriber<Int>(initial: .max(1))
        subject.receive(subscriber: subscriber)

        subject.send(1)
        subject.send(2)
        subject.send(3)
        XCTAssertEqual(subscriber.received, [1], "values sent with no demand are dropped")

        subscriber.subscription?.request(.max(1))
        subject.send(4)
        subject.send(5)
        XCTAssertEqual(subscriber.received, [1, 4])
        subscriber.subscription?.cancel()
    }

    func testDemandReturnedFromReceiveIsAdded() {
        let subject = VMxConcurrentSubject<Int, Never>()
        let subscriber = DemandSubscriber<Int>(initial: .max(1), more: .max(1))
        subject.receive(subscriber: subscriber)

        for value in 1...4 { subject.send(value) }
        XCTAssertEqual(subscriber.received, [1, 2, 3, 4])
        subscriber.subscription?.cancel()
    }

    func testUnlimitedDemandReceivesEveryValueAndOtherSubscribersAreIndependent() {
        let subject = VMxConcurrentSubject<Int, Never>()
        let limited = DemandSubscriber<Int>(initial: .max(1))
        let unlimited = DemandSubscriber<Int>(initial: .unlimited)
        subject.receive(subscriber: limited)
        subject.receive(subscriber: unlimited)

        for value in 1...3 { subject.send(value) }
        XCTAssertEqual(limited.received, [1])
        XCTAssertEqual(unlimited.received, [1, 2, 3])
        limited.subscription?.cancel()
        unlimited.subscription?.cancel()
    }

    func testFormErrorsChangedHonorsDemand() {
        let form = FormVM<Int>(
            initial: 0,
            persister: { _ in },
            validators: ["value": { $0.isMultiple(of: 2) ? nil : "odd" }]
        )
        let subscriber = DemandSubscriber<[String: String]>(initial: .max(1))
        form.errorsChanged.receive(subscriber: subscriber)

        form.setModel(1)
        form.setModel(2)
        form.setModel(3)
        XCTAssertEqual(subscriber.received, [["value": "odd"]], "maps sent with no demand are dropped")
        subscriber.subscription?.cancel()
        form.dispose()
    }

    /// `AsyncPublisher` requests `.max(1)` at a time. A burst of error-map
    /// changes must not deliver a value it did not request.
    func testAsyncValuesConsumerSurvivesABurstOfErrorMapChanges() {
        let form = FormVM<Int>(
            initial: 0,
            persister: { _ in },
            validators: ["value": { $0.isMultiple(of: 2) ? nil : "odd" }]
        )
        let consumerDone = DispatchSemaphore(value: 0)
        let consumerStarted = DispatchSemaphore(value: 0)
        let publisher = UncheckedSendableBox(form.errorsChanged)
        Task.detached {
            consumerStarted.signal()
            for await _ in publisher.value.values {}
            consumerDone.signal()
        }
        XCTAssertEqual(consumerStarted.wait(timeout: .now() + demandTimeout), .success)
        for value in 1...2000 { form.setModel(value) }
        // Disposal completes the channel, which ends the loop.
        form.dispose()
        XCTAssertEqual(
            consumerDone.wait(timeout: .now() + demandTimeout), .success,
            "the async consumer never finished"
        )
    }
}
