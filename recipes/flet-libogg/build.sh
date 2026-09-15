#!/bin/bash
set -eu

# PIC: the archive is linked into the shared libsndfile.so.
common_args="\
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_TESTING=OFF \
    -DINSTALL_DOCS=OFF"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    cmake -B build \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        $common_args
else
    cmake -B build \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        $common_args
fi

cmake --build build -j "$CPU_COUNT"
cmake --install build

rm -rf "$PREFIX/share"
