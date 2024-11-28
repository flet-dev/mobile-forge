#!/bin/bash
set -eu

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --disable-docs
make -j $CPU_COUNT
make install

rm -r $PREFIX/bin
rm -rf $PREFIX/lib/{*.la,*xx.*,pkgconfig}

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/lib/*.a
fi