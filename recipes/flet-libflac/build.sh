#!/bin/bash
set -eu

# ENABLE_MULTITHREADING puts Threads::Threads in libFLAC's exported CMake
# target, which libsndfile (no find_package(Threads)) then cannot resolve.
# libsndfile drives the single-threaded encoder API regardless.
common_args="\
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_PREFIX_PATH=$PLATLIB/opt \
    -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_CXXLIBS=OFF \
    -DBUILD_PROGRAMS=OFF \
    -DBUILD_EXAMPLES=OFF \
    -DBUILD_TESTING=OFF \
    -DBUILD_DOCS=OFF \
    -DINSTALL_MANPAGES=OFF \
    -DWITH_OGG=ON \
    -DENABLE_MULTITHREADING=OFF \
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
