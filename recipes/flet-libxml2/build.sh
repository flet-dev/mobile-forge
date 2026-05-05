#!/bin/bash
set -eu

# Android NDK bionic does not expose iconv until API 28; we target 24.
if [ "$CROSS_VENV_SDK" = "android" ]; then
    iconv_arg=--without-iconv
else
    iconv_arg=--with-iconv
fi

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --without-python $iconv_arg
make -j $CPU_COUNT
make install

mv $PREFIX/include/libxml2/libxml $PREFIX/include
rm -r $PREFIX/include/libxml2

shopt -s nullglob
rm -rf $PREFIX/share
rm -rf $PREFIX/lib/cmake $PREFIX/lib/pkgconfig $PREFIX/lib/*.la $PREFIX/lib/*.sh