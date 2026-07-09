#!/bin/bash
# Fix CI-baked absolute paths in the Python Android support tarball's
# sysconfigdata files. This is a one-time operation per python-build tarball
# (and idempotent — running it twice is a no-op).
#
# Two independent things get rewritten:
#
# Phase 1: CI runner paths
#   - python-android-mobile-forge-3.12.tar.gz is built on Linux CI runners
#   - CPython's `configure` records absolute CC/CXX paths at build time
#   - The CI runner's NDK lives at /home/runner/ndk/r27d/...
#   - On macOS local dev, those paths point nowhere; crossenv can't find the compiler
#   - Fix: rewrite the embedded paths so they point at the local NDK + python-build
#     install dirs.
#
# Phase 2: /usr/local install prefix (the CPython `./configure` default)
#   - CPython's configure was run with no --prefix, so it baked '/usr/local'
#     into 'prefix', 'exec_prefix', 'LIBDIR' (and 'LIBPC').
#   - This breaks any Rust/PyO3-based recipe (tokenizers, polars, …): PyO3's
#     build script reads sysconfigdata's LIBDIR to know where libpython lives
#     and emits '-L/usr/local/lib -lpython3 -lpython3.12'. On macOS that path
#     has no libpython and the link fails with 'unable to find library -lpython3'.
#   - iOS doesn't hit this because forge's Rust path passes -framework Python
#     explicitly; only Android needs sysconfigdata to be correct.
#   - Fix: rewrite '/usr/local' → '<install>/python-3.12.X' per-file.
#
# Both phases auto-detect whether they need to run and skip cleanly otherwise.

set -eu

require_env() {
    local name="$1"
    if [ -z "${!name:-}" ]; then
        echo "ERROR: \$$name is not set." >&2
        echo "  Set it and re-run this script. See SKILL.md Phase 2 for details." >&2
        exit 1
    fi
}

require_env NDK_HOME
require_env MOBILE_FORGE_ANDROID_SUPPORT_PATH

# Derive the local NDK toolchain dir (darwin-x86_64 or whatever)
local_toolchain=$(echo "$NDK_HOME"/toolchains/llvm/prebuilt/* 2>/dev/null | tr ' ' '\n' | head -1)
if [ -z "$local_toolchain" ] || [ ! -d "$local_toolchain" ]; then
    echo "ERROR: Cannot find a toolchain in $NDK_HOME/toolchains/llvm/prebuilt/*" >&2
    echo "  Is NDK_HOME pointing at a valid NDK install?" >&2
    exit 1
fi

# Find all sysconfigdata files (one per ABI)
files=()
while IFS= read -r f; do
    files+=("$f")
done < <(find "$MOBILE_FORGE_ANDROID_SUPPORT_PATH"/install/android/*/python-3.12.*/lib/python3.12 -name '_sysconfigdata__linux_.py' 2>/dev/null)

