//
// DerivedProperty conformance tests — DPROP-001..012.
//
// Ports langs/typescript/tests/conformance/derivedProperties.test.ts. See
// spec/15-derived-properties.md and spec/ADRs/0011-derived-properties.md.
//
// Sources are `CurrentValueSubject`s (Combine's behavior-subject analog): they
// hold a current value, so `combineLatest` emits the initial computed value
// synchronously on subscription and every `.send(...)` recomputes on the same
// call stack — letting these tests read `dp.value` immediately after a mutation.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import Foundation
@testable import VMx

final class DerivedPropertyTests: XCTestCase {

    /// DPROP-001 — single-source derived value computes on construction.
    func testDprop001SingleSourceComputesOnConstruction() throws {
        let s1 = CurrentValueSubject<Int, Never>(10)
        let dp = DerivedProperty<Int>.from(s1.eraseToAnyPublisher()) { $0 * 2 }
        XCTAssertEqual(try dp.value, 20)
        dp.dispose()
    }

    /// DPROP-002 — source change triggers recompute.
    func testDprop002SourceChangeRecomputes() throws {
        let s1 = CurrentValueSubject<Int, Never>(10)
        let dp = DerivedProperty<Int>.from(s1.eraseToAnyPublisher()) { $0 * 2 }
        s1.send(5)
        XCTAssertEqual(try dp.value, 10)
        dp.dispose()
    }

    /// DPROP-003 — two-source derived value (`Publishers.CombineLatest`).
    func testDprop003TwoSourceDerivedValue() throws {
        let s1 = CurrentValueSubject<Int, Never>(3)
        let s2 = CurrentValueSubject<Int, Never>(4)
        let dp = DerivedProperty<Int>.from(
            s1.eraseToAnyPublisher(),
            s2.eraseToAnyPublisher()
        ) { $0 + $1 }
        XCTAssertEqual(try dp.value, 7)
        s2.send(6)
        XCTAssertEqual(try dp.value, 9)
        dp.dispose()
    }

    /// DPROP-004 — five-source derived value (spec minimum; nested combine).
    func testDprop004FiveSourceSpecMinimum() throws {
        let s1 = CurrentValueSubject<Int, Never>(1)
        let s2 = CurrentValueSubject<Int, Never>(2)
        let s3 = CurrentValueSubject<Int, Never>(3)
        let s4 = CurrentValueSubject<Int, Never>(4)
        let s5 = CurrentValueSubject<Int, Never>(5)
        let dp = DerivedProperty<Int>.from(
            s1.eraseToAnyPublisher(),
            s2.eraseToAnyPublisher(),
            s3.eraseToAnyPublisher(),
            s4.eraseToAnyPublisher(),
            s5.eraseToAnyPublisher()
        ) { $0 + $1 + $2 + $3 + $4 }
        XCTAssertEqual(try dp.value, 15)
        dp.dispose()
    }

    /// DPROP-005 — mutation of any source recomputes (five sources via the
    /// N-ary `fromSources` array fold).
    func testDprop005MutationOfAnySourceRecomputes() throws {
        let subjects = (1...5).map { CurrentValueSubject<Int, Never>($0) }
        let dp = DerivedProperty<Int>.fromSources(
            subjects.map { subject in subject.map { $0 as Any }.eraseToAnyPublisher() }
        ) { values in values.reduce(0) { $0 + ($1 as! Int) } }
        subjects[2].send(30)
        XCTAssertEqual(try dp.value, 1 + 2 + 30 + 4 + 5)
        dp.dispose()
    }

    /// DPROP-006 — default-built derived property is read-only (`canSet` false).
    func testDprop006DefaultBuiltIsReadOnly() {
        let s1 = CurrentValueSubject<Int, Never>(1)
        let dp = DerivedProperty<Int>.from(s1.eraseToAnyPublisher()) { $0 }
        for candidate in [0, 1, 42, -7] {
            XCTAssertFalse(dp.canSet(candidate),
                           "default-built property must reject all writes")
        }
        dp.dispose()
    }

