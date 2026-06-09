#!/bin/bash
set -eu

# OpenSSL discovery, for 3 known layouts across python-build versions:
#   1. host-dep extraction (iOS): the openssl wheel is declared in
#      `requirements.host`, pip extracts it into $PLATLIB/opt — so headers
#      land at $PLATLIB/opt/include/openssl/ssl.h and libs at
#      $PLATLIB/opt/lib/libssl.{a,so}.
OPENSSL_PREFIX="$PLATLIB/opt"

#   2. python-build 3.12/3.13 (Android): openssl is bundled directly
#      into the python install dir, so $PYTHON_PREFIX itself acts as the
#      prefix and headers live at $PYTHON_PREFIX/include/openssl/ssl.h.
if [ ! -f "$OPENSSL_PREFIX/include/openssl/ssl.h" ] || \
   { [ ! -f "$OPENSSL_PREFIX/lib/libssl.a" ] && [ ! -f "$OPENSSL_PREFIX/lib/libssl.so" ]; } || \
   { [ ! -f "$OPENSSL_PREFIX/lib/libcrypto.a" ] && [ ! -f "$OPENSSL_PREFIX/lib/libcrypto.so" ]; }; then
    OPENSSL_PREFIX="$PYTHON_PREFIX"
fi

#   3. python-build 3.14+ (Android): openssl lives as a *sibling* of the
#      python install dir (e.g. .../install/android/<abi>/openssl-3.0.20-1).
#      Glob siblings of $HOST_PYTHON_HOME (the support-tree python install
#      dir, distinct from $PYTHON_PREFIX which on 3.14 relocates into the
#      cross-venv), and take the first match.
if [ ! -f "$OPENSSL_PREFIX/include/openssl/ssl.h" ]; then
    for candidate in "$HOST_PYTHON_HOME"/../openssl-*; do
        if [ -f "$candidate/include/openssl/ssl.h" ]; then
            OPENSSL_PREFIX="$candidate"
            break
        fi
    done
fi

PKG_CONFIG=false ./configure --host=$HOST_TRIPLET --prefix=$PREFIX --with-openssl="$OPENSSL_PREFIX"
make -j $CPU_COUNT
make install

rm -r $PREFIX/{bin,share}
rm -r $PREFIX/lib/{*.la,pkgconfig}

if [ $CROSS_VENV_SDK == "android" ]; then
    rm -r $PREFIX/lib/*.a
fi
