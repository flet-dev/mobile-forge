#!/bin/bash
set -eu

if [ $CROSS_VENV_SDK != "android" ]; then
    case $HOST_TRIPLET in
        arm64-apple-ios)
            HOST_TRIPLET=arm-apple-darwin23
            ;;
        arm64-apple-ios-simulator)
            HOST_TRIPLET=aarch64-apple-darwin23
            ;;
        x86_64-apple-ios-simulator)
            HOST_TRIPLET=x86_64-apple-darwin23
            ;;
        *)
            echo "Unknown host triplet: '$HOST_TRIPLET'"
            exit 1
            ;;
    esac
fi

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --disable-soname-versions
make -j $CPU_COUNT
make install

rm -r $PREFIX/lib/{*.la,pkgconfig}

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/lib/*.a
else
    mv $PREFIX/lib/libsodium.dylib $PREFIX/../libsodium.so
fi