#!/bin/bash
set -eu

# SQLite3 discovery for Android, similar layout drift as openssl:
#   - 3.12/3.13: sqlite3.h is bundled inside the python install dir,
#     so $HOST_PYTHON_HOME/include/sqlite3.h works.
#   - 3.14+: sqlite3.h lives in a sibling dir alongside the python
#     install (.../install/android/<abi>/sqlite-X.Y.Z/include/).
# The .so library itself stays inside $HOST_PYTHON_HOME/lib/ on both.
SQLITE3_INC="$HOST_PYTHON_HOME/include"
if [ ! -f "$SQLITE3_INC/sqlite3.h" ]; then
    for candidate in "$HOST_PYTHON_HOME"/../sqlite-*; do
        if [ -f "$candidate/include/sqlite3.h" ]; then
            SQLITE3_INC="$candidate/include"
            break
        fi
    done
fi

mkdir build
cd build

if [ $CROSS_VENV_SDK == "android" ]; then
    cmake .. \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=NEVER \
        -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=NEVER \
        -DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO \
        -DPROJ_LIBRARY=$PLATLIB/opt/lib/libproj.so \
        -DPROJ_INCLUDE_DIR=$PLATLIB/opt/include \
        -DSQLite3_LIBRARY=$HOST_PYTHON_HOME/lib/libsqlite3_python.so \
        -DSQLite3_INCLUDE_DIR=$SQLITE3_INC \
        -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF \
        -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
        -DGDAL_USE_EXPAT=OFF \
        -DGDAL_USE_OPENSSL=OFF \
        -DGDAL_USE_CURL=OFF \
        -DGDAL_USE_LIBXML2=OFF \
        -DGDAL_USE_OPENMP=OFF \
        -DBUILD_APPS=OFF \
        -DBUILD_TESTING=OFF \
        -DBUILD_PYTHON_BINDINGS=OFF
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
        -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF \
        -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
        -DGDAL_USE_OPENMP=OFF \
        -DBUILD_APPS=OFF \
        -DBUILD_TESTING=OFF \
        -DBUILD_PYTHON_BINDINGS=OFF
fi

cmake --build . -j $CPU_COUNT
cmake --build . --target install

rm -rf $PREFIX/{bin,share}
rm -rf $PREFIX/lib/{cmake,pkgconfig}