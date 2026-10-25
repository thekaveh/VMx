# Keep-a-Changelog level-two headings delimit releases. Compare the version
# token literally so dots and prerelease/build suffixes are not regex syntax.
# A heading may carry a `(url)` link directly after the bracketed version, as
# release-please writes it. check_react_changelog_section in
# tools/check-version-consistency.py rejects the heading forms this script
# cannot read: indented headings, links with spaces, non-ASCII spacing.
/^##([[:space:]]|$)/ {
    if (capture) exit
    key = "[" v "]"
    capture = ($2 == key || (index($2, key "(") == 1 && substr($2, length($2)) == ")"))
    next
}
capture { print }
