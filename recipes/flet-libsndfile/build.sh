#!/bin/bash
# flet-libsndfile: libsndfile as a SHARED library (Pattern H) for the pure-Python
# `soundfile` package, which dlopens it through cffi. Ships opt/lib/libsndfile.so
# on both platforms; serious-python surfaces it as Android jniLibs / an iOS
# embedded framework + libsndfile.fwork pointer.
set -eu

NAME=sndfile

common_args="\
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DBUILD_PROGRAMS=OFF \
    -DBUILD_EXAMPLES=OFF \
    -DBUILD_TESTING=OFF \
    -DENABLE_CPACK=OFF \
    -DENABLE_PACKAGE_CONFIG=OFF \
    -DINSTALL_PKGCONFIG_MODULE=OFF \
    -DENABLE_EXTERNAL_LIBS=ON \
    -DENABLE_MPEG=ON \
    -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
    -DCMAKE_PREFIX_PATH=$PLATLIB/opt \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=BOTH \
    -DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    cmake -B build \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
        -DBUILD_SHARED_LIBS=ON \
        $common_args
    cmake --build build -j "$CPU_COUNT"
    cmake --install build
else
    # iOS: build static, then hand-link the shared image. CMake would emit the
    # versioned dylib triplet, and serious-python's framework name is the relative
    # path truncated at the first dot -- libsndfile.dylib and libsndfile.1.dylib
    # would both become one framework. One unversioned file named .so also matches
    # Android's jniLibs glob, so the loader patch needs a single candidate name.
    #
    # -headerpad_max_install_names is not optional: serious-python rewrites install
    # names when it relocates the image into a framework, and without the padding
    # that rewrite fails while the build still exits 0.
    cmake -B build \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        -DBUILD_SHARED_LIBS=OFF \
        $common_args
    cmake --build build -j "$CPU_COUNT"
    cmake --install build

    # force_load (not all_load) so only libsndfile's own objects are taken
    # whole; the codec archives contribute just what libsndfile references.
    # -exported_symbol hides the absorbed codec symbols, matching what the
    # version script already does on Android.
    cd "$PREFIX/lib"
    $CC $CFLAGS -shared \
        -Wl,-headerpad_max_install_names \
        -Wl,-exported_symbol,'_sf_*' \
        -Wl,-force_load,"lib$NAME.a" \
        "$PLATLIB/opt/lib/libFLAC.a" \
        "$PLATLIB/opt/lib/libvorbisenc.a" \
        "$PLATLIB/opt/lib/libvorbis.a" \
        "$PLATLIB/opt/lib/libopus.a" \
        "$PLATLIB/opt/lib/libogg.a" \
        "$PLATLIB/opt/lib/libmp3lame.a" \
        "$PLATLIB/opt/lib/libmpg123.a" \
        -install_name "@rpath/lib$NAME.so" \
        -o "lib$NAME.so"
    rm -f "lib$NAME.a"
    cd - >/dev/null
fi

shopt -s nullglob
rm -rf "$PREFIX/share" "$PREFIX/bin" "$PREFIX/include"
rm -rf "$PREFIX/lib/cmake" "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la
