# VMx Documentation Diagrams

Diagrams in this directory are generated assets used by the `.io` site and the
GitHub wiki. Each diagram is stored as:

- `.html` — standalone source page
- `.svg` — vector embed
- `.png` — high-resolution landscape image for GitHub/wiki rendering

`diagram-registry.json` is the validation source of truth.

Regenerate the triplets with `python3 generate_diagrams.py`; the renderer
requires `rsvg-convert` and `pngquant` on `PATH`.
