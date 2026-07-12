"""Package metadata for vmx."""

# release-please updates the value preceding the marker comment on the
# `__version__` line each time it cuts a release PR. `__min_spec_version__`
# is intentionally not auto-bumped — when a spec major bumps, the user
# adjusts it together with `spec/VERSION` and the compatibility matrix in
# the release-prep PR review (or in a follow-up commit on the release PR
# before merging).
__version__ = "3.19.0"  # x-release-please-version
__min_spec_version__ = "3.19.0"
