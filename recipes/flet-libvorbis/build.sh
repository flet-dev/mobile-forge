#!/bin/bash
set -eu

# Hand libvorbis's bundled FindOgg the flet-libogg paths directly: its
# find_path/find_library calls are re-rooted at the SDK sysroot under both
# cross toolchains, so a pkg-config HINT alone never resolves.
common_args="\
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_TESTING=OFF \
    -DOGG_INCLUDE_DIR=$PLATLIB/opt/include \
    -DOGG_LIBRARY=$PLATLIB/opt/lib/libogg.a"

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
