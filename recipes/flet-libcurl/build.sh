#!/bin/bash
set -eu

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --with-openssl
make -j $CPU_COUNT
make install

rm -r $PREFIX/{bin,share}
rm -r $PREFIX/lib/{*.la,pkgconfig}

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/lib/*.a
fi