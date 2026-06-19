#!/bin/bash
# flet-libiconv: GNU libiconv as a STATIC, PIC archive for Android. It gets
# folded into shared consumers (libzbar.so), so it must be -fPIC. Android-only
# (iOS/macOS provide a system libiconv).
set -eu

# Static lib folded into a shared .so -> needs PIC.
export CFLAGS="${CFLAGS:-} -fPIC"

./configure \
    --host=$HOST_TRIPLET \
    --prefix=$PREFIX \
    --enable-static --disable-shared \
    --disable-dependency-tracking \
    --disable-nls
make -j $CPU_COUNT
make install

# Keep opt/include (iconv.h) + opt/lib/{libiconv,libcharset}.a; drop the rest.
rm -rf "$PREFIX/bin" "$PREFIX/share"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la
