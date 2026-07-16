PYTHON ?= python3

.PHONY: help docs-build docs-check docs-serve docs-wiki

help:
	@printf '%s\n' \
		'docs-build  Generate site/wiki inputs and build the MkDocs site' \
		'docs-check  Run the full three-surface docs gate' \
		'docs-serve  Generate and serve the MkDocs site locally' \
		'docs-wiki   Generate and dry-run the GitHub wiki sync'

docs-build:
	$(PYTHON) -m scripts.docs.build_docs --site --wiki
	$(PYTHON) docs/assets/diagrams/generate_diagrams.py --check
	$(PYTHON) tools/generate-doc-diagrams.py --check
	$(PYTHON) -m scripts.docs.validate_diagrams
	mkdocs build --strict

docs-check:
	$(PYTHON) -m ruff check scripts/docs tests/docs docs/assets/diagrams tools/generate-doc-diagrams.py tools/docs --config langs/python/pyproject.toml
	$(PYTHON) -m ruff format --check scripts/docs tests/docs docs/assets/diagrams tools/generate-doc-diagrams.py tools/docs --config langs/python/pyproject.toml
	$(PYTHON) -m scripts.docs.check_docs
	$(PYTHON) docs/assets/diagrams/generate_diagrams.py --check
	$(PYTHON) tools/generate-doc-diagrams.py --check
	$(PYTHON) -m scripts.docs.validate_diagrams
	$(PYTHON) -m pytest tests/docs docs/assets/diagrams/test_generate_diagrams.py -q
	mkdocs build --strict

docs-serve:
	$(PYTHON) -m scripts.docs.build_docs --site
	mkdocs serve

docs-wiki:
	$(PYTHON) -m scripts.docs.build_docs --wiki
	$(PYTHON) -m scripts.docs.push_wiki --check
