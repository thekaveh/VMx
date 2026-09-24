# Keep-a-Changelog level-two headings delimit releases. Compare the version
# token literally so dots and prerelease/build suffixes are not regex syntax.
/^##([[:space:]]|$)/ {
    if (capture) exit
    capture = ($2 == "[" v "]")
    next
}
capture { print }