    /// DPROP-007 — validator + write-back enables `setValue`.
    func testDprop007ValidatorWriteBackEnablesSetValue() throws {
        let s1 = CurrentValueSubject<Int, Never>(0)
        var recorder: [Int] = []
        let dp = DerivedProperty<Int>.from(
            s1.eraseToAnyPublisher(),
            { $0 },
            canSet: { $0 > 0 },
            setAction: { recorder.append($0) }
        )
        try dp.setValue(5)
        XCTAssertEqual(recorder, [5])
        XCTAssertThrowsError(try dp.setValue(-1)) { error in
            guard case DerivedPropertyError.cannotSet = error else {
                XCTFail("expected .cannotSet, got \(error)")
                return
            }
        }
        XCTAssertEqual(recorder, [5], "rejected write must not invoke the write-back")
        dp.dispose()
    }

    /// DPROP-008 — write-back action receives the value.
    func testDprop008WriteBackReceivesValue() throws {
        let s1 = CurrentValueSubject<Int, Never>(0)
        var recorder: [Int] = []
        let dp = DerivedProperty<Int>.from(
            s1.eraseToAnyPublisher(),
            { $0 },
            canSet: { _ in true },
            setAction: { recorder.append($0) }
        )
        try dp.setValue(7)
        XCTAssertEqual(recorder, [7])
        dp.dispose()
    }

    /// DPROP-009 — `valueChanged` emits on recompute (post-construction only).
    func testDprop009ValueChangedEmitsOnRecompute() {
        let s1 = CurrentValueSubject<Int, Never>(1)
        let dp = DerivedProperty<Int>.from(s1.eraseToAnyPublisher()) { $0 }
        var observed: [Int] = []
        let cancel = dp.valueChanged.sink { observed.append($0) }
        s1.send(2)
        s1.send(3)
        XCTAssertEqual(observed, [2, 3], "initial value (1) must not be replayed")
        cancel.cancel()
        dp.dispose()
    }

    /// DPROP-010 — `valueChanged` does not emit when the transform output is
    /// unchanged (distinct-until-changed).
    func testDprop010DistinctUntilChanged() {
        let s1 = CurrentValueSubject<Int, Never>(5)
        let s2 = CurrentValueSubject<Int, Never>(5)
        let dp = DerivedProperty<Int>.from(
            s1.eraseToAnyPublisher(),
            s2.eraseToAnyPublisher()
        ) { $0 + $1 }
        var observed: [Int] = []
        let cancel = dp.valueChanged.sink { observed.append($0) }
        s1.send(3) // 3 + 5 = 8  → emit
        s2.send(7) // 3 + 7 = 10 → emit
        XCTAssertEqual(observed, [8, 10])
        s1.send(3) // 3 + 7 still 10 → suppressed (distinct)
        XCTAssertEqual(observed, [8, 10])
        cancel.cancel()
        dp.dispose()
    }

    /// DPROP-011 — `dispose` ends subscriptions and `valueChanged` completes.
    func testDprop011DisposeEndsSubscriptionsAndCompletes() throws {
        let s1 = CurrentValueSubject<Int, Never>(1)
        let dp = DerivedProperty<Int>.from(s1.eraseToAnyPublisher()) { $0 }
        var observed: [Int] = []
        var completed = false
        let cancel = dp.valueChanged.sink(
            receiveCompletion: { _ in completed = true },
            receiveValue: { observed.append($0) }
        )
        s1.send(2)
        XCTAssertEqual(observed, [2])
        dp.dispose()
        XCTAssertTrue(completed, "valueChanged must complete on dispose")
        s1.send(3) // recompute halted — no further emission, value frozen
        XCTAssertEqual(try dp.value, 2, "value retains its last reading after dispose")
        XCTAssertEqual(observed, [2], "no emission after dispose")
        cancel.cancel()
    }

    // Regression guard (NOT a conformance ID): dispose is idempotent. Mirrors
    // the equivalent guard in the Python / TypeScript suites.
    func testDisposeIsIdempotent() {
        let s1 = CurrentValueSubject<Int, Never>(1)
        let dp = DerivedProperty<Int>.from(s1.eraseToAnyPublisher()) { $0 }
        dp.dispose()
        dp.dispose() // must not trap or re-complete
    }

