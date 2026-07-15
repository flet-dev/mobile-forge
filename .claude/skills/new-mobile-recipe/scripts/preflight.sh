#!/bin/bash
# Preflight check for mobile-forge recipe authoring.
# Run from the mobile-forge repo root: bash .claude/skills/new-mobile-recipe/scripts/preflight.sh
#
# Verifies (in order):
#   1. We're in a mobile-forge clone
#   2. The venv3.12 venv is active (or hints how to activate)
#   3. `forge` CLI is on $PATH
#   4. MOBILE_FORGE_IOS_SUPPORT_PATH points at a valid iOS Python.xcframework tree
#   5. MOBILE_FORGE_ANDROID_SUPPORT_PATH points at a valid Android python install tree
#   6. NDK_HOME points at an r27d (or compatible) NDK install
#   7. dist/ has the iOS dep wheels (bzip2, openssl, etc.)
#   8. dist/ has the Android dep wheels
#   9. The Android sysconfigdata files are self-relocating (python-build >= 2026-06)
#
# Output: prints PASS/FAIL/WARN for each check. Exit code 0 if no FAILs.

set -u

PASS="\033[32m✓\033[0m"
FAIL="\033[31m✗\033[0m"
WARN="\033[33m!\033[0m"
INFO="\033[34mi\033[0m"

fails=0
warns=0

check() {
    local status="$1"
    local label="$2"
    local detail="${3:-}"
    case "$status" in
        pass) echo -e "  ${PASS} $label";;
        fail) echo -e "  ${FAIL} $label"; ((fails++));;
        warn) echo -e "  ${WARN} $label"; ((warns++));;
        info) echo -e "  ${INFO} $label";;
    esac
    [ -n "$detail" ] && echo "        $detail"
}

# 1. cwd is a mobile-forge clone
echo "Environment:"
if [ -f "src/forge/__main__.py" ] && [ -f "pyproject.toml" ] && grep -q "mobile-forge" pyproject.toml 2>/dev/null; then
    check pass "in a mobile-forge repo"
else
    check fail "not in a mobile-forge repo (cwd=$(pwd))" \
        "cd to the mobile-forge clone root and rerun"
    exit 1
fi

# 2. venv active
if [ -n "${VIRTUAL_ENV:-}" ] && [[ "$VIRTUAL_ENV" == *"/venv3.12" ]]; then
    check pass "venv3.12 active ($(basename $VIRTUAL_ENV))"
elif [ -d "venv3.12" ]; then
    check fail "venv3.12 exists but isn't active" \
        "source venv3.12/bin/activate"
else
    check fail "venv3.12 doesn't exist" \
        "source ./setup.sh 3.12.12 (after setting MOBILE_FORGE_*_SUPPORT_PATH env vars)"
fi

# 3. forge on PATH
if command -v forge >/dev/null 2>&1; then
    check pass "forge CLI: $(command -v forge)"
else
    check fail "forge CLI not on PATH" \
        "activate the venv (source venv3.12/bin/activate)"
fi

echo ""
echo "iOS support:"

# 4. iOS support path
if [ -n "${MOBILE_FORGE_IOS_SUPPORT_PATH:-}" ]; then
    if [ -e "$MOBILE_FORGE_IOS_SUPPORT_PATH/support/3.12/iOS/Python.xcframework/ios-arm64/bin/python3.12" ]; then
        check pass "MOBILE_FORGE_IOS_SUPPORT_PATH valid" "($MOBILE_FORGE_IOS_SUPPORT_PATH)"
    else
        check fail "MOBILE_FORGE_IOS_SUPPORT_PATH set but tree is missing python3.12" \
            "expected: \$MOBILE_FORGE_IOS_SUPPORT_PATH/support/3.12/iOS/Python.xcframework/ios-arm64/bin/python3.12"
    fi
else
    check warn "MOBILE_FORGE_IOS_SUPPORT_PATH not set" \
        "if you want iOS builds, download python-ios-mobile-forge-3.12.tar.gz from"\
        "https://github.com/flet-dev/python-build/releases and export the path"
fi

# 7. iOS dep wheels
if ls dist/bzip2-*-ios_*.whl dist/openssl-*-ios_*.whl 2>/dev/null | head -1 | grep -q whl; then
    check pass "iOS dep wheels present in dist/"
