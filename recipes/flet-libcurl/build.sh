#!/bin/bash
set -eu

OPENSSL_PREFIX="$PLATLIB/opt"
if [ ! -f "$OPENSSL_PREFIX/include/openssl/ssl.h" ] || \
   { [ ! -f "$OPENSSL_PREFIX/lib/libssl.a" ] && [ ! -f "$OPENSSL_PREFIX/lib/libssl.so" ]; } || \
   { [ ! -f "$OPENSSL_PREFIX/lib/libcrypto.a" ] && [ ! -f "$OPENSSL_PREFIX/lib/libcrypto.so" ]; }; then
    OPENSSL_PREFIX="$PYTHON_PREFIX"
fi

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --with-openssl="$OPENSSL_PREFIX"
make -j $CPU_COUNT
make install

rm -r $PREFIX/{bin,share}
rm -r $PREFIX/lib/{*.la,pkgconfig}

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/lib/*.a
fi
