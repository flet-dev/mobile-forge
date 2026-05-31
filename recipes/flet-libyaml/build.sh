#!/bin/bash
set -eu

if [ $CROSS_VENV_SDK != "android" ]; then
    case $HOST_TRIPLET in
        arm64-apple-ios)
            HOST_TRIPLET=arm-apple-darwin23
            ;;
        arm64-apple-ios-simulator)
            HOST_TRIPLET=aarch64-apple-darwin23
            ;;
        x86_64-apple-ios-simulator)
            HOST_TRIPLET=x86_64-apple-darwin23
            ;;
        *)
            echo "Unknown host triplet: '$HOST_TRIPLET'"
            exit 1
            ;;
    esac
fi

# On Android we want libyaml as a shared library — pyyaml's `_yaml.so` links
# against it dynamically and forge ships `libyaml.so` in `opt/lib/`.
# On iOS we additionally need the static archive (`libyaml.a`) so pyyaml's
# `-lyaml` resolves at link time. iOS pyyaml statically links libyaml into
# `_yaml.cpython-*.so`, mirroring how PyNaCl statically links libsodium via
# the `libsodium.a` that flet-libsodium ships in `opt/lib/`.
if [ $CROSS_VENV_SDK == "android" ]; then
    ./configure --host=$HOST_TRIPLET --prefix=$PREFIX --disable-static
else
    ./configure --host=$HOST_TRIPLET --prefix=$PREFIX
fi

# Rewrite libyaml_la_LDFLAGS to drop libtool's library-versioning flags and to
# work around forge's `-F "<framework>"` quoting on iOS:
#
#  - Default flags are `-no-undefined -release $(YAML_LT_RELEASE) -version-info $(YAML_LT_CURRENT):$(YAML_LT_REVISION):$(YAML_LT_AGE)`.
#    `-release` + `-version-info` make libtool produce a versioned dylib
#    (`libyaml-0.2.dylib` / `libyaml-0.so`). On Android that forced PyYAML's
#    `-lyaml` to need a separate `libyaml.so → libyaml-0.so` shim; on iOS the
#    versioned install_name path doesn't exist yet at link time and clang dies.
#    `-avoid-version` makes libtool skip versioning entirely → plain
#    `libyaml.so` / `libyaml.dylib` with matching soname/install_name.
#  - `-pthread` is benign filler. forge injects `-F "<Python.xcframework slice>"`
#    into LDFLAGS for iOS, but libtool re-emits it as bare `-F   ` (empty
#    arg) — clang then consumes the NEXT token as the framework path. With
#    no filler, that next token is `-install_name` and the install_name flag
#    silently disappears, dropping clang into "treat /path/libyaml.dylib as a
#    source file" mode → "no such file or directory". libsodium happens to
#    have `-pthread` in this slot from its own LDFLAGS, which is why
#    libsodium builds cleanly; we add it here for the same reason.
sed -i.bak 's/^\(libyaml_la_LDFLAGS *=\).*$/\1 -no-undefined -avoid-version -pthread/' src/Makefile
rm src/Makefile.bak

make -j $CPU_COUNT
make install

rm -r $PREFIX/lib/{*.la,pkgconfig}

if [ $CROSS_VENV_SDK != "android" ]; then
    mv $PREFIX/lib/libyaml.dylib $PREFIX/../libyaml.so
fi
