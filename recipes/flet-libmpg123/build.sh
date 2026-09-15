#!/bin/bash
set -eu

# PIC: the archive is linked into the shared libsndfile.so.
export CFLAGS="${CFLAGS:-} -fPIC"

# --disable-components + --enable-libmpg123 drops the CLI, libout123 and
# libsyn123; libsndfile only decodes through libmpg123.
common_args="\
    --disable-dependency-tracking \
    --enable-static --disable-shared \
    --disable-components --enable-libmpg123 \
    --disable-modules --disable-network"

# The packed CPU sets carry a NEON/SSE decoder plus a generic fallback and pick
# at runtime, so one build serves every device of that ABI.
case $HOST_ARCH in
    arm64-v8a|arm64)   cpu=aarch64 ;;
    armeabi-v7a)       cpu=arm_fpu ;;
    x86_64)            cpu=x86-64 ;;
    *)                 cpu=generic_fpu ;;
esac

if [ "$CROSS_VENV_SDK" = "android" ]; then
    host=$HOST_TRIPLET
else
    # config.sub predates Apple's mobile triplets -- feed it the equivalent
    # Darwin one; CC/CFLAGS do the real targeting.
    case $HOST_TRIPLET in
        arm64-apple-ios)            host=aarch64-apple-darwin23 ;;
        arm64-apple-ios-simulator)  host=aarch64-apple-darwin23 ;;
        x86_64-apple-ios-simulator) host=x86_64-apple-darwin23 ;;
        *) echo "Unknown iOS host triplet: $HOST_TRIPLET"; exit 1 ;;
    esac
    # forge's iOS flags carry a quoted -F path; the quotes reach the compiler
    # literally and break preprocessing. The forge paths have no spaces.
    export CFLAGS="$(printf '%s' "$CFLAGS" | tr -d '"')"
    export CPPFLAGS="$(printf '%s' "${CPPFLAGS:-}" | tr -d '"')"
    export LDFLAGS="$(printf '%s' "${LDFLAGS:-}" | tr -d '"')"
fi

./configure --host=$host --prefix=$PREFIX --with-cpu=$cpu $common_args
make -j "$CPU_COUNT"
make install

shopt -s nullglob
rm -rf "$PREFIX/share" "$PREFIX/bin"
rm -f "$PREFIX"/lib/*.la
