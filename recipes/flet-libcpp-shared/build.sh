#!/bin/bash
set -eu

if [[ "$CROSS_VENV_SDK" != "android" ]]; then
    echo "This package can be built for Android only."
    exit 1
fi

toolchain=$(echo $NDK_ROOT/toolchains/llvm/prebuilt/*)
export LIBC_SHARED_SO="$toolchain/sysroot/usr/lib/${HOST_TRIPLET}/libc++_shared.so"

mkdir -p $PREFIX/lib
cp $LIBC_SHARED_SO $PREFIX/lib
