#!/bin/bash
set -eu

common_args="\
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_TESTING=OFF \
    -DOPUS_BUILD_PROGRAMS=OFF \
    -DOPUS_BUILD_TESTING=OFF"

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
