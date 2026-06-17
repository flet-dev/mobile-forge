#!/bin/bash
# flet-libfreetds: FreeTDS (the TDS / SQL-Server protocol library) as a STATIC,
# PIC archive (libsybdb + libtds) that pymssql links into its _mssql C
# extension. TLS via the support-tree OpenSSL ($OPENSSL_DIR). iconv uses
# FreeTDS's built-in converter for now (--disable-libiconv).
set -eu

# Static archives folded into a C extension -> needs PIC.
export CFLAGS="${CFLAGS:-} -fPIC"

common_args="\
    --disable-dependency-tracking \
    --enable-static --disable-shared \
    --disable-odbc \
    --disable-libiconv \
    --with-openssl=$OPENSSL_DIR"

if [ "$CROSS_VENV_SDK" = "android" ]; then
    HOST=$HOST_TRIPLET
else
    # config.sub doesn't know Apple-mobile triplets — feed it an equivalent
    # Darwin triplet (CC/CFLAGS from forge do the real targeting).
    case $HOST_TRIPLET in
        arm64-apple-ios)            HOST=arm-apple-darwin23 ;;
        arm64-apple-ios-simulator)  HOST=aarch64-apple-darwin23 ;;
        x86_64-apple-ios-simulator) HOST=x86_64-apple-darwin23 ;;
        *) echo "Unknown iOS host triplet: $HOST_TRIPLET"; exit 1 ;;
    esac
fi

./configure --host=$HOST --prefix=$PREFIX $common_args
make -j "$CPU_COUNT"
make install

# Keep opt/include + opt/lib/*.a (pymssql links the static libs); drop the rest.
shopt -s nullglob
rm -rf "$PREFIX/bin" "$PREFIX/share"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la "$PREFIX"/lib/*.so*
