#!/bin/bash
set -eu

# SQLite3 discovery for Android:
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

if [ $CROSS_VENV_SDK == "android" ]; then
    cmake \
        -DCMAKE_SYSTEM_NAME=Android \
        -DANDROID_PLATFORM=$SDK_VERSION \
        -DANDROID_ABI=$ANDROID_ABI \
        -DCMAKE_TOOLCHAIN_FILE=$NDK_ROOT/build/cmake/android.toolchain.cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DBUILD_TESTING=0 \
        -DTIFF_LIBRARY="$PLATLIB/opt/lib/libtiff.so" \
        -DTIFF_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DCURL_LIBRARY="$PLATLIB/opt/lib/libcurl.so" \
        -DCURL_INCLUDE_DIR="$PLATLIB/opt/include" \
        -DSQLite3_LIBRARY=$HOST_PYTHON_HOME/lib/libsqlite3_python.so \
        -DSQLite3_INCLUDE_DIR=$SQLITE3_INC
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