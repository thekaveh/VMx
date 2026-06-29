//
// DerivedProperty — a value derived from N source publishers via a pure
// transform, recomputed whenever any source emits.
//
// See spec/15-derived-properties.md and spec/ADRs/0011-derived-properties.md.
// Ports langs/typescript/src/properties/derivedProperty.ts to Combine.
//
// Behavior contract (mirrors the C# / Python / TypeScript flavors):
//   - `value` returns the latest computed value; throws `.noValueYet` until a
//     source has emitted (DPROP-001).
//   - A source emission recomputes `value` (DPROP-002/005).
//   - `valueChanged` emits ONLY post-construction recomputes — never the
//     initial computed value (DPROP-009) — and suppresses consecutive
//     duplicates via distinct-until-changed (DPROP-010, `TValue: Equatable`).
//   - Default-built (no validator) → `canSet` always false / read-only
//     (DPROP-006). With a validator + write-back, `setValue` runs the
//     write-back iff `canSet` is true, else throws `.cannotSet`
//     (DPROP-007/008).
//   - `dispose()` cancels all source subscriptions, completes `valueChanged`,
//     and halts further recomputes; `value` retains its last reading
//     (DPROP-011). Idempotent.
//
// Divergence: Combine offers `CombineLatest`/`CombineLatest3`/`CombineLatest4`
// but no native 5-ary operator. The typed five-source `from` overload nests a
// `CombineLatest4` with a final `combineLatest`; `fromSources` (any N) folds an
// array of erased publishers with a left-associative `combineLatest` so the
// 5-source spec minimum and beyond are supported without per-arity operators.
//
import Foundation
import Combine

/// Errors raised by `DerivedProperty`.
public enum DerivedPropertyError: Error {
    /// `value` was read before any source emitted.
    case noValueYet
    /// `setValue` was called but the validator rejected the value (or the
    /// property is read-only / default-built).
    case cannotSet
}

public final class DerivedProperty<TValue> {
    private var cachedValue: TValue?
    private var hasValue = false
    private let changesSubject = PassthroughSubject<TValue, Never>()
    private var cancellables: Set<AnyCancellable> = []
    private var disposed = false

    private let valueEquals: (TValue, TValue) -> Bool
    private let canSetValidator: ((TValue) -> Bool)?
    private let setAction: ((TValue) -> Void)?

    /// Designated initializer. Consumers build instances via the `from` /
    /// `fromSources` factories (which require `TValue: Equatable` and supply
    /// `==`); the explicit `valueEquals` closure keeps the class itself usable
    /// with any `TValue` while still honoring distinct-until-changed.
    ///
    /// - Parameters:
    ///   - derivedStream: the combined-and-transformed value stream. With
    ///     `CurrentValueSubject`-backed sources this emits its initial value
    ///     synchronously on subscription, so `value` is populated by the time
    ///     this initializer returns (DPROP-001).
    ///   - valueEquals: distinct-until-changed comparator (DPROP-010).
    ///   - canSet: optional validator gating `setValue`; nil ⇒ read-only.
    ///   - setAction: optional write-back invoked by `setValue` once `canSet`
    ///     passes.
    init(
        derivedStream: AnyPublisher<TValue, Never>,
        valueEquals: @escaping (TValue, TValue) -> Bool,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) {
        self.valueEquals = valueEquals
        self.canSetValidator = canSet
        self.setAction = setAction

        derivedStream
            .sink { [weak self] next in
                guard let self else { return }
                if !self.hasValue {
                    // Initial compute — seed the cache; do NOT emit (DPROP-009).
                    self.cachedValue = next
                    self.hasValue = true
                    return
                }
                // Distinct-until-changed: an equal recompute is a no-op — the
                // prior instance is kept, nothing is published (DPROP-010,
                // spec/15 §6).
                if let current = self.cachedValue, self.valueEquals(next, current) {
                    return
                }
                self.cachedValue = next
                self.changesSubject.send(next)
            }
            .store(in: &cancellables)
    }

    /// Latest computed value. Throws `.noValueYet` until a source has emitted.
    public var value: TValue {
        get throws {
            guard hasValue else { throw DerivedPropertyError.noValueYet }
            return cachedValue!
        }
    }

    /// Emits each post-construction recompute that differs from its predecessor
    /// (distinct). Never replays the initial value. Completes on `dispose()`.
    public var valueChanged: AnyPublisher<TValue, Never> {
        changesSubject.eraseToAnyPublisher()
    }

    /// Whether `value` may be written. False for default-built (read-only)
    /// properties; otherwise delegates to the configured validator.
    public func canSet(_ value: TValue) -> Bool {
        canSetValidator?(value) ?? false
    }

    /// Write-back entry point. Invokes the configured write-back action iff
    /// `canSet(value)` is true; otherwise throws `.cannotSet`.
    public func setValue(_ value: TValue) throws {
        guard canSet(value) else { throw DerivedPropertyError.cannotSet }
        setAction?(value)
    }

    /// Cancel all source subscriptions, complete `valueChanged`, and halt
    /// further recomputes. `value` retains its last reading. Idempotent.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        cancellables.removeAll()
        changesSubject.send(completion: .finished)
    }
}

// ── Factories ──────────────────────────────────────────────────────────────
//
// Distinct-until-changed requires `TValue: Equatable`, so the factories — the
// canonical construction surface — are constrained accordingly and pass `==`
// to the designated initializer.

