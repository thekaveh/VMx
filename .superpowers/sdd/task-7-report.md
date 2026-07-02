## 2026-07-02 Task 7

- Status: DONE
- Branch: `codex/vmx-docs-site`

### Files Changed

- `mkdocs.yml`
- `docs/site/flavors/index.md`
- `docs/site/flavors/csharp.md`
- `docs/site/flavors/python.md`
- `docs/site/flavors/typescript.md`
- `docs/site/flavors/swift.md`
- `docs/site/flavors/cross-language-naming.md`
- `docs/site/examples/index.md`
- `docs/site/examples/notes-workspace.md`
- `docs/site/examples/notes-workspace-vm-layer.md`
- `docs/site/examples/global-search-token-paging.md`
- `docs/site/examples/editor-mode-discriminator-vm.md`
- `docs/site/examples/tag-autocomplete-searchable-state.md`
- `docs/site/examples/smaller-examples.md`
- `docs/site/integration-recipes.md`
- `docs/site/specification-conformance.md`
- `docs/site/contributing-releases.md`

### Validation

1. `uv run --with-requirements docs/requirements.txt python -m mkdocs build --strict`
   - Result: exit `0`
   - Output:
     - `INFO    -  Cleaning site directory`
     - `INFO    -  Building documentation to directory: /Users/kaveh/repos/VMx/.worktrees/vmx-docs-site/site`
     - `INFO    -  Documentation built in 0.52 seconds`
     - Material for MkDocs emitted its upstream MkDocs 2.0 warning banner before the build logs.

2. `uv run --with 'mdformat==0.7.22' --with 'mdformat-gfm==1.0.0' --with 'mdformat-tables==1.0.0' mdformat --check docs/site/flavors/index.md docs/site/flavors/csharp.md docs/site/flavors/python.md docs/site/flavors/typescript.md docs/site/flavors/swift.md docs/site/flavors/cross-language-naming.md docs/site/examples/index.md docs/site/examples/notes-workspace.md docs/site/examples/notes-workspace-vm-layer.md docs/site/examples/global-search-token-paging.md docs/site/examples/editor-mode-discriminator-vm.md docs/site/examples/tag-autocomplete-searchable-state.md docs/site/examples/smaller-examples.md docs/site/integration-recipes.md docs/site/specification-conformance.md docs/site/contributing-releases.md`
   - Result: exit `0`

3. `uv run --with 'pre-commit==4.3.0' pre-commit run check-yaml --files mkdocs.yml`
   - Result: exit `0`
   - Output: `check yaml...Passed`

4. `rg -n 'assets/diagrams/examples-vm-layer\\.(svg|png)|notes-showcase-vm-hierarchy\\.svg' site/examples site/search`
   - Result: exit `0`
   - Verified:
     - `site/examples/notes-workspace/index.html` contains the page-relative `../../assets/diagrams/examples-vm-layer.svg` and `.png` references.
     - `site/examples/notes-workspace-vm-layer/index.html` contains the same page-relative diagram references.
     - the generated output also preserves the GitHub link to `examples/assets/notes-showcase-vm-hierarchy.svg`.

### Concerns

- None.
