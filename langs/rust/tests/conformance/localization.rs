use vmx::{Localizer, NullLocalizer};

struct PrefixLocalizer;

impl Localizer for PrefixLocalizer {
    fn localize(&self, key: &str) -> String {
        format!("loc:{key}")
    }
}

/// LOC-001 — ILocalizer.Localize returns a string
#[test]
fn localizer_returns_string() {
    let localizer = PrefixLocalizer;

    assert_eq!(localizer.localize("hello"), "loc:hello");
}

/// LOC-002 — NullLocalizer.Localize returns the key verbatim
#[test]
fn null_localizer_returns_key() {
    let localizer = NullLocalizer;

    assert_eq!(localizer.localize("hello"), "hello");
}

/// LOC-003 — Custom localizer can be substituted
#[test]
fn custom_localizer_can_be_substituted() {
    let localizer: Box<dyn Localizer> = Box::new(PrefixLocalizer);

    assert_eq!(localizer.localize("title"), "loc:title");
}