public extension DerivedProperty where TValue: Equatable {

    /// One typed source.
    static func from<S1>(
        _ s1: AnyPublisher<S1, Never>,
        _ transform: @escaping (S1) -> TValue,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) -> DerivedProperty {
        DerivedProperty(
            derivedStream: s1.map(transform).eraseToAnyPublisher(),
            valueEquals: { $0 == $1 },
            canSet: canSet,
            setAction: setAction
        )
    }

    /// Two typed sources (`Publishers.CombineLatest`).
    static func from<S1, S2>(
        _ s1: AnyPublisher<S1, Never>,
        _ s2: AnyPublisher<S2, Never>,
        _ transform: @escaping (S1, S2) -> TValue,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) -> DerivedProperty {
        DerivedProperty(
            derivedStream: Publishers.CombineLatest(s1, s2)
                .map { transform($0.0, $0.1) }
                .eraseToAnyPublisher(),
            valueEquals: { $0 == $1 },
            canSet: canSet,
            setAction: setAction
        )
    }

    /// Three typed sources (`Publishers.CombineLatest3`).
    static func from<S1, S2, S3>(
        _ s1: AnyPublisher<S1, Never>,
        _ s2: AnyPublisher<S2, Never>,
        _ s3: AnyPublisher<S3, Never>,
        _ transform: @escaping (S1, S2, S3) -> TValue,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) -> DerivedProperty {
        DerivedProperty(
            derivedStream: Publishers.CombineLatest3(s1, s2, s3)
                .map { transform($0.0, $0.1, $0.2) }
                .eraseToAnyPublisher(),
            valueEquals: { $0 == $1 },
            canSet: canSet,
            setAction: setAction
        )
    }

    /// Four typed sources (`Publishers.CombineLatest4`).
    static func from<S1, S2, S3, S4>(
        _ s1: AnyPublisher<S1, Never>,
        _ s2: AnyPublisher<S2, Never>,
        _ s3: AnyPublisher<S3, Never>,
        _ s4: AnyPublisher<S4, Never>,
        _ transform: @escaping (S1, S2, S3, S4) -> TValue,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) -> DerivedProperty {
        DerivedProperty(
            derivedStream: Publishers.CombineLatest4(s1, s2, s3, s4)
                .map { transform($0.0, $0.1, $0.2, $0.3) }
                .eraseToAnyPublisher(),
            valueEquals: { $0 == $1 },
            canSet: canSet,
            setAction: setAction
        )
    }

    /// Five typed sources — the spec minimum upper bound. Combine has no native
    /// 5-ary `CombineLatest`, so this nests a `CombineLatest4` with a trailing
    /// `combineLatest` over the fifth source.
    static func from<S1, S2, S3, S4, S5>(
        _ s1: AnyPublisher<S1, Never>,
        _ s2: AnyPublisher<S2, Never>,
        _ s3: AnyPublisher<S3, Never>,
        _ s4: AnyPublisher<S4, Never>,
        _ s5: AnyPublisher<S5, Never>,
        _ transform: @escaping (S1, S2, S3, S4, S5) -> TValue,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) -> DerivedProperty {
        let stream = Publishers.CombineLatest4(s1, s2, s3, s4)
            .combineLatest(s5)
            .map { quad, v5 in transform(quad.0, quad.1, quad.2, quad.3, v5) }
            .eraseToAnyPublisher()
        return DerivedProperty(
            derivedStream: stream,
            valueEquals: { $0 == $1 },
            canSet: canSet,
            setAction: setAction
        )
    }

    /// N erased sources (any N ≥ 1). The transform receives the latest value of
    /// each source, in order, whenever any source emits. Sources are erased to
    /// `AnyPublisher<Any, Never>`, so heterogeneously-typed sources combine in
    /// one call (used by the fixture-driven DPROP-012 scenarios).
    static func fromSources(
        _ sources: [AnyPublisher<Any, Never>],
        _ transform: @escaping ([Any]) -> TValue,
        canSet: ((TValue) -> Bool)? = nil,
        setAction: ((TValue) -> Void)? = nil
    ) -> DerivedProperty {
        precondition(!sources.isEmpty, "DerivedProperty requires at least one source")
        let stream = combineLatestArray(sources)
            .map(transform)
            .eraseToAnyPublisher()
        return DerivedProperty(
            derivedStream: stream,
            valueEquals: { $0 == $1 },
            canSet: canSet,
            setAction: setAction
        )
    }
}

/// N-ary `combineLatest` over an array of erased publishers. Combine caps its
/// native operators at four sources, so this folds the array left-to-right:
/// the seed is the first source mapped to a one-element array, and each
/// remaining source is appended via a binary `combineLatest`. The result emits
/// the full ordered snapshot whenever any source emits, matching native
/// combine-latest semantics for any N ≥ 1.
private func combineLatestArray(
    _ sources: [AnyPublisher<Any, Never>]
) -> AnyPublisher<[Any], Never> {
    guard let first = sources.first else {
        // Unreachable: callers precondition on a non-empty array.
        return Empty(completeImmediately: true).eraseToAnyPublisher()
    }
    var combined: AnyPublisher<[Any], Never> = first
        .map { [$0] }
        .eraseToAnyPublisher()
    for source in sources.dropFirst() {
        combined = combined
            .combineLatest(source)
            .map { accumulated, next in accumulated + [next] }
            .eraseToAnyPublisher()
    }
    return combined
}
