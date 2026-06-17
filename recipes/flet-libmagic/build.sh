#!/bin/bash
# flet-libmagic: libmagic (the `file` library) as a SHARED library (Pattern H)
# for python-magic's ctypes loader. Ships:
#   - opt/lib/libmagic.so          (the lib python-magic dlopens)
#   - opt/share/misc/magic.mgc     (the compiled magic database libmagic loads)
# serious-python surfaces the .so into Android jniLibs / an iOS framework; the
# magic.mgc data file rides along in the wheel for the loader to point at.
set -eu

NAME=magic

common_args="\
    --disable-dependency-tracking \
    --disable-libseccomp \
    --disable-bzlib --disable-xzlib --disable-zlib --disable-zstdlib --disable-lzlib"

# The magic database (magic.mgc) is compiled by the `file` tool at build time.
# Cross-compiling, the target `file` can't run on the build host, so build a
# native `file` first (out-of-tree) and point the cross build at it via
# FILE_COMPILE so the DB is compiled by a host binary of the SAME version.
mkdir -p _hostbuild
# Force the NATIVE build toolchain here: forge exports the cross CC/CFLAGS/etc.
# for the target, but this `file` must run on the build machine to compile the DB.
( cd _hostbuild && \
    CC=cc CXX=c++ CPP="cc -E" CFLAGS= CXXFLAGS= CPPFLAGS= LDFLAGS= AR=ar RANLIB=ranlib STRIP=strip \
    ../configure --silent $common_args --disable-shared >/dev/null && \
    make -j "$CPU_COUNT" >/dev/null )
HOST_FILE="$PWD/_hostbuild/src/file"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    ./configure \
        --host=$HOST_TRIPLET \
        --prefix=$PREFIX \
        --enable-shared --disable-static \
        $common_args
    make -j "$CPU_COUNT" FILE_COMPILE="$HOST_FILE"
    make install FILE_COMPILE="$HOST_FILE"

    # Collapse versioned .so + symlinks to a single unversioned libmagic.so
    # (Android extracts only files literally matching lib*.so; python-magic
    # dlopens "libmagic.so" by name).
    cd "$PREFIX/lib"
    real=$(readlink -f "lib$NAME.so")
    tmp=$(mktemp); cp "$real" "$tmp"
    rm -f "lib$NAME.so" "lib$NAME.so".*
    mv "$tmp" "lib$NAME.so"; chmod 755 "lib$NAME.so"
    cd - >/dev/null
else
    # iOS: libtool can't emit a versioned darwin dylib under cross-compile, so
    # build static then hand-link the shared lib. config.sub doesn't know Apple
    # mobile triplets — feed it an equivalent Darwin triplet (CC/CFLAGS do the
    # real targeting).
    case $HOST_TRIPLET in
        arm64-apple-ios)            host=arm-apple-darwin23 ;;
        arm64-apple-ios-simulator)  host=aarch64-apple-darwin23 ;;
        x86_64-apple-ios-simulator) host=x86_64-apple-darwin23 ;;
        *) echo "Unknown iOS host triplet: $HOST_TRIPLET"; exit 1 ;;
    esac
    # iOS's simulator SDK exports pipe2 as a linkable symbol (so configure's
    # cross AC_CHECK_FUNC sets HAVE_PIPE2) but doesn't declare it for the
    # deployment target -> implicit-declaration error in funcs.c. Force it off
    # so file uses its pipe()+fcntl fallback.
    ac_cv_func_pipe2=no ./configure \
        --host=$host \
        --prefix=$PREFIX \
        --enable-static --disable-shared \
        $common_args
    make -j "$CPU_COUNT" FILE_COMPILE="$HOST_FILE"
    make install FILE_COMPILE="$HOST_FILE"

    cd "$PREFIX/lib"
    $CC $CFLAGS -shared \
        -Wl,-all_load "lib$NAME.a" \
        -install_name "@rpath/lib$NAME.so" \
        -o "lib$NAME.so"
    rm -f "lib$NAME.a"
    cd - >/dev/null
fi

# Keep opt/lib/libmagic.so + opt/share/misc/magic.mgc; drop everything else
# (the host `file` binary, headers, man pages, pkgconfig, libtool archives).
shopt -s nullglob
rm -rf "$PREFIX/bin" "$PREFIX/include" "$PREFIX/share/man"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la