if [ ${#files[@]} -eq 0 ]; then
    echo "ERROR: No _sysconfigdata__linux_.py files found." >&2
    echo "  Expected location: \$MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/*/python-3.12.*/lib/python3.12/" >&2
    exit 1
fi

echo "Found ${#files[@]} sysconfigdata files:"
for f in "${files[@]}"; do
    echo "  $f"
done
echo ""

# =========================================================================
# Phase 0: self-relocating tarball check (python-build PRs #5/#8/#9)
# =========================================================================
# Releases since 2026-06 inject a _mobile_forge_relocate_sysconfig() block
# that rewrites the CI-baked paths at import time — the /home/runner strings
# in the file are build-time constants, NOT live paths. Nothing to fix.
if grep -q "_mobile_forge_relocate_sysconfig" "${files[0]}" 2>/dev/null; then
    echo "Sysconfigdata is SELF-RELOCATING (python-build >= 2026-06) — no fix needed."
    echo "The relocator resolves the NDK via NDK_HOME/ANDROID_NDK_HOME, ~/ndk/<ver>,"
    echo "or ~/Library/Android/sdk/ndk/*. If crossenv still can't find the compiler,"
    echo "set NDK_HOME rather than rewriting this file."
    exit 0
fi

# =========================================================================
# Phase 1: CI runner paths (NDK + python-build install root)
# =========================================================================
echo "──── Phase 1: CI runner paths ────"
sample="${files[0]}"
ci_ndk_path=$(grep -oE "/home/runner/ndk/r27d/toolchains/llvm/prebuilt/[a-z0-9_-]+" "$sample" 2>/dev/null | head -1 || true)
ci_install_root=$(grep -oE "/home/runner/work/python-build/python-build" "$sample" 2>/dev/null | head -1 || true)

if [ -z "$ci_ndk_path" ] && [ -z "$ci_install_root" ]; then
    echo "  No CI-baked /home/runner paths found — already patched (or never present)."
    phase1_did_anything=0
else
    # Build sed expressions for phase 1
    sed_args=()
    if [ -n "$ci_ndk_path" ]; then
        echo "  Replacing NDK toolchain path:"
        echo "    $ci_ndk_path"
        echo "    → $local_toolchain"
        sed_args+=(-e "s|$ci_ndk_path|$local_toolchain|g")
    fi
    if [ -n "$ci_install_root" ]; then
        echo "  Replacing Python install root path:"
        echo "    $ci_install_root"
        echo "    → $MOBILE_FORGE_ANDROID_SUPPORT_PATH"
        sed_args+=(-e "s|$ci_install_root|$MOBILE_FORGE_ANDROID_SUPPORT_PATH|g")
    fi

    # Apply (with .bak backup)
    for f in "${files[@]}"; do
        sed -i.bak "${sed_args[@]}" "$f"
        echo "    patched: $f"
    done
    phase1_did_anything=1
fi

echo ""

# =========================================================================
# Phase 2: /usr/local → actual install prefix (per-file, since each ABI
# has a different install root)
# =========================================================================
echo "──── Phase 2: /usr/local install prefix ────"
phase2_did_anything=0
for f in "${files[@]}"; do
    # Derive the install prefix from the file path:
    # <prefix>/lib/python3.12/_sysconfigdata__linux_.py  →  <prefix>
    install_prefix=$(cd "$(dirname "$f")/../.." && pwd)

    # Cheap detection: does this file still hold the CPython configure default?
    if ! grep -q "'/usr/local'" "$f"; then
        echo "  $f"
        echo "    /usr/local already rewritten — skipping."
        continue
    fi

    # Order matters: longest pattern first (otherwise '/usr/local' fires inside
    # '/usr/local/lib/pkgconfig' and produces malformed paths).
    sed -i.bak3 -E \
        -e "s|'/usr/local/lib/pkgconfig'|'$install_prefix/lib/pkgconfig'|g" \
        -e "s|'/usr/local/lib'|'$install_prefix/lib'|g" \
        -e "s|'/usr/local'|'$install_prefix'|g" \
        "$f"
    echo "  $f"
    echo "    → install prefix: $install_prefix"
    phase2_did_anything=1
done

if [ $phase2_did_anything = 0 ]; then
    echo "  No /usr/local references remained — phase 2 was already done."
fi
echo ""

# =========================================================================
# Verify the rewrites landed correctly
# =========================================================================
echo "──── Verification ────"

# Phase 1 check: no more /home/runner refs in critical paths
remaining=$(grep -l "/home/runner/ndk\|/home/runner/work/python-build" "${files[@]}" 2>/dev/null | wc -l | tr -d ' ')
if [ "$remaining" = "0" ]; then
    echo "  ✓ phase 1: no /home/runner refs remain"
else
    echo "  ⚠ phase 1: $remaining file(s) still have /home/runner refs (may be cosmetic)"
fi

# Phase 1 check: the CC binary actually exists at the rewritten path
expected_cc="$local_toolchain/bin/aarch64-linux-android24-clang"
if [ -x "$expected_cc" ]; then
    echo "  ✓ phase 1: CC path resolves: $expected_cc"
else
    echo "  ⚠ phase 1: CC path doesn't resolve: $expected_cc"
fi

# Phase 2 check: LIBDIR for each ABI now points at a directory holding libpython
for f in "${files[@]}"; do
    libdir=$(sed -nE "s|.*'LIBDIR':\s*'([^']+)'.*|\1|p" "$f")
    arch=$(echo "$f" | sed -nE 's|.*/install/android/([^/]+)/.*|\1|p')
    if [ -f "$libdir/libpython3.12.so" ]; then
        echo "  ✓ phase 2 ($arch): LIBDIR has libpython3.12.so"
    else
        echo "  ⚠ phase 2 ($arch): LIBDIR=$libdir but libpython3.12.so isn't there"
    fi
done

echo ""
echo "Done. Next: run \`forge --clean android:<arch> <your-recipe>\` to verify."
echo "Backups: <file>.bak (phase 1), <file>.bak3 (phase 2)."
