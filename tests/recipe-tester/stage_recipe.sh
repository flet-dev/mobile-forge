#!/usr/bin/env bash
# Stage a recipe's test file(s) into this app for build/run.
#
# Used by:
#   - .github/workflows/build-wheels.yml (per-job, before `flet build`)
#   - local dev (run before `uv sync && flet build`)
#
# Usage:
#   ./stage_recipe.sh <recipe-name> [<version>]
#
# Examples:
#   ./stage_recipe.sh numpy 2.2.2
#   ./stage_recipe.sh pillow            # no version pin
#
# Effects (idempotent):
#   - (re)creates ./recipe_tests/ with the recipe's pytest files
#   - generates pyproject.toml from pyproject.toml.tpl with the
#     __RECIPE_DEP__ token replaced by "<name>[==<version>]"

set -euo pipefail

RECIPE="${1:?usage: $0 <recipe-name> [<version>]}"
VERSION="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RECIPE_DIR="$REPO_ROOT/recipes/$RECIPE"
TEST_DIR="$SCRIPT_DIR/recipe_tests"

if [ ! -d "$RECIPE_DIR" ]; then
    echo "::error::Recipe not found: $RECIPE_DIR" >&2
    exit 1
fi

# 1. Stage the test file(s) into recipe_tests/. Wipe first so we don't carry
#    leftover files from a previous recipe.
rm -rf "$TEST_DIR"
mkdir -p "$TEST_DIR"

if [ -d "$RECIPE_DIR/test" ]; then
    # Directory shape (pillow): test/test_<name>.py + adjacent assets
    cp -r "$RECIPE_DIR/test/." "$TEST_DIR/"
elif compgen -G "$RECIPE_DIR/test_*.py" > /dev/null; then
    # Flat shape (numpy, lxml, pandas, …): test_<name>.py
    cp "$RECIPE_DIR"/test_*.py "$TEST_DIR/"
else
    echo "::error::No test file(s) found at $RECIPE_DIR/test_*.py or $RECIPE_DIR/test/" >&2
    exit 1
fi

# 2. Substitute the __RECIPE_DEP__ token in the pyproject template and write
#    a fresh pyproject.toml (which is gitignored).
DEP="$RECIPE"
[ -n "$VERSION" ] && DEP="$RECIPE==$VERSION"

# Use a temp file + mv so the substitution is sed-portability-friendly
# (BSD sed and GNU sed differ on -i quoting).
TPL="$SCRIPT_DIR/pyproject.toml.tpl"
OUT="$SCRIPT_DIR/pyproject.toml"
sed "s|__RECIPE_DEP__|$DEP|" "$TPL" > "$OUT"

echo "Staged recipe '$RECIPE' (dep: $DEP)"
echo "  recipe_tests/:"
ls -1 "$TEST_DIR" | sed 's/^/    /'
echo "  pyproject.toml: generated (gitignored)"
echo ""
echo "Next:"
echo "  cd $(realpath --relative-to="$PWD" "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")"
echo "  PIP_FIND_LINKS=\"\$(realpath ../../dist)\" uvx --with flet-cli flet build apk --arch arm64-v8a --yes"
