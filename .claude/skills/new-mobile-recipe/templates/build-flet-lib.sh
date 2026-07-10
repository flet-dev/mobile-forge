#!/bin/bash
# Canonical autotools-based cross-compile script for a flet-lib* recipe.
# Use this as a starting point — adapt to upstream's actual build system.
#
# Available environment variables (set by forge):
#   CC, CXX, AR, STRIP, RANLIB             — cross-compile toolchain
#   CFLAGS, CPPFLAGS, LDFLAGS              — pre-configured for SDK + install_root + 16KB align (Android)
#   HOST_TRIPLET                           — e.g. aarch64-apple-ios, aarch64-linux-android
#   HOST_ARCH                              — e.g. arm64, arm64-v8a
#   BUILD_TRIPLET                          — e.g. arm64-apple-darwin (the laptop's triplet)
#   SDK                                    — iphoneos, iphonesimulator, android, etc.
#   CROSS_VENV_SDK                         — same as $SDK; idiomatic platform check
#   SDK_VERSION                            — 13.0 (iOS) or 24 (Android)
#   SDK_ROOT                               — xcrun --show-sdk-path output (empty on Android)
#   PREFIX                                 — install into here (= <build>/wheel/opt)
#   PYTHON_PREFIX                          — host Python prefix
#   PLATLIB                                — host Python platlib site-packages
#   CPU_COUNT                              — multiprocessing.cpu_count()
#   NDK_ROOT, NDK_SYSROOT, ANDROID_ABI,
#   ANDROID_API_LEVEL                      — Android-only

set -eu   # bash 3.2 compatible (no -o pipefail in older bash) — macOS still ships 3.2

# ---------------------------------------------------------------------------
# Platform-specific configure args. Use plain string variables, NOT bash
# arrays — under `set -u`, expanding an empty array errors with "unbound
# variable" on bash 3.2 (which macOS ships).
# ---------------------------------------------------------------------------
if [ "$CROSS_VENV_SDK" = "android" ]; then
    # Examples of common Android-only flags:
    #   - Android NDK r27d API 24 bionic doesn't expose iconv (added in API 28).
    #     Pass --without-iconv if the package's configure cares.
    #   - C++ codebases: don't add -lstdc++ here; NDK clang accepts it but
    #     the link should happen in the package's own makefile.
    extra_args=""
else
    # iOS — Apple toolchain accepts most autotools flags transparently.
    extra_args=""
fi

# ---------------------------------------------------------------------------
# Configure
# ---------------------------------------------------------------------------
./configure \
    --host=$HOST_TRIPLET \
    --build=$BUILD_TRIPLET \
    --prefix=$PREFIX \
    $extra_args

# ---------------------------------------------------------------------------
# Build & install
# ---------------------------------------------------------------------------
make -j $CPU_COUNT
make install

# ---------------------------------------------------------------------------
# Cleanup — remove artifacts not consumed by downstream Python recipes.
#
# Rules of thumb:
#   - Do KEEP $PREFIX/lib/*.a (iOS-only consumers static-link them)
#   - Do delete *.la (libtool archives — not portable)
#   - Do delete pkgconfig/ (not used by downstream; pkg-config is disabled in forge)
#   - Do delete cmake/ (same reasoning)
#   - Do delete share/ (docs/locale/etc., not consumed)
#   - Do delete bin/ on Android if the package builds CLI tools (.so-only delivery)
#
# `shopt -s nullglob` is REQUIRED before glob deletes — without it, `rm -r
# $PREFIX/lib/*.la` passes the literal `*.la` to rm when no matches exist
# and fails the script.
# ---------------------------------------------------------------------------
shopt -s nullglob

rm -rf $PREFIX/share
rm -rf $PREFIX/lib/cmake
rm -rf $PREFIX/lib/pkgconfig
rm -rf $PREFIX/lib/*.la
rm -rf $PREFIX/lib/*.sh

# Android-only: delete the static archive (only .so is consumed)
# if [ "$CROSS_VENV_SDK" = "android" ]; then
#     rm -rf $PREFIX/lib/*.a
# fi
