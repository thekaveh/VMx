# ADR 0230 — Spec version labels name the first spec tag that contains the ADR

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (`spec/HISTORY.md` and the ADR registry only; no spec chapter or conformance ID changes)
- **Related:** #1809 (the issue this ADR implements), #1478 (HISTORY §39 and ADR-0227), #1814 (the automated check for these records).

## 1. Context

Each spec release has an annotated tag `spec-vX.Y.Z`. Ten such tags exist: `spec-v1.0.0`, `spec-v2.0.0`, `spec-v2.1.0`, `spec-v2.2.0`, `spec-v2.3.0`, `spec-v2.4.0`, `spec-v2.6.0`, `spec-v3.1.0`, `spec-v3.23.0` and `spec-v3.29.0`. Some spec versions never received a tag, such as 3.0.0 and 3.2.0.

An ADR's `Spec version` field names the version the decision belongs to. Eleven ADRs named a tagged release whose tree does not contain the ADR file. Each was merged after that tag was cut, without a version bump:

- ADR-0020 and ADR-0021 named 2.0.0, and the first tag containing them is `spec-v2.1.0`.
- ADR-0045 and ADR-0046 named 2.6.0, and the first tag containing them is `spec-v3.1.0`.
- ADR-0080 and ADR-0081 named 3.1.0, and the first tag containing them is `spec-v3.23.0`.
- ADR-0129 to ADR-0133 named 3.23.0, and the first tag containing them is `spec-v3.29.0`.

ADR-0146 to ADR-0150 name 3.29.0, but no tag contains them, and `spec-v3.30.0` does not exist yet. HISTORY §1 to §38 also omitted 25 ADRs from ADR-0044 onward whose labels name a version from 2.2.0 to 3.29.0. ADR-0043 is the 26th omission in the issue's count, but it has no label.

The registry cell always repeated the preamble label, so the error sat in the labels and was copied into the registry.

## 2. Decision

1. A label that names a spec tag must name the first spec tag whose tree contains the ADR file. Find that tag with `git ls-tree --name-only spec-vX.Y.Z spec/ADRs/` for each tag in version order. The earliest tag that lists the file is the release that carries the decision. The preamble label and the registry cell both name that version.
1. An ADR that no tag contains yet has no tag evidence. Its label stays until the owner cuts the tag that contains it, and then rule 1 applies.
1. Rule 1 covers labels that name a tag. A label that names a version with no tag, such as 3.0.0, 3.2.0 or 3.24.0, is not a release claim that the tags can test, so this ADR leaves it unchanged. Section 3.3 lists those labels for the owner.
1. Each ADR whose label names a version from 2.2.0 to 3.29.0 is cited in the `spec/HISTORY.md` section of that version. An ADR that rule 1 moves is cited in its tag's section and not in the section of its old label.
1. `tools/tests/test_adr_spec_version_labels.py` checks rules 1, 2 and 4 against the git tags and the ADR tree, and checks that each registry cell repeats its label.

## 3. Consequences

### 3.1 Label changes

The preamble label and the registry cell change to the first containing tag. Prose labels keep their wording, so ADR-0020 and ADR-0021 still read "editorial within … (no normative behavior change)", and ADR-0080, ADR-0081 and ADR-0131 still read "introduced in …".

| ADR  | Label before | Label after | First spec tag containing the file |
| ---- | ------------ | ----------- | ---------------------------------- |
| 0020 | 2.0.0        | 2.1.0       | `spec-v2.1.0`                      |
| 0021 | 2.0.0        | 2.1.0       | `spec-v2.1.0`                      |
| 0045 | 2.6.0        | 3.1.0       | `spec-v3.1.0`                      |
| 0046 | 2.6.0        | 3.1.0       | `spec-v3.1.0`                      |
| 0080 | 3.1.0        | 3.23.0      | `spec-v3.23.0`                     |
| 0081 | 3.1.0        | 3.23.0      | `spec-v3.23.0`                     |
| 0129 | 3.23.0       | 3.29.0      | `spec-v3.29.0`                     |
| 0130 | 3.23.0       | 3.29.0      | `spec-v3.29.0`                     |
| 0131 | 3.23.0       | 3.29.0      | `spec-v3.29.0`                     |
| 0132 | 3.23.0       | 3.29.0      | `spec-v3.29.0`                     |
| 0133 | 3.23.0       | 3.29.0      | `spec-v3.29.0`                     |

### 3.2 HISTORY changes

- ADR-0080 and ADR-0081 move from the v3.0.0 to v3.1.0 section (§8) to the v3.22.1 to v3.23.0 section (§32).
- ADR-0129 to ADR-0133 are cited in the v3.28.0 to v3.29.0 section (§38).
- Missing citations are added in the section of each label: ADR-0044 (§6), ADR-0045 and ADR-0046 (§8), ADR-0059 through ADR-0067 (§7), ADR-0103 and ADR-0104 (§27), ADR-0135 (§33), and ADR-0137 through ADR-0141 (§34).
- No section heading changes. The headings of §1 to §38 already name every tagged release from 2.1.0 to 3.29.0.

### 3.3 Left for the owner

- **ADR-0146 to ADR-0150** name 3.29.0, and no tag contains them. Once the owner cuts `spec-v3.30.0`, rule 1 gives them the label 3.30.0, which matches HISTORY §39. ADR-0150 says "the spec version stays 3.29.0" in its body, and that sentence belongs to the owner's edit.
- **82 ADRs name an untagged version, and rule 1 would move each.** They are ADR-0008, ADR-0009, ADR-0037, ADR-0038, ADR-0047 to ADR-0067, ADR-0082 to ADR-0127, and ADR-0134 to ADR-0144. For example, ADR-0082 would move to 3.23.0 and ADR-0134 to 3.29.0. Applying the rule would re-home HISTORY §8 to §37, whose sections carry their own catalog counts. This ADR does not apply it. The owner decides.
- **ADR-0043** has no `Spec version` field. Rule 1 would place it in 2.6.0. The owner decides whether to add the field.
- **Not covered here:** the registry §2.1 text on labels after a tag (issue #1809, step 2), HISTORY sections for 1.0.0 and 2.0.0, and the AGG-007 count in HISTORY §30 (issue #1809, steps 6 and 7).

## 4. Rejected alternatives

- **Name the next spec version.** The issue suggested that a label name the version after the tag that lacks the ADR. A label that names an unreleased version, or a version whose tag does not contain the ADR, cannot be checked against the tags. The spec tags decide which release a decision belongs to, so this ADR uses the first containing tag.
- **Apply rule 1 to every label now.** This is the simplest single rule, but it moves 82 ADRs and re-homes HISTORY sections whose catalog counts describe the in-development version. That changes the history record, so the owner should approve it first (section 3.3).
