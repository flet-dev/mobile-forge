#!/bin/bash
set -eu

cmake \
    -DCMAKE_SYSTEM_NAME=Android \
    -DANDROID_PLATFORM=$SDK_VERSION \
    -DANDROID_ABI=$ANDROID_ABI \
    -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DBUILD_TESTING=0 \
    -DTIFF_LIBRARY="$PLATLIB/opt/lib/libtiff.so" \
    -DTIFF_INCLUDE_DIR="$PLATLIB/opt/include" \
    -DCURL_LIBRARY="$PLATLIB/opt/lib/libcurl.so" \
    -DCURL_INCLUDE_DIR="$PLATLIB/opt/include" \
    -DSQLite3_LIBRARY=$PYTHON_PREFIX/lib/libsqlite3.so \
    -DSQLite3_INCLUDE_DIR=$PYTHON_PREFIX/include

cmake --build . -j $CPU_COUNT
cmake --build . --target install

rm -rf $PREFIX/{bin,share}
rm -rf $PREFIX/lib/{cmake,pkgconfig}