#!/bin/bash
set -eu

# SIMD is only available for x86, so disable for consistency between ABIs.
if [ $CROSS_VENV_SDK == "android" ]; then
    cmake -G"Unix Makefiles" \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=24 \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_INSTALL_PREFIX=$PREFIX .
else
    cmake -G"Unix Makefiles" \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_SYSTEM_PROCESSOR=$HOST_ARCH \
        -DCMAKE_INSTALL_PREFIX=$PREFIX .
fi

make -j $CPU_COUNT > /dev/null 2>&1 || { echo "Error building libjpeg"; exit 1; }
make install

rm -r $PREFIX/{bin,share}
rm -r $PREFIX/lib/{pkgconfig,cmake}
