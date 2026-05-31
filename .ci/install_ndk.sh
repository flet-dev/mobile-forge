#!/usr/bin/env bash
# Install an Android NDK component via sdkmanager.
#
# Usage:
#   .ci/install_ndk.sh                    # uses $NDK_VERSION
#   .ci/install_ndk.sh 27.3.13750724      # explicit component version
#   .ci/install_ndk.sh r27d               # release letter (resolved via Google's manifest)
#
# Installs into $ANDROID_HOME/ndk/<component-version>/ — sdkmanager's
# standard layout, which is also where AGP looks for Gradle builds.
# When SOURCED (`. install_ndk.sh ...`), exports NDK_HOME pointing at
# the resulting install path; forge reads that env var.
#
# Idempotent: if the NDK is already installed, the sdkmanager call is skipped.
#
# Requires `sdkmanager` from the Android SDK cmdline-tools. On CI both
# the Ubuntu and macOS runner images ship it; locally install Android
# Studio or the standalone cmdline-tools.

set -eu

version="${1:-${NDK_VERSION:-}}"
if [ -z "$version" ]; then
    echo "usage: $0 <ndk-version>  (or set NDK_VERSION)" >&2
    exit 2
fi

# Resolve release-letter form (e.g. "r27d") to the component version
# (e.g. "27.3.13750724") via Google's repository manifest. Skipped when
# the input is already in component form. Uses awk to track the most-recent
# `path="ndk;<version>"` attribute.
if [[ "$version" =~ ^r[0-9]+[a-z]*$ ]]; then
    letter="$version"
    version=$(curl -sfL https://dl.google.com/android/repository/repository2-3.xml \
                | awk -v zip="android-ndk-${letter}-linux.zip" '
                    match($0, /path="ndk;[0-9.]+"/) {
                        current = substr($0, RSTART+10, RLENGTH-11)
                    }
                    !found && index($0, zip) { print current; found=1 }
                  ')
    if [ -z "$version" ]; then
        echo "Could not resolve NDK release letter '$letter' to a component version." >&2
        echo "Check it exists at https://dl.google.com/android/repository/repository2-3.xml" >&2
        exit 4
    fi
    echo "Resolved $letter → $version"
fi

: "${ANDROID_HOME:?ANDROID_HOME must be set (Android SDK location)}"

sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "$sdkmanager" ]; then
    echo "sdkmanager not found at $sdkmanager" >&2
    echo "  Install Android Studio or the standalone cmdline-tools first." >&2
    exit 3
fi

install_dir="$ANDROID_HOME/ndk/$version"

# Idempotency check: any host-triplet clang under the install dir means
# it's already installed and usable.
if ! find "$install_dir/toolchains/llvm/prebuilt"/*/bin/aarch64-linux-android*-clang 2>/dev/null | grep -q .; then
    echo "Installing NDK $version via sdkmanager…"
    yes | "$sdkmanager" --licenses > /dev/null
    "$sdkmanager" --install "ndk;$version"
fi

echo "NDK $version installed at $install_dir"
export NDK_HOME="$install_dir"

# When run as a GH Actions step (not sourced — the export above doesn't
# persist across steps), write NDK_HOME to $GITHUB_ENV so downstream
# steps inherit it. Harmless to no-op when $GITHUB_ENV is unset (local).
if [ -n "${GITHUB_ENV:-}" ]; then
    echo "NDK_HOME=$install_dir" >> "$GITHUB_ENV"
fi
