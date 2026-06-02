//
// Command — protocol for the VMx command contract.
//
// See spec/04-commands.md.
//
import Foundation
import Combine

/// Non-parameterized command. Mirrors `ICommand` in the C# / Python / TS
/// flavors.
public protocol Command: AnyObject {
    /// Whether `execute()` is currently allowed.
    func canExecute() -> Bool
    /// Run the command body. No-op when `canExecute()` is false.
    func execute()
    /// Publisher that fires (a `Void` value) whenever `canExecute()`
    /// *may* have changed.
    var canExecuteChanged: AnyPublisher<Void, Never> { get }
}
