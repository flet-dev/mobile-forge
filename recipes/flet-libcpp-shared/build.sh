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

# This recipe has no upstream archive, so nothing carries a licence into the wheel on
# its own. libc++_shared.so is LLVM's, under Apache-2.0 WITH LLVM-exception; take the
# notice from the same NDK the .so was copied from so the two can never drift.
cp "$toolchain/NOTICE" ./LICENSE
