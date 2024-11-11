#!/bin/bash
set -eu

export CFLAGS="-Wno-error=incompatible-function-pointer-types"
export LIBS="-lxml2"

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --without-crypto --without-python \
     --with-libxml-include-prefix=$PLATLIB/opt/include \
     --with-libxml-libs-prefix=$PLATLIB/opt/lib 
make -j $CPU_COUNT V=1
make install

rm -r $PREFIX/share
rm -r $PREFIX/lib/{libxslt-*,pkgconfig,*.a,*.la,*.sh}