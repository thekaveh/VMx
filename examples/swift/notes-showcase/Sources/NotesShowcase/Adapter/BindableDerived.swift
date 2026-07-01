//
// BindableDerived — Combine → SwiftUI bridge for DerivedProperty<T>.
//
// `DerivedProperty.value` has a throwing getter (throws `.noValueYet` before
// the first source emission). With `CurrentValueSubject`-backed sources
// the value is populated synchronously by the time the DP is constructed
// (DPROP-001), so `try? dp.value` returns a non-nil seed in practice.
//
// `valueChanged` only emits distinct post-construction recomputes (DPROP-009),
// so this bridge always carries the latest derived value reactively.
//
import Combine
import SwiftUI
import VMx

/// Combine → SwiftUI bridge for a `DerivedProperty<T>`.
///
/// Seeds `value` from `try? dp.value` at construction, then updates on
/// each `dp.valueChanged` emission on the main run loop.
///
/// `value` is `T?` to accommodate the pre-emission window; in practice it
/// is populated immediately for `CurrentValueSubject`-backed properties.
final class BindableDerived<T>: ObservableObject {
    /// Latest derived value — `nil` only before the first source emission.
    @Published var value: T?
    private var cancellable: AnyCancellable?

    init(_ dp: DerivedProperty<T>) {
        value = try? dp.value
        cancellable = dp.valueChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] newValue in
                self?.value = newValue
            }
    }
}
