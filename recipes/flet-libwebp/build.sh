#!/bin/bash
set -eu

# The image-format detection only feeds the cwebp/dwebp/gif2webp tools, which we
# delete; disabling it keeps configure from probing for host libpng/jpeg/tiff/gif.
# --prefix must be the real staging dir, not overridden at `make install` time:
# libwebp.la links libsharpyuv.la, and libtool refuses to install a shared library
# into a directory that disagrees with the -rpath it was linked with.
./configure --host=$HOST_TRIPLET --build=$BUILD_TRIPLET --prefix=$PREFIX \
    --enable-libwebpmux --enable-libwebpdemux \
    --disable-png --disable-jpeg --disable-tiff --disable-gif \
    --disable-gl --disable-sdl --disable-wic
# libtool's linux defaults hardcode -rpath $PREFIX/lib into the shared libraries,
# baking the build machine's absolute path into a published wheel. Nothing on the
# device lives there; jniLibs resolves these by SONAME.
sed -i.bak 's|^hardcode_into_libs=.*|hardcode_into_libs=no|' libtool
# Fail loud if libtool ever renames the variable: the silent outcome is a
# published wheel with the build machine's paths in it.
grep -q '^hardcode_into_libs=no' libtool || { echo "libtool rpath patch failed"; exit 1; }

make -j $CPU_COUNT
make install

rm -rf $PREFIX/bin $PREFIX/share
rm -rf $PREFIX/lib/{*.la,pkgconfig}

# Android links these dynamically (Pillow's _webp.so gets a DT_NEEDED and flet
# stages the .so into jniLibs); iOS is static-only, and there libtool leaves
# sharpyuv out of libwebp.a -- Pillow's setup.py already adds -lsharpyuv there.
if [ $CROSS_VENV_SDK == "android" ]; then
    rm -f $PREFIX/lib/*.a
fi