elif [ -n "${MOBILE_FORGE_IOS_SUPPORT_PATH:-}" ]; then
    check warn "iOS dep wheels not in dist/ — run: python -m make_dep_wheels iOS"
fi

echo ""
echo "Android support:"

# 5. Android support path
if [ -n "${MOBILE_FORGE_ANDROID_SUPPORT_PATH:-}" ]; then
    if ls "$MOBILE_FORGE_ANDROID_SUPPORT_PATH"/install/android/arm64-v8a/python-3.12.*/bin/python3.12 2>/dev/null | head -1 | grep -q python; then
        check pass "MOBILE_FORGE_ANDROID_SUPPORT_PATH valid" "($MOBILE_FORGE_ANDROID_SUPPORT_PATH)"
    else
        check fail "MOBILE_FORGE_ANDROID_SUPPORT_PATH set but tree is missing python3.12" \
            "expected: \$MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/arm64-v8a/python-3.12.*/bin/python3.12"
    fi
else
    check warn "MOBILE_FORGE_ANDROID_SUPPORT_PATH not set" \
        "if you want Android builds, download python-android-mobile-forge-3.12.tar.gz from"\
        "https://github.com/flet-dev/python-build/releases and export the path"
fi

# 6. NDK
if [ -n "${NDK_HOME:-}" ]; then
    clang_path=$(ls "$NDK_HOME"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android24-clang 2>/dev/null | head -1)
    if [ -n "$clang_path" ] && [ -x "$clang_path" ]; then
        ver=$(grep '^Pkg.ReleaseName' "$NDK_HOME"/source.properties 2>/dev/null | sed 's/.*= //')
        check pass "NDK at $NDK_HOME ($ver)"
        # Warn if not r27d (CI parity)
        if [ "$ver" != "r27d" ]; then
            check warn "NDK is $ver, CI uses r27d — minor differences possible"
        fi
    else
        check fail "NDK_HOME set but doesn't contain aarch64-linux-android24-clang" \
            "expected: \$NDK_HOME/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android24-clang"
    fi
elif [ -n "${MOBILE_FORGE_ANDROID_SUPPORT_PATH:-}" ]; then
    check fail "NDK_HOME not set (required for Android builds)" \
        "run: bash .claude/skills/new-mobile-recipe/scripts/install_ndk_r27d.sh"
fi

# 8. Android dep wheels
if ls dist/bzip2-*-android_*.whl dist/openssl-*-android_*.whl 2>/dev/null | head -1 | grep -q whl; then
    check pass "Android dep wheels present in dist/"
elif [ -n "${MOBILE_FORGE_ANDROID_SUPPORT_PATH:-}" ]; then
    check warn "Android dep wheels not in dist/ — run: python -m make_dep_wheels android"
fi

