import Foundation

/// Fixture-driven lifecycle legality table (LIFE-011). Decodes the bundled
/// `lifecycle-transitions.json` — the cross-flavor source of truth — replacing
/// the previously hand-rolled legality switch, so Swift cannot drift from the
/// canonical table the way C#/Python/TypeScript cannot.
struct LifecycleTransitionTable {
    struct Row: Decodable {
        let from: String
        let via: String
        let toFinal: String?
        let legal: Bool
        enum CodingKeys: String, CodingKey {
            case from, via, legal
            case toFinal = "to_final"
        }
    }
    private struct Fixture: Decodable { let transitions: [Row] }

    static let shared = LifecycleTransitionTable()

    private let rows: [Row]

    private init() {
        guard
            let url = Bundle.module.url(forResource: "lifecycle-transitions", withExtension: "json"),
            let data = try? Data(contentsOf: url),
            let fixture = try? JSONDecoder().decode(Fixture.self, from: data)
        else {
            preconditionFailure("VMx: lifecycle-transitions.json resource is missing or unreadable")
        }
        rows = fixture.transitions
    }

    private func row(from current: ConstructionStatus, via operation: String) -> Row? {
        rows.first { $0.from == current.name && $0.via == operation }
    }

    /// Whether `operation` is legal from `current`. Unknown (from, via) pairs are illegal.
    func isLegal(from current: ConstructionStatus, operation: String) -> Bool {
        row(from: current, via: operation)?.legal ?? false
    }
}