    /// DPROP-012 — fixture-driven scenarios match `derived-properties.json`.
    func testDprop012FixtureScenariosMatch() throws {
        let fixture = try loadDerivedPropertiesFixture()
        XCTAssertFalse(fixture.scenarios.isEmpty, "fixture declares no scenarios")
        for scenario in fixture.scenarios {
            let subjects = scenario.sourcesInitial.map {
                CurrentValueSubject<Any, Never>($0.anyValue)
            }
            let transformName = scenario.transform
            let dp = DerivedProperty<FixtureValue>.fromSources(
                subjects.map { $0.eraseToAnyPublisher() }
            ) { values in applyFixtureTransform(transformName, values) }

            var actuals: [FixtureValue] = [try dp.value]
            for mutation in scenario.mutations {
                subjects[mutation.index].send(mutation.newValue.anyValue)
                actuals.append(try dp.value)
            }
            XCTAssertEqual(actuals, scenario.expectedValues,
                           "scenario \(scenario.name): value sequence mismatch")
            dp.dispose()
        }
    }

    // MARK: - fixture loading

    private func loadDerivedPropertiesFixture() throws -> DerivedPropertiesFixture {
        let url = try XCTUnwrap(
            Bundle.module.url(forResource: "derived-properties", withExtension: "json"),
            "derived-properties.json missing from the library bundle"
        )
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(DerivedPropertiesFixture.self, from: data)
    }
}

// ── Fixture model (derived-properties.json) ─────────────────────────────────
//
// `sources_initial`, mutation new-values, and `expected_values` are each a
// JSON Int OR String, so they decode into a small heterogeneous union. The
// `transform` field is a symbolic name ("sum" / "concat") resolved by the test.

/// A fixture cell — either an integer (sum scenarios) or a string (concat).
private enum FixtureValue: Decodable, Equatable {
    case int(Int)
    case string(String)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        // Probe Int before String: a JSON number never decodes as String, and a
        // JSON string never decodes as Int, so the order only matters for clarity.
        if let intValue = try? container.decode(Int.self) {
            self = .int(intValue)
        } else if let stringValue = try? container.decode(String.self) {
            self = .string(stringValue)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "fixture value must be an Int or a String"
            )
        }
    }

    /// The boxed underlying value, ready to feed an `AnyPublisher<Any, Never>`.
    var anyValue: Any {
        switch self {
        case .int(let value): return value
        case .string(let value): return value
        }
    }
}

/// A `[sourceIndex, newValue]` mutation tuple.
private struct FixtureMutation: Decodable {
    let index: Int
    let newValue: FixtureValue

    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        index = try container.decode(Int.self)            // always an Int
        newValue = try container.decode(FixtureValue.self) // Int or String
    }
}

private struct FixtureScenario: Decodable {
    let name: String
    let sourcesInitial: [FixtureValue]
    let transform: String
    let mutations: [FixtureMutation]
    let expectedValues: [FixtureValue]

    enum CodingKeys: String, CodingKey {
        case name
        case sourcesInitial = "sources_initial"
        case transform
        case mutations
        case expectedValues = "expected_values"
    }
}

private struct DerivedPropertiesFixture: Decodable {
    let scenarios: [FixtureScenario]
}

/// Resolve a symbolic transform name against the latest source values.
private func applyFixtureTransform(_ name: String, _ values: [Any]) -> FixtureValue {
    switch name {
    case "sum":
        let total = values.reduce(0) { partial, value in partial + ((value as? Int) ?? 0) }
        return .int(total)
    case "concat":
        let joined = values.map(stringifyFixtureValue).joined()
        return .string(joined)
    default:
        fatalError("unknown fixture transform: \(name)")
    }
}

private func stringifyFixtureValue(_ value: Any) -> String {
    if let intValue = value as? Int { return String(intValue) }
    if let stringValue = value as? String { return stringValue }
    return "\(value)"
}
