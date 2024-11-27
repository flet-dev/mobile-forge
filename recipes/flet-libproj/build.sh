#!/bin/bash
set -eu

if [ $CROSS_VENV_SDK == "android" ]; then
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
else
    cmake \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DBUILD_SHARED_LIBS=OFF \
        -DBUILD_TESTING=0 \
        -DTIFF_LIBRARY="$PLATLIB/opt/lib/libtiff.a" \
        -DTIFF_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DCURL_LIBRARY="$PLATLIB/opt/lib/libcurl.a" \
        -DCURL_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DSQLite3_LIBRARY=$SDK_ROOT/usr/lib/libsqlite3.tbd \
        -DSQLite3_INCLUDE_DIR=$SDK_ROOT/usr/include
fi

cmake --build . -j $CPU_COUNT
cmake --build . --target install

rm -rf $PREFIX/{bin,share}
rm -rf $PREFIX/lib/{cmake,pkgconfig}