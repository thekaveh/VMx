import Combine
import XCTest
@testable import VMx

private final class SubscribeValueProbeVM: ComponentVMBase {
    private var storedValue: Int

    init(name: String, value: Int = 0, hub: any MessageHubProtocol) {
        storedValue = value
        super.init(
            name: name,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    var value: Int {
        get { storedValue }
        set {
            guard storedValue != newValue else { return }
            storedValue = newValue
            _notifyPropertyChanged("value")
        }
    }

    func republishValue() {
        _notifyPropertyChanged("value")
    }
}

private struct SubscribeValueSelection {
    let rawValue: Int
}

private struct SubscribeValuePair: Equatable {
    let current: Int
    let previous: Int
}

private final class SubscribeValueCancellationBox {
    var cancellable: AnyCancellable?
}

private enum SubscribeValueTestError: Error, Equatable {
    case initialSelector
    case immediateCallback
    case deliverySelector
    case deliveryEquality
    case deliveryCallback
}

final class SubscribeValueConformanceTests: XCTestCase {
    /// SUBV-001 — fixed source, default equality, and immediate current/current.
    func testSubscribeValueInitialAndDefaultEquality() throws {
        let hub = MessageHub()
        let source = SubscribeValueProbeVM(name: "source", hub: hub)
        let other = SubscribeValueProbeVM(name: "other", hub: hub)
        var selectorCalls = 0
        var seen: [SubscribeValuePair] = []

        let subscription = try subscribeValue(
            source,
            selector: { vm in
                selectorCalls += 1
                return vm.value
            },
            callback: { current, previous in
                seen.append(SubscribeValuePair(current: current, previous: previous))
                if seen.count == 1 {
                    source.value = 1
                }
            },
            fireImmediately: true
        )

        XCTAssertEqual(seen, [SubscribeValuePair(current: 0, previous: 0)])
        XCTAssertEqual(selectorCalls, 1, "the immediate callback runs before attachment")

        other.value = 1
        hub.send(ConstructionStatusChangedMessage(
            sender: source,
            senderName: source.name,
            status: .constructed
        ))
        XCTAssertEqual(selectorCalls, 1, "other senders and non-property messages are ignored")

        source.republishValue()
        source.republishValue()
        source.value = 2

        XCTAssertEqual(selectorCalls, 4)
        XCTAssertEqual(seen, [
            SubscribeValuePair(current: 0, previous: 0),
            SubscribeValuePair(current: 1, previous: 0),
            SubscribeValuePair(current: 2, previous: 1),
        ])
        subscription.cancel()
    }

    /// SUBV-002 — custom equality and at-most-once evaluation per matching message.
    func testSubscribeValueCustomEqualityEvaluatesOnce() throws {
        let hub = MessageHub()
        let source = SubscribeValueProbeVM(name: "source", value: 11, hub: hub)
        var selectorCalls = 0
        var comparisons: [(Int, Int)] = []
        var seen: [SubscribeValuePair] = []

        let subscription = try subscribeValue(
            source,
            selector: { vm in
                selectorCalls += 1
                return SubscribeValueSelection(rawValue: vm.value)
            },
            callback: { current, previous in
                seen.append(SubscribeValuePair(
                    current: current.rawValue,
                    previous: previous.rawValue
                ))
            },
            isEqual: { current, next in
                comparisons.append((current.rawValue, next.rawValue))
                return current.rawValue / 10 == next.rawValue / 10
            }
        )

        XCTAssertEqual(selectorCalls, 1)
        XCTAssertTrue(comparisons.isEmpty)

        source.value = 19
        source.republishValue()
        source.value = 21

        XCTAssertEqual(selectorCalls, 4)
        XCTAssertEqual(comparisons.map { "\($0.0):\($0.1)" }, ["11:19", "11:19", "11:21"])
        XCTAssertEqual(seen, [SubscribeValuePair(current: 21, previous: 11)])
        subscription.cancel()
    }

    /// SUBV-003 — re-entrant FIFO, batch suppression, and deterministic cancellation.
    func testSubscribeValueReentrancyBatchAndCancellation() throws {
        let hub = MessageHub()
        let source = SubscribeValueProbeVM(name: "source", hub: hub)
        var seen: [SubscribeValuePair] = []

        let subscription = try subscribeValue(
            source,
            selector: { $0.value },
            callback: { current, previous in
                seen.append(SubscribeValuePair(current: current, previous: previous))
                if current == 1 {
                    source.value = 2
                }
            }
        )

        source.value = 1
        XCTAssertEqual(seen, [
            SubscribeValuePair(current: 1, previous: 0),
            SubscribeValuePair(current: 2, previous: 1),
        ])

        try hub.batch {
            source.value = 3
            source.value = 4
        }
        XCTAssertEqual(seen, [
            SubscribeValuePair(current: 1, previous: 0),
            SubscribeValuePair(current: 2, previous: 1),
            SubscribeValuePair(current: 4, previous: 2),
        ])

        subscription.cancel()
        subscription.cancel()
        source.value = 5
        XCTAssertEqual(seen.count, 3)

        let callbackSource = SubscribeValueProbeVM(name: "callback-source", hub: hub)
        let cancellationBox = SubscribeValueCancellationBox()
        var callbackSeen: [SubscribeValuePair] = []
        var callbackSelectorCalls = 0
        cancellationBox.cancellable = try subscribeValue(
            callbackSource,
            selector: { vm in
                callbackSelectorCalls += 1
                return vm.value
            },
            callback: { current, previous in
                callbackSeen.append(SubscribeValuePair(current: current, previous: previous))
                cancellationBox.cancellable?.cancel()
                callbackSource.value = 2
            }
        )

        callbackSource.value = 1
        callbackSource.value = 3

        XCTAssertEqual(callbackSeen, [SubscribeValuePair(current: 1, previous: 0)])
        XCTAssertEqual(callbackSelectorCalls, 2,
                       "cancellation in the callback drops re-entrant and later deliveries")
    }

    /// SUBV-004 — setup propagation and isolated delivery failures retain the baseline.
    func testSubscribeValueFailureSemantics() throws {
        let hub = MessageHub()

        let initialSource = SubscribeValueProbeVM(name: "initial", hub: hub)
        var initialSelectorCalls = 0
        XCTAssertThrowsError(try subscribeValue(
            initialSource,
            selector: { _ throws -> Int in
                initialSelectorCalls += 1
                throw SubscribeValueTestError.initialSelector
            },
            callback: { _, _ in }
        )) { error in
            XCTAssertEqual(error as? SubscribeValueTestError, .initialSelector)
        }
        initialSource.republishValue()
        XCTAssertEqual(initialSelectorCalls, 1, "a failed initial selector attaches nothing")

        let immediateSource = SubscribeValueProbeVM(name: "immediate", hub: hub)
        var immediateSelectorCalls = 0
        var immediateCallbackCalls = 0
        XCTAssertThrowsError(try subscribeValue(
            immediateSource,
            selector: { vm in
                immediateSelectorCalls += 1
                return vm.value
            },
            callback: { _, _ in
                immediateCallbackCalls += 1
                throw SubscribeValueTestError.immediateCallback
            },
            fireImmediately: true
        )) { error in
            XCTAssertEqual(error as? SubscribeValueTestError, .immediateCallback)
        }
        immediateSource.republishValue()
        XCTAssertEqual(immediateSelectorCalls, 1)
        XCTAssertEqual(immediateCallbackCalls, 1,
                       "a failed immediate callback attaches nothing")

        let callbackSource = SubscribeValueProbeVM(name: "callback", hub: hub)
        var callbackSeen: [SubscribeValuePair] = []
        var healthyDeliveries = 0
        let healthySubscription = hub.subscribe { message in
            guard let property = message as? PropertyChangedMessage,
                  property.senderObject === callbackSource else { return }
            healthyDeliveries += 1
        }
        let callbackSubscription = try subscribeValue(
            callbackSource,
            selector: { $0.value },
            callback: { current, previous in
                callbackSeen.append(SubscribeValuePair(current: current, previous: previous))
                if current == 1 {
                    throw SubscribeValueTestError.deliveryCallback
                }
            }
        )

        callbackSource.value = 1
        callbackSource.value = 2

        XCTAssertEqual(callbackSeen, [
            SubscribeValuePair(current: 1, previous: 0),
            SubscribeValuePair(current: 2, previous: 1),
        ])
        XCTAssertEqual(healthyDeliveries, 2)

        let selectorSource = SubscribeValueProbeVM(name: "selector", hub: hub)
        var failNextSelector = false
        var selectorEqualityCalls = 0
        var selectorSeen: [SubscribeValuePair] = []
        let selectorSubscription = try subscribeValue(
            selectorSource,
            selector: { vm throws -> Int in
                if failNextSelector {
                    failNextSelector = false
                    throw SubscribeValueTestError.deliverySelector
                }
                return vm.value
            },
            callback: { current, previous in
                selectorSeen.append(SubscribeValuePair(current: current, previous: previous))
            },
            isEqual: { current, next in
                selectorEqualityCalls += 1
                return current == next
            }
        )
        failNextSelector = true
        selectorSource.value = 1
        selectorSource.value = 2
        XCTAssertEqual(selectorEqualityCalls, 1,
                       "equality is skipped when delivery-time selection fails")
        XCTAssertEqual(selectorSeen, [SubscribeValuePair(current: 2, previous: 0)])

        let equalitySource = SubscribeValueProbeVM(name: "equality", hub: hub)
        var equalityCalls = 0
        var equalitySeen: [SubscribeValuePair] = []
        let equalitySubscription = try subscribeValue(
            equalitySource,
            selector: { $0.value },
            callback: { current, previous in
                equalitySeen.append(SubscribeValuePair(current: current, previous: previous))
            },
            isEqual: { current, next in
                equalityCalls += 1
                if equalityCalls == 1 {
                    throw SubscribeValueTestError.deliveryEquality
                }
                return current == next
            }
        )
        equalitySource.value = 1
        equalitySource.value = 2
        XCTAssertEqual(equalityCalls, 2)
        XCTAssertEqual(equalitySeen, [SubscribeValuePair(current: 2, previous: 0)])

        healthySubscription.cancel()
        callbackSubscription.cancel()
        selectorSubscription.cancel()
        equalitySubscription.cancel()
    }
}
