#!/bin/bash
set -eu

if [ $CROSS_VENV_SDK == "android" ]; then
    cmake \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCRC32C_BUILD_TESTS=0 \
        -DCRC32C_BUILD_BENCHMARKS=0 \
        -DCRC32C_USE_GLOG=0 \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=1 \
        -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX"
else
    cmake \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        -DCRC32C_BUILD_TESTS=0 \
        -DCRC32C_BUILD_BENCHMARKS=0 \
        -DCRC32C_USE_GLOG=0 \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$PREFIX
fi

make -j $CPU_COUNT
make install

# cleanup
rm -r $PREFIX/lib/cmake