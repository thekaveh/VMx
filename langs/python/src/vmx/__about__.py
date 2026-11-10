"""Package metadata for vmx."""

# release-please updates the value preceding the marker comment on the
# `__version__` line each time it cuts a release PR. `__min_spec_version__`
# is not auto-bumped: it must equal `spec/VERSION`
# (`tools/check-version-consistency.py`), so update it in the same change
# whenever `spec/VERSION` changes.
__version__ = "3.30.0"  # x-release-please-version
__min_spec_version__ = "3.30.0"
