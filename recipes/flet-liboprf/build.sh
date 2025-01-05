#!/bin/bash
set -eu

cd src
make -j $CPU_COUNT
make install

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/lib/*.a
else
    rm -r $PREFIX/lib/*.so
fi