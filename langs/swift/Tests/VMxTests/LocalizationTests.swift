//
// Localization hook conformance — LOC-001..003 (spec/17-localization.md).
// Ports langs/typescript/tests/conformance/localization.test.ts.
//
import XCTest
@testable import VMx

private class FakeLocalizer: Localizer {
    func localize(_ key: String, _ args: [Any]?) -> String {
        return key == "greeting" ? "hello" : key
    }
}

private class XLocalizer: Localizer {
    func localize(_ key: String, _ args: [Any]?) -> String {
        return "X:" + key
    }
}

final class LocalizationTests: XCTestCase {

    /// LOC-001 — Localizer.localize returns a string from a custom implementation.
    func testLocalizerReturnsLocalizedString() {
        let loc: any Localizer = FakeLocalizer()
        XCTAssertEqual(loc.localize("greeting", nil), "hello")
    }

    /// LOC-002 — NullLocalizer.localize returns the key verbatim, ignoring args.
    func testNullLocalizerReturnsKeyVerbatim() {
        let loc = NullLocalizer.INSTANCE
        XCTAssertEqual(loc.localize("any.key", nil), "any.key")
        XCTAssertEqual(loc.localize("any.key", ["x"]), "any.key")
    }

    /// LOC-003 — Custom localizer can substitute for the null variant under the Localizer type.
    func testCustomLocalizerSubstitutesNullVariant() {
        let loc: any Localizer = XLocalizer()
        XCTAssertEqual(loc.localize("k", nil), "X:k")
    }
}