# 9a. Android libpython.so SONAME check.
# The flet-dev/python-build tarball ships libpython3.12.so without a SONAME.
# Recipes that link target_link_libraries(... Python::Python) (e.g. anything
# using FindPython with Development.Embed) get the absolute build-host path
# embedded as DT_NEEDED → fails to load on device. Fix:
#   patchelf --set-soname libpython3.12.so <so>
if [ -n "${MOBILE_FORGE_ANDROID_SUPPORT_PATH:-}" ]; then
    # Read SONAME byte signature via grep — avoids needing readelf on PATH.
    # We check arm64-v8a as a proxy for all 4 ABIs (they ship identically built).
    libpy=$(ls "$MOBILE_FORGE_ANDROID_SUPPORT_PATH"/install/android/arm64-v8a/python-3.12.*/lib/libpython3.12.so 2>/dev/null | head -1)
    if [ -n "$libpy" ]; then
        # patchelf is the cheapest probe; fall back to NDK readelf
        if command -v patchelf >/dev/null 2>&1; then
            soname=$(patchelf --print-soname "$libpy" 2>/dev/null || true)
        elif [ -n "${NDK_HOME:-}" ]; then
            readelf=$(echo "$NDK_HOME"/toolchains/llvm/prebuilt/*/bin/llvm-readelf 2>/dev/null | head -1)
            if [ -x "$readelf" ]; then
                soname=$("$readelf" -d "$libpy" 2>/dev/null | grep -oE 'soname: \[[^]]*\]' | head -1 || true)
            fi
        fi
        if [ -n "${soname:-}" ] && [ "$soname" != "" ]; then
            check pass "Android libpython3.12.so has SONAME"
        else
            check warn "Android libpython3.12.so has no SONAME" \
                "needed for CMake recipes that link libpython (e.g. pyzmq). Fix:" \
                "  pip install patchelf && for so in \$MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/*/python-*/lib/libpython3.12.so; do patchelf --set-soname libpython3.12.so \"\$so\"; done"
        fi
    fi
fi

# 9b. Android sysconfigdata self-relocation check.
# python-build releases since 2026-06 (PRs #5/#8/#9) inject a
# _mobile_forge_relocate_sysconfig() block that rewrites the CI-baked
# /home/runner paths at import time — those strings staying in the file is
# expected, so we check for the relocator marker, not for the paths.
# setup.sh pins a release >= 20260701, so a normal setup always passes.
if [ -n "${MOBILE_FORGE_ANDROID_SUPPORT_PATH:-}" ]; then
    total_files=$(ls "$MOBILE_FORGE_ANDROID_SUPPORT_PATH"/install/android/*/python-3.12.*/lib/python3.12/_sysconfigdata__linux_.py 2>/dev/null | wc -l | tr -d ' ')
    relocating=$(grep -l "_mobile_forge_relocate_sysconfig" \
        "$MOBILE_FORGE_ANDROID_SUPPORT_PATH"/install/android/*/python-3.12.*/lib/python3.12/_sysconfigdata__linux_.py \
        2>/dev/null | wc -l | tr -d ' ')
    if [ "$total_files" = "0" ]; then
        check fail "No Android sysconfigdata files found under MOBILE_FORGE_ANDROID_SUPPORT_PATH" \
            "re-run: source ./setup.sh <python-version>"
    elif [ "$relocating" = "$total_files" ]; then
        check pass "Android sysconfigdata is self-relocating (python-build >= 2026-06)" \
            "CI-baked strings rewrite themselves at import; ensure NDK_HOME is set"
    else
        check fail "$((total_files - relocating))/$total_files Android sysconfigdata file(s) lack the self-relocation block (tarball predates 2026-06)" \
            "delete downloads/support/python-android-* and re-run: source ./setup.sh <python-version>"
    fi
fi

echo ""
echo "Rust toolchain (only relevant for Rust/PyO3 recipes):"

# 10. Rust targets for mobile.
# Not a hard blocker — only Rust recipes need these. Warn so the dev sees what's
# missing before hitting a confusing cargo error mid-build.
if command -v rustup >/dev/null 2>&1; then
    installed=$(rustup target list --installed 2>/dev/null || true)
    ios_targets="aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios"
    android_targets="aarch64-linux-android arm-linux-androideabi x86_64-linux-android i686-linux-android"
    missing_ios=""
    missing_android=""
    for t in $ios_targets; do
        echo "$installed" | grep -qx "$t" || missing_ios+=" $t"
    done
    for t in $android_targets; do
        echo "$installed" | grep -qx "$t" || missing_android+=" $t"
    done
    if [ -z "$missing_ios" ] && [ -z "$missing_android" ]; then
        check pass "all iOS + Android Rust targets installed"
    else
        cmd=""
        [ -n "$missing_ios" ] && cmd="rustup target add$missing_ios"
        [ -n "$missing_android" ] && cmd="${cmd:+$cmd; }rustup target add$missing_android"
        check warn "some Rust targets not installed — only relevant for Rust recipes" \
            "to install:  $cmd"
    fi
else
    check info "rustup not installed (only needed for Rust/PyO3 recipes)"
fi

echo ""
echo "Summary:"
if [ "$fails" = "0" ] && [ "$warns" = "0" ]; then
    echo -e "  ${PASS} All checks passed — ready to build recipes."
    exit 0
elif [ "$fails" = "0" ]; then
    echo -e "  ${WARN} $warns warning(s) — you can build for whichever platform passed, but check the warnings."
    exit 0
else
    echo -e "  ${FAIL} $fails check(s) failed. Fix the issues above before running forge."
    exit 1
fi
