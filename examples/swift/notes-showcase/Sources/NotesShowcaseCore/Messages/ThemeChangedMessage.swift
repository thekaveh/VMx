import Foundation
import VMx

/// Published on the hub by `ThemeVM` after every effective theme change.
///
/// See spec/proposals/2026-06-02-theme-vm-scenario.md §4 (event surface) and
/// §6 (conformance THEME-001/003/004).
///
/// `previous` is the model the VM held immediately before the transition;
/// `current` is the model just installed. The two are guaranteed to differ
/// by at least one field (the VM short-circuits a no-op transition before
/// publishing).
///
/// Mirrors C# `ThemeChangedMessage` and follows the `PropertyChangedMessage`
/// `senderObject`/`senderName` convention from the VMx Swift library.
public struct ThemeChangedMessage: Message {
    public let senderObject: AnyObject
    public let senderName: String
    /// The model installed prior to this transition.
    public let previous: ThemeModel
    /// The model now installed.
    public let current: ThemeModel

    public init(
        sender: AnyObject,
        senderName: String,
        previous: ThemeModel,
        current: ThemeModel
    ) {
        self.senderObject = sender
        self.senderName = senderName
        self.previous = previous
        self.current = current
    }

    /// Spec alias of `senderObject`.
    /// Matches the C# `Sender` / Python `sender` field convention.
    public var sender: AnyObject { senderObject }
}
