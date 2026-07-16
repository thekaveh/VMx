/// Internal transfer box for values whose access is already serialized by
/// VMx state gates. The box narrows an unchecked sendability assertion to the
/// capture of one internally-created task instead of marking a public VM type
/// `Sendable`.
final class UncheckedSendableBox<Value>: @unchecked Sendable {
    let value: Value

    init(_ value: Value) {
        self.value = value
    }
}

/// Weak counterpart used when an internal task must not extend its VM's
/// lifetime. Access to the referenced VM still follows that VM's state gate.
final class UncheckedSendableWeakBox<Value: AnyObject>: @unchecked Sendable {
    weak var value: Value?

    init(_ value: Value) {
        self.value = value
    }
}
