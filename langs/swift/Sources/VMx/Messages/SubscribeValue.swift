import Combine

/// Observe selected state from one fixed component using caller-supplied equality.
public func subscribeValue<Source: ComponentVMBase, Value>(
    _ source: Source,
    selector: @escaping (Source) throws -> Value,
    callback: @escaping (Value, Value) throws -> Void,
    isEqual: @escaping (Value, Value) throws -> Bool,
    fireImmediately: Bool = false
) throws -> AnyCancellable {
    var current = try selector(source)

    if fireImmediately {
        try callback(current, current)
    }

    return source.hub.subscribe { message in
        guard let propertyChanged = message as? PropertyChangedMessage,
              propertyChanged.senderObject === source else {
            return
        }

        let next = try selector(source)
        if try isEqual(current, next) {
            return
        }

        let previous = current
        current = next
        try callback(next, previous)
    }
}

/// Observe selected `Equatable` state from one fixed component.
public func subscribeValue<Source: ComponentVMBase, Value: Equatable>(
    _ source: Source,
    selector: @escaping (Source) throws -> Value,
    callback: @escaping (Value, Value) throws -> Void,
    fireImmediately: Bool = false
) throws -> AnyCancellable {
    try subscribeValue(
        source,
        selector: selector,
        callback: callback,
        isEqual: { current, next in current == next },
        fireImmediately: fireImmediately
    )
}
