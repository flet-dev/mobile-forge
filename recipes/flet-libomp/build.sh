#!/bin/bash
set -eu

if [[ "$CROSS_VENV_SDK" != "android" ]]; then
    echo "This package can be built for Android only."
    exit 1
fi

# libomp.so lives in clang's per-target runtime dir, keyed by the LLVM arch name
# (not the Android ABI): arm64-v8a->aarch64, armeabi-v7a->arm, x86_64->x86_64,
# x86->i386. This is the same libomp.so the toolchain links with -fopenmp.
case "$HOST_ARCH" in
    arm64-v8a)   omp_arch=aarch64 ;;
    armeabi-v7a) omp_arch=arm ;;
    x86_64)      omp_arch=x86_64 ;;
    x86)         omp_arch=i386 ;;
    *) echo "flet-libomp: unsupported arch '$HOST_ARCH'"; exit 1 ;;
esac

toolchain=$(echo "$NDK_ROOT"/toolchains/llvm/prebuilt/*)
libomp=$(echo "$toolchain"/lib/clang/*/lib/linux/"$omp_arch"/libomp.so)

if [ ! -f "$libomp" ]; then
    echo "flet-libomp: libomp.so not found at $libomp"
    exit 1
fi

mkdir -p "$PREFIX/lib"
cp "$libomp" "$PREFIX/lib/libomp.so"
