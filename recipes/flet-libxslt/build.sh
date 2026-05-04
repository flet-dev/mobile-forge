#!/bin/bash
set -eu

export CFLAGS="-Wno-error=incompatible-function-pointer-types"
export LIBS="-lxml2"

./configure --host=$HOST_TRIPLET --prefix=$PREFIX --without-crypto --without-python \
     --with-libxml-include-prefix=$PLATLIB/opt/include \
     --with-libxml-libs-prefix=$PLATLIB/opt/lib 
# Skip the xsltproc CLI / doc / tests subdirs: xsltproc links against
# libxml2 and on iOS the SDK's bundled libxml2.tbd predates 1.1.45's
# usage of xmlCtxtParseDocument / xmlXPathValuePush, so the binary
# fails to link. The wheel only needs the libraries.
make -j $CPU_COUNT V=1 SUBDIRS='libxslt libexslt'
make install SUBDIRS='libxslt libexslt'

shopt -s nullglob
rm -rf $PREFIX/share
rm -rf $PREFIX/lib/libxslt-* $PREFIX/lib/pkgconfig $PREFIX/lib/cmake $PREFIX/lib/*.la $PREFIX/lib/*.sh