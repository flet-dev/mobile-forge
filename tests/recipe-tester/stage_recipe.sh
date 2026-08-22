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

# Look for test files in the recipe's tests/ directory
if [ -d "$RECIPE_DIR/tests" ]; then
    cp -r "$RECIPE_DIR/tests/." "$TEST_DIR/"
else
    echo "::error::No tests/ directory found in $RECIPE_DIR/" >&2
    exit 1
fi

# 2. Generate pyproject.toml from the template (gitignored): pin the recipe
#    under test (__RECIPE_DEP__) and expand test-only deps (__TEST_DEPS__)
#    from the recipe's meta.yaml `test.requires`.
DEP="$RECIPE"
[ -n "$VERSION" ] && DEP="$RECIPE==$VERSION"

# Declarative lists live in the recipe's meta.yaml; read them the way forge loads
# meta (Jinja -> YAML) via read_meta_list.py, run hermetically with uv so
# jinja2/pyyaml are present regardless of the caller's environment.
meta_list() {  # $1 = dotted key -> one item per line on stdout
    uv run --no-project --quiet --with jinja2 --with pyyaml \
        python3 "$SCRIPT_DIR/read_meta_list.py" "$RECIPE_DIR/meta.yaml" "$1"
}

# Test-only deps: packages the tests import that are NOT in the recipe's
# Requires-Dist (e.g. numpy for a recipe whose numpy integration is extra-gated
# upstream). PEP 508 specs from meta.yaml `test.requires`; each must resolve for
# the MOBILE target — pure-Python from PyPI, or a recipe published on
# pypi.flet.dev (or seeded into dist/) — the same constraint a real app faces.
if ! TEST_REQ_RAW="$(meta_list test.requires)"; then
    echo "::error::failed to read test.requires from $RECIPE_DIR/meta.yaml" >&2
    exit 1
fi
TEST_DEPS=()
while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    # Deps are emitted as TOML literal (single-quoted) strings so PEP 508 markers
    # — which legitimately contain double quotes — pass through verbatim; a single
    # quote inside the spec would end the TOML string.
    if [[ "$line" == *"'"* ]]; then
        echo "::error::single quotes are not supported in test.requires: $line" >&2
        exit 1
    fi
    TEST_DEPS+=("$line")
done <<< "$TEST_REQ_RAW"

# Path-hungry packages to ship EXTRACTED to disk instead of inside Flet 0.86's
# compressed sitepackages.zip — those that read bundled data via a real __file__
# path (rather than importlib.resources) and otherwise crash on-device with
# NotADirectoryError. Declared as the recipe's top-level `extract_packages:` list
# in meta.yaml; emitted into [tool.flet.android].extract_packages as a TOML array.
if ! EXTRACT_RAW="$(meta_list extract_packages)"; then
    echo "::error::failed to read extract_packages from $RECIPE_DIR/meta.yaml" >&2
    exit 1
fi
EXTRACT_ENTRIES=()
while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    # Entries become double-quoted TOML strings; a literal double quote in a path
    # would end the string. Package names / relative paths never have one.
    if [[ "$line" == *'"'* ]]; then
        echo "::error::double quotes are not supported in extract_packages: $line" >&2
        exit 1
    fi
    EXTRACT_ENTRIES+=("$line")
done <<< "$EXTRACT_RAW"
# Comma-joined TOML array body, e.g. "matplotlib", "thinc" (empty when none declared).
EXTRACT_LIST=""
for e in ${EXTRACT_ENTRIES[@]+"${EXTRACT_ENTRIES[@]}"}; do
    [ -n "$EXTRACT_LIST" ] && EXTRACT_LIST="$EXTRACT_LIST, "
    EXTRACT_LIST="$EXTRACT_LIST\"$e\""
done

# Expand the template line-by-line with printf '%s' rather than sed: the
# replacement text (PEP 508 specs) may contain characters that are unsafe in
# a sed RHS, and BSD/GNU sed disagree on escaping rules.
TPL="$SCRIPT_DIR/pyproject.toml.tpl"
OUT="$SCRIPT_DIR/pyproject.toml"
: > "$OUT"
while IFS= read -r tpl_line || [ -n "$tpl_line" ]; do
    # Trimmed copy, so the token matches are exact-line (a comment merely
    # *mentioning* a token must pass through verbatim, not expand).
    trimmed="${tpl_line#"${tpl_line%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
    if [ "$trimmed" = '"__RECIPE_DEP__",' ]; then
        printf '%s\n' "${tpl_line/__RECIPE_DEP__/$DEP}" >> "$OUT"
    elif [ "$trimmed" = "__TEST_DEPS__" ]; then
        # Replaced by zero or more dep lines. The ${arr[@]+...} guard keeps
        # the empty-array expansion safe under `set -u` on macOS bash 3.2.
        for dep in ${TEST_DEPS[@]+"${TEST_DEPS[@]}"}; do
            printf "    '%s',\n" "$dep" >> "$OUT"
        done
    elif [[ "$tpl_line" == *"__EXTRACT_PACKAGES__"* ]]; then
        printf '%s\n' "${tpl_line/__EXTRACT_PACKAGES__/$EXTRACT_LIST}" >> "$OUT"
    else
        printf '%s\n' "$tpl_line" >> "$OUT"
    fi
done < "$TPL"

# When SERIOUS_PYTHON_REF is set (from the CI `serious_python_ref` input, or a
# local env), pin serious_python + its platform implementations to that ref of
# flet-dev/serious-python so the recipe-tester on-device test builds against an
# UNRELEASED sp fix (#223 framework relocation, _SorefFinder, ...). Appended here
# instead of hardcoded in the template so the ref is a single CI knob; empty ->
# the published serious_python is used. SERIOUS_PYTHON_URL overrides the repo URL.
if [ -n "${SERIOUS_PYTHON_REF:-}" ]; then
    SP_URL="${SERIOUS_PYTHON_URL:-https://github.com/flet-dev/serious-python.git}"
    {
        echo ""
        echo "[tool.flet.flutter.pubspec.dependency_overrides]"
        for _sp in serious_python serious_python_darwin serious_python_android serious_python_platform_interface; do
            echo "$_sp = { git = { url = \"$SP_URL\", ref = \"$SERIOUS_PYTHON_REF\", path = \"src/$_sp\" } }"
        done
    } >> "$OUT"
    echo "  serious_python pinned: $SP_URL@$SERIOUS_PYTHON_REF (dependency_overrides)"
fi

echo "Staged recipe '$RECIPE' (dep: $DEP)"
echo "  recipe_tests/:"
ls -1 "$TEST_DIR" | sed 's/^/    /'
echo "  pyproject.toml: generated (gitignored)"
if [ ${#TEST_DEPS[@]} -gt 0 ]; then
    echo "  test-only deps (meta.yaml test.requires): ${TEST_DEPS[*]}"
fi
if [ ${#EXTRACT_ENTRIES[@]} -gt 0 ]; then
    echo "  extract-to-disk (meta.yaml extract_packages): ${EXTRACT_ENTRIES[*]}"
fi
echo ""
echo "Next:"
echo "  cd $(realpath --relative-to="$PWD" "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")"
echo "  PIP_FIND_LINKS=\"\$(realpath ../../dist)\" uvx --with flet-cli flet build apk --arch arm64-v8a --yes"
