#!/bin/bash
set -eu

./configure --host=$HOST_TRIPLET --prefix=$PREFIX
make -j $CPU_COUNT
make install

rm -r $PREFIX/lib/{*.la,pkgconfig}