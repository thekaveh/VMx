#!/usr/bin/env bash
set -euo pipefail

repo_url="${1:-https://github.com/thekaveh/VMx.wiki.git}"
workdir="${2:-docs/_build/wiki-repo}"

python3 tools/docs/build_wiki.py --out docs/_build/wiki
rm -rf "$workdir"
git clone "$repo_url" "$workdir"
find "$workdir" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp docs/_build/wiki/*.md "$workdir"/
mkdir -p "$workdir/assets"
mkdir -p "$workdir/assets/diagrams"
find docs/assets/diagrams -maxdepth 1 -type f \( -name "*.html" -o -name "*.svg" -o -name "*.png" \) \
  -exec cp {} "$workdir/assets/diagrams/" \;
(
  cd "$workdir"
  git add .
  if git diff --cached --quiet; then
    echo "wiki already up to date"
    exit 0
  fi
  git commit -m "docs: publish VMx wiki"
  git push
)
