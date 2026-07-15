#!/bin/bash
# Build a flet-lib* as a SHARED library (Pattern H) — for libraries a
# pure-Python wrapper loads at runtime via ctypes (not linked into a C
# extension at build time). Output is named lib<NAME>.so on BOTH platforms so
# serious-python's *.so handling picks it up:
#   - Android: surfaced into jniLibs/<abi>/, loadable by bare name.
#   - iOS: converted to an embedded framework + lib<NAME>.fwork pointer;
#     iOS CPython's ctypes is .fwork-aware.
#
# Replace <NAME> and the configure flags for your library. See
# recipes/flet-libzbar/build.sh for a worked example, and
# references/recipe-patterns.md § "Pattern H".
set -eu

NAME=<NAME>   # e.g. zbar  (produces lib<NAME>.so)

# Configure flags shared by both platforms — trim to the core library; disable
# GUI/CLI/codec extras your wrapper doesn't use.
common_args="--disable-dependency-tracking <YOUR --without-* / --disable-* FLAGS>"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    # ELF shared lib via libtool works on Android.
    # --disable-pthread: bionic folds pthread into libc (no -lpthread).
    # If the lib hard-uses iconv, add flet-libiconv as a host dep and
    #   --with-libiconv-prefix="$PLATLIB/opt" (Android bionic has no iconv <28).
    ./configure \
        --host=$HOST_TRIPLET \
        --prefix=$PREFIX \
        --enable-shared --disable-static \
        $common_args
    make -j $CPU_COUNT
    make install

    # Collapse versioned .so + symlinks to a single unversioned lib<NAME>.so
    # (Android only extracts files literally matching lib*.so; the wrapper
    # dlopens "lib<NAME>.so" by name).
    cd "$PREFIX/lib"
    real=$(readlink -f "lib$NAME.so")
    tmp=$(mktemp); cp "$real" "$tmp"
    rm -f "lib$NAME.so" "lib$NAME.so".*
    mv "$tmp" "lib$NAME.so"; chmod 755 "lib$NAME.so"
    cd - >/dev/null
else
    # iOS: libtool can't emit a versioned darwin dylib under cross-compile, so
    # build static then hand-link the shared lib. config.sub doesn't know Apple
    # mobile triplets — feed it an equivalent Darwin triplet (real targeting is
    # via CC/CFLAGS). iOS ships a system iconv; link -liconv only if you use it.
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
        <YOUR -l<dep> FLAGS, e.g. -liconv> \
        -install_name "@rpath/lib$NAME.so" \
        -o "lib$NAME.so"
    rm -f "lib$NAME.a"
    cd - >/dev/null
fi

shopt -s nullglob
rm -rf "$PREFIX/share" "$PREFIX/bin"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la
# Keep ONLY lib<NAME>.so in $PREFIX/lib (the wrapper loads it; nothing static).

# REMINDER (iOS): build for ALL THREE slices — `forge iOS flet-lib<NAME>` —
# or serious-python's iphoneos.arm64-reference merge silently drops the lib.
