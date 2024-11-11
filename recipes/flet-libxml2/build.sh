#!/bin/bash
set -eu

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --without-python
make -j $CPU_COUNT
make install

mv $PREFIX/include/libxml2/libxml $PREFIX/include
rm -r $PREFIX/include/libxml2

rm -r $PREFIX/share
rm -r $PREFIX/lib/{cmake,pkgconfig,*.a,*.la,*.sh}