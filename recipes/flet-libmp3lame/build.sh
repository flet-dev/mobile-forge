#!/bin/bash
set -eu

# PIC: the archive is linked into the shared libsndfile.so.
export CFLAGS="${CFLAGS:-} -fPIC"

# Only libmp3lame is wanted; the frontend drags in a terminal UI and, on 3.100,
# an frontend/get_audio.c that does not cross-compile.
common_args="\
    --disable-dependency-tracking \
    --enable-static --disable-shared \
    --disable-frontend --disable-decoder --disable-gtktest \
    --disable-analyzer-hooks --disable-nasm"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    host=$HOST_TRIPLET
else
    # lame 3.100's config.sub (2016) rejects arm64-apple-ios -- feed it the
    # equivalent Darwin triplet; CC/CFLAGS do the real targeting.
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

./configure --host=$host --prefix=$PREFIX $common_args
make -j "$CPU_COUNT"
make install

shopt -s nullglob
rm -rf "$PREFIX/share" "$PREFIX/bin"
rm -f "$PREFIX"/lib/*.la
