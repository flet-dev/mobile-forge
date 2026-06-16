#!/bin/bash
# flet-libzbar: build libzbar as a SHARED library (Pattern H) for pyzbar's
# ctypes loader. pyzbar dlopen()s libzbar at runtime, so we ship
# opt/lib/libzbar.so on BOTH platforms; serious-python surfaces it into
# Android jniLibs/<abi>/ and an iOS embedded framework (its ctypes is
# .fwork-aware).
set -eu

NAME=zbar

# The GitHub source archive ships only configure.ac — generate ./configure.
autoreconf -fi

# Core barcode decoder only. pyzbar feeds raw Y800 greyscale buffers, so drop
# the image codecs, every GUI/CLI/video frontend, the language bindings, and
# docs — none of which the ctypes wrapper uses.
common_args="\
    --disable-dependency-tracking \
    --without-x --disable-video \
    --without-gtk --without-qt --without-imagemagick \
    --without-jpeg \
    --without-python --without-java --without-dbus \
    --disable-doc"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    # ELF shared lib via libtool works on Android.
    # --disable-pthread: bionic folds pthread into libc (no -lpthread).
    # iconv is absent from bionic at API 24, so AM_ICONV resolves to "no" and
    # zbar builds without charset conversion (fine for QR byte/UTF-8 payloads).
    ./configure \
        --host=$HOST_TRIPLET \
        --prefix=$PREFIX \
        --enable-shared --disable-static --disable-pthread \
        $common_args
    make -j $CPU_COUNT
    make install

    # Collapse the versioned .so + symlinks into a single unversioned
    # libzbar.so (Android extracts only files literally matching lib*.so, and
    # pyzbar dlopens "libzbar.so" by name).
    cd "$PREFIX/lib"
    real=$(readlink -f "lib$NAME.so")
    tmp=$(mktemp); cp "$real" "$tmp"
    rm -f "lib$NAME.so" "lib$NAME.so".*
    mv "$tmp" "lib$NAME.so"; chmod 755 "lib$NAME.so"
    cd - >/dev/null
else
    # iOS: libtool can't emit a versioned darwin dylib under cross-compile, so
    # build static then hand-link the shared lib. config.sub doesn't know Apple
    # mobile triplets — feed it an equivalent Darwin triplet (the real targeting
    # is via CC/CFLAGS). iOS ships a system libiconv, so link -liconv to satisfy
    # any iconv symbols AM_ICONV pulled in.
    case $HOST_TRIPLET in
        arm64-apple-ios)            host=arm-apple-darwin23 ;;
        arm64-apple-ios-simulator)  host=aarch64-apple-darwin23 ;;
        x86_64-apple-ios-simulator) host=x86_64-apple-darwin23 ;;
        *) echo "Unknown iOS host triplet: $HOST_TRIPLET"; exit 1 ;;
    esac
    ./configure \
        --host=$host \
        --prefix=$PREFIX \
        --enable-static --disable-shared \
        $common_args
    make -j $CPU_COUNT
    make install

    cd "$PREFIX/lib"
    $CC $CFLAGS -shared \
        -Wl,-all_load "lib$NAME.a" \
        -liconv \
        -install_name "@rpath/lib$NAME.so" \
        -o "lib$NAME.so"
    rm -f "lib$NAME.a"
    cd - >/dev/null
fi

# Keep ONLY opt/lib/libzbar.so — the ctypes wrapper loads it; nothing links it.
shopt -s nullglob
rm -rf "$PREFIX/share" "$PREFIX/bin" "$PREFIX/include"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la
