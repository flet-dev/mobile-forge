#!/bin/bash
set -eu

# --with-pic: build PIC objects so the static archives (libjq.a / libonig.a)
# can be linked into the jq Python extension, which is itself a shared object.
# The jq recipe static-links them (requirements.host_build + -l:libjq.a) so the
# extension is self-contained. This is deliberate: on Android the `jq` Python
# module mangles to jniLibs `libjq.so` — the SAME basename this library would
# ship — so a bundled libjq.so would collide with (and be clobbered by) the
# extension. Static-linking avoids shipping libjq.so at all.
./configure --host=$HOST_TRIPLET --prefix=$PREFIX --with-oniguruma=builtin --with-pic
make -j $CPU_COUNT
make install

rm -r $PREFIX/{bin,share}
rm -r $PREFIX/lib/{*.la,pkgconfig}
# Keep the static archives (libjq.a / libonig.a); drop the shared libraries so
# nothing can ship/relocate a colliding libjq.so at runtime.
rm -f $PREFIX/lib/*.so*
