#!/bin/bash
# Robust NDK r27d installer for macOS.
#
# Why this exists: .ci/install_ndk.sh has a bug on macOS where 7-zip's
# "dangerous symbolic link" warning (from lldb python bindings in the DMG)
# causes the silent abort of the install. This script:
#   1. Adds -snld to 7-zip to skip those symlinks silently
#   2. Detects and recovers from a half-installed previous state
#   3. Falls back to hdiutil mount if 7-zip completely fails
#
# Usage: bash .claude/skills/new-mobile-recipe/scripts/install_ndk_r27d.sh
# Output: prints `export NDK_HOME=...` for you to add to your shell.

set -eu

NDK_VERSION="r27d"
NDK_TARGET="${NDK_HOME:-$HOME/ndk/$NDK_VERSION}"

# 1. Check if NDK is already there
if [ -d "$NDK_TARGET" ] && [ -x "$NDK_TARGET"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android24-clang 2>/dev/null ] || \
   ls "$NDK_TARGET"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android24-clang 2>/dev/null | head -1 | grep -q clang; then
    echo "NDK already installed at $NDK_TARGET"
    ver=$(grep '^Pkg.ReleaseName' "$NDK_TARGET/source.properties" 2>/dev/null | sed 's/.*= //')
    echo "  Version: $ver"
    echo ""
    echo "To use it, run in your shell:"
    echo "  export NDK_HOME=$NDK_TARGET"
    exit 0
fi

# 2. Check if a previous attempt left a partial dir
if [ -d "$NDK_TARGET" ] && [ -z "$(ls -A "$NDK_TARGET" 2>/dev/null)" ]; then
    echo "Found empty $NDK_TARGET — removing and reinstalling."
    rmdir "$NDK_TARGET"
fi

# 3. Confirm we're on macOS
if [ "$(uname)" != "Darwin" ]; then
    echo "This script is macOS-specific. For Linux, use .ci/install_ndk.sh directly."
    exit 1
fi

# 4. Determine working dir
script_dir="$(dirname "$(realpath "$0")")"
mobile_forge_root="$(realpath "$script_dir/../../../..")"
downloads_dir="$mobile_forge_root/downloads"
mkdir -p "$downloads_dir"

dmg_name="android-ndk-${NDK_VERSION}-darwin.dmg"
dmg_path="$downloads_dir/$dmg_name"

# 5. Download DMG if not cached
if [ -f "$dmg_path" ]; then
    size=$(stat -f%z "$dmg_path" 2>/dev/null || stat -c%s "$dmg_path")
    if [ "$size" -lt 100000000 ]; then  # < 100MB means truncated
        echo "Cached DMG looks truncated ($size bytes), redownloading"
        rm "$dmg_path"
    else
        echo "Using cached DMG: $dmg_path ($(echo "scale=0; $size/1024/1024" | bc) MB)"
    fi
fi

if [ ! -f "$dmg_path" ]; then
    echo "Downloading $dmg_name..."
    curl -L --fail --progress-bar \
        -o "$dmg_path" \
        "https://dl.google.com/android/repository/$dmg_name"
fi

# 6. Get 7-zip if not cached
sevenzip_dir="$downloads_dir/7zip"
sevenzip="$sevenzip_dir/7zz"

if [ ! -x "$sevenzip" ]; then
    echo "Installing 7-zip..."
    mkdir -p "$sevenzip_dir"
    cd "$sevenzip_dir"
    curl -L --fail --progress-bar \
        -o 7z2301-mac.tar.xz \
        https://www.7-zip.org/a/7z2301-mac.tar.xz
    tar -xf 7z2301-mac.tar.xz
    cd -
fi

# 7. Extract. The -snld flag (skip non-existent links / dangerous links)
# is the key fix — without it, 7-zip aborts on the lldb python binding
# symlinks inside the DMG.
extract_dir="$downloads_dir/ndk-extract"
rm -rf "$extract_dir"
mkdir -p "$extract_dir"

echo "Extracting DMG (this takes 1-2 min)..."
cd "$extract_dir"
if "$sevenzip" x -snld "$dmg_path" -bso0 -bsp1 2>&1 | tail -5; then
    echo "  7-zip extraction completed"
else
    rc=$?
    echo "  7-zip extraction completed with rc=$rc (errors expected — checking content)"
fi
cd -

# 8. Find the extracted NDK dir
ndk_src=$(find "$extract_dir" -type d -name "NDK" -path "*Contents*" | head -1)
if [ -z "$ndk_src" ]; then
    echo "ERROR: didn't find the NDK dir inside the extracted DMG." >&2
    echo "  Contents of $extract_dir:" >&2
    ls -la "$extract_dir" >&2
    echo ""
    echo "  Falling back to hdiutil mount..." >&2

    mount_point="/Volumes/Android NDK ${NDK_VERSION}"
    hdiutil attach "$dmg_path" -nobrowse -quiet
    ndk_src=$(find "$mount_point" -type d -name "NDK" -path "*Contents*" 2>/dev/null | head -1)
    if [ -z "$ndk_src" ]; then
        echo "  ERROR: hdiutil mount also didn't find the NDK dir." >&2
        hdiutil detach "$mount_point" -quiet 2>/dev/null || true
        exit 1
    fi
fi

echo "  Found NDK at: $ndk_src"

# 9. Move into place
mkdir -p "$(dirname "$NDK_TARGET")"
echo "Moving NDK to $NDK_TARGET..."
mv "$ndk_src" "$NDK_TARGET"

# 10. Detach DMG if mounted
hdiutil detach "/Volumes/Android NDK ${NDK_VERSION}" -quiet 2>/dev/null || true

# 11. Clean up extract dir
rm -rf "$extract_dir"

# 12. Verify
clang_path=$(ls "$NDK_TARGET"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android24-clang 2>/dev/null | head -1)
if [ -z "$clang_path" ]; then
    echo "ERROR: install verified failed — clang not found at expected path." >&2
    exit 1
fi

ver=$(grep '^Pkg.ReleaseName' "$NDK_TARGET/source.properties" 2>/dev/null | sed 's/.*= //')
echo ""
echo "✓ NDK $ver installed at $NDK_TARGET"
echo "  clang: $clang_path"
echo ""
echo "Add this to your shell (or current session):"
echo "  export NDK_HOME=$NDK_TARGET"
