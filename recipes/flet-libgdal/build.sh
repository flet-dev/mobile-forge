#!/bin/bash
set -eu

mkdir build
cd build

if [ $CROSS_VENV_SDK == "android" ]; then
    cmake .. \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=NEVER \
        -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=NEVER \
        -DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO \
        -DPROJ_LIBRARY=$PLATLIB/opt/lib/libproj.so \
        -DPROJ_INCLUDE_DIR=$PLATLIB/opt/include \
        -DSQLite3_LIBRARY=$PYTHON_PREFIX/lib/libsqlite3_python.so \
        -DSQLite3_INCLUDE_DIR=$PYTHON_PREFIX/include \
        -DGDAL_BUILD_OPTIONAL_DRIVERS=ON \
        -DOGR_BUILD_OPTIONAL_DRIVERS=ON \
        -DGDAL_USE_EXPAT=OFF \
        -DGDAL_USE_OPENSSL=OFF \
        -DGDAL_USE_CURL=OFF \
        -DGDAL_USE_LIBXML2=OFF \
        -DBUILD_APPS=OFF \
        -DBUILD_TESTING=OFF
else
    cmake .. \
        -DCMAKE_SYSTEM_NAME=iOS \
        -DCMAKE_OSX_SYSROOT=$SDK \
        -DCMAKE_OSX_ARCHITECTURES=$HOST_ARCH \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$PREFIX \
        -DBUILD_SHARED_LIBS=OFF \
        -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=NEVER \
        -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=NEVER \
        -DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO \
        -DCMAKE_CXX_FLAGS="$CFLAGS" \
        -DGDAL_USE_EXTERNAL_LIBS=OFF \
        -DPROJ_LIBRARY=$PLATLIB/opt/lib/libproj.a \
        -DPROJ_INCLUDE_DIR=$PLATLIB/opt/include \
        -DSQLite3_LIBRARY=$SDK_ROOT/usr/lib/libsqlite3.tbd \
        -DSQLite3_INCLUDE_DIR=$SDK_ROOT/usr/include \
        -DGDAL_BUILD_OPTIONAL_DRIVERS=ON \
        -DOGR_BUILD_OPTIONAL_DRIVERS=ON \
        -DBUILD_APPS=OFF \
        -DBUILD_TESTING=OFF
fi

cmake --build . -j $CPU_COUNT
cmake --build . --target install

rm -rf $PREFIX/bin
rm -rf $PREFIX/share/{bash-completion,man}
rm -rf $PREFIX/lib/{cmake,pkgconfig}

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/share
fi