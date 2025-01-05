#!/bin/bash
set -eu

cd src
make -j $CPU_COUNT
make install

rm -r $PREFIX/bin
rm -r $PREFIX/lib/*.a

if [ $CROSS_VENV_SDK != "android" ]; then
    mv $PREFIX/lib/libopaque.so $PREFIX/../libopaque.so
fi