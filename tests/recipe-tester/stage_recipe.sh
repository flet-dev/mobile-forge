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
#    from the recipe's optional tests/requirements.txt.
DEP="$RECIPE"
[ -n "$VERSION" ] && DEP="$RECIPE==$VERSION"

# Test-only deps: packages the tests import that are NOT in the recipe's
# Requires-Dist (e.g. numpy for a zero-runtime-dep recipe like safetensors,
# whose numpy integration is extra-gated upstream). One PEP 508 spec per
# line; blanks and full-line comments are skipped. Each dep must resolve for
# the MOBILE target — pure-Python from PyPI, or a recipe published on
# pypi.flet.dev (or seeded into dist/) — the same constraint a real app faces.
REQS_FILE="$TEST_DIR/requirements.txt"
TEST_DEPS=()
if [ -f "$REQS_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # ltrim/rtrim, then skip blanks and full-line comments
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [ -z "$line" ] && continue
        [ "${line:0:1}" = "#" ] && continue
        # Deps are emitted as TOML literal (single-quoted) strings so PEP 508
        # markers — which legitimately contain double quotes — pass through
        # verbatim; a single quote inside the spec would end the TOML string.
        if [[ "$line" == *"'"* ]]; then
            echo "::error::single quotes are not supported in $REQS_FILE: $line" >&2
            exit 1
        fi
        TEST_DEPS+=("$line")
    done < "$REQS_FILE"
fi

# Path-hungry packages to ship EXTRACTED to disk instead of inside Flet 0.86's
# compressed sitepackages.zip — those that read bundled data via a real __file__
# path (rather than importlib.resources) and otherwise crash on-device with
# NotADirectoryError. One relative path per line in recipes/<pkg>/extract_packages.txt
# (blanks and full-line comments skipped); emitted into
# [tool.flet.android].extract_packages as a TOML array. Absent file => [] (no-op).
EXTRACT_FILE="$RECIPE_DIR/extract_packages.txt"
EXTRACT_ENTRIES=()
if [ -f "$EXTRACT_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [ -z "$line" ] && continue
        [ "${line:0:1}" = "#" ] && continue
        # Entries become double-quoted TOML strings; a literal double quote in
        # a path would end the string. Package names / relative paths never have one.
        if [[ "$line" == *'"'* ]]; then
            echo "::error::double quotes are not supported in $EXTRACT_FILE: $line" >&2
            exit 1
        fi
        EXTRACT_ENTRIES+=("$line")
    done < "$EXTRACT_FILE"
fi
# Comma-joined TOML array body, e.g. "matplotlib", "thinc" (empty when no file).
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

echo "Staged recipe '$RECIPE' (dep: $DEP)"
echo "  recipe_tests/:"
ls -1 "$TEST_DIR" | sed 's/^/    /'
echo "  pyproject.toml: generated (gitignored)"
if [ ${#TEST_DEPS[@]} -gt 0 ]; then
    echo "  test-only deps (tests/requirements.txt): ${TEST_DEPS[*]}"
fi
if [ ${#EXTRACT_ENTRIES[@]} -gt 0 ]; then
    echo "  extract-to-disk (extract_packages.txt): ${EXTRACT_ENTRIES[*]}"
fi
echo ""
echo "Next:"
echo "  cd $(realpath --relative-to="$PWD" "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")"
echo "  PIP_FIND_LINKS=\"\$(realpath ../../dist)\" uvx --with flet-cli flet build apk --arch arm64-v8a --yes"
