use std::fmt::Display;

use vmx::{Localizer, NullLocalizer};

struct PrefixLocalizer;

impl Localizer for PrefixLocalizer {
    fn localize(&self, key: &str) -> String {
        format!("loc:{key}")
    }
}

/// Replaces each `{N}` placeholder with the positional argument `N`.
struct FormattingLocalizer;

impl Localizer for FormattingLocalizer {
    fn localize(&self, key: &str) -> String {
        format!("loc:{key}")
    }

    fn localize_with_args(&self, key: &str, args: &[&dyn Display]) -> String {
        args.iter()
            .enumerate()
            .fold(self.localize(key), |text, (index, arg)| {
                text.replace(&format!("{{{index}}}"), &arg.to_string())
            })
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

#[test]
fn null_localizer_returns_key_from_args_form() {
    let localizer = NullLocalizer;

    assert_eq!(
        localizer.localize_with_args("hello {0}", &[&"world", &7]),
        "hello {0}"
    );
}

#[test]
fn default_args_form_delegates_to_key_form() {
    let localizer = PrefixLocalizer;

    assert_eq!(localizer.localize_with_args("title", &[&1]), "loc:title");
}

#[test]
fn custom_localizer_formats_positional_args() {
    let localizer: Box<dyn Localizer> = Box::new(FormattingLocalizer);

    assert_eq!(
        localizer.localize_with_args("{0} has {1} items", &[&"cart", &3]),
        "loc:cart has 3 items"
    );
}
