#!/bin/bash
set -eu

# OpenBLAS is make-based (not autotools). Cross-compile knobs:
#   TARGET/BINARY  — required for cross (OpenBLAS can't probe the target CPU)
#   NOFORTRAN=1    — build BLAS + f2c-converted LAPACK (no Fortran compiler)
#   CROSS=1        — never run target binaries during the build
#   HOSTCC=clang   — build-machine compiler for getarch and friends
case "$HOST_ARCH" in
    arm64-v8a|arm64) TARGET=ARMV8;   BINARY=64 ;;
    armeabi-v7a)     TARGET=ARMV7;   BINARY=32 ;;
    x86_64)          TARGET=NEHALEM; BINARY=64 ;;
    *) echo "flet-libopenblas: unsupported arch '$HOST_ARCH'"; exit 1 ;;
esac

# `libs netlib` builds the BLAS + f2c-LAPACK static lib but skips OpenBLAS's
# self-test binaries (the `tests` target), whose ARMV7 link pulls a hard-float
# -lm_hard that the softfp NDK lacks. The .a is identical; tests aren't needed.
make libs netlib \
    TARGET="$TARGET" BINARY="$BINARY" \
    HOSTCC=clang CC="$CC" AR="$AR" RANLIB=echo \
    NOFORTRAN=1 CROSS=1 \
    USE_THREAD=0 NUM_THREADS=1 \
    NO_SHARED=1 \
    CFLAGS="$CFLAGS" \
    -j"$CPU_COUNT"

make PREFIX="$PREFIX" TARGET="$TARGET" NO_SHARED=1 install
rm -rf "$PREFIX/lib/cmake"

# OpenBLAS installs libopenblas.a as a symlink to the versioned archive; forge's
# copytree dereferences it into two 60 MB files. Collapse to one real libopenblas.a.
ver_a=$(ls "$PREFIX"/lib/libopenblas_*.a 2>/dev/null | head -1 || true)
if [ -n "${ver_a:-}" ]; then
    rm -f "$PREFIX/lib/libopenblas.a"
    mv "$ver_a" "$PREFIX/lib/libopenblas.a"
fi

# Fix openblas.pc for consumers (scipy's meson `dependency('openblas')`):
#  - relocatable libdir/includedir (the baked-in absolute build paths are gone
#    by the time scipy builds against the installed host wheel)
#  - drop extralib's `-lgfortran` (we built NOFORTRAN; the f2c LAPACK lives inside
#    libopenblas and there is no libgfortran on iOS/Android) and `-lpthread`
#    (USE_THREAD=0; pthread is in libc on both platforms).
pc="$PREFIX/lib/pkgconfig/openblas.pc"
sed -i.bak \
    -e 's|^libdir=.*|libdir=${pcfiledir}/..|' \
    -e 's|^includedir=.*|includedir=${pcfiledir}/../../include|' \
    -e 's|^extralib=.*|extralib=|' \
    "$pc"
rm -f "$pc.bak"
