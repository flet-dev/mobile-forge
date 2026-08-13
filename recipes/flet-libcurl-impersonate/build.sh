#!/bin/bash
set -eu

# Stage the prebuilt curl-impersonate static mega-archive + headers so the
# curl-cffi recipe can statically link it. curl-cffi's ffibuilder expects a
# single "libdir" that contains both libcurl-impersonate.a and an include/curl/
# subtree; it points IMPERSONATE_BUILD_DIR at {platlib}/opt, so lay the files out
# exactly that way (the .a directly under opt/, headers under opt/include/).
#
# source.strip=0 left the archive's root-level files in place, and each upstream
# tarball is already thin for its slice (arm64 device, arm64/x86_64 simulator,
# aarch64/x86_64 android — all verified single-arch), so no lipo/thinning here.
# Nothing is shipped to the device: this wheel is a host_build (link-time) dep.

if [ ! -f libcurl-impersonate.a ]; then
    echo "flet-libcurl-impersonate: libcurl-impersonate.a not found after unpack" >&2
    ls -la >&2
    exit 1
fi
if [ ! -d include/curl ]; then
    echo "flet-libcurl-impersonate: include/curl/ not found after unpack" >&2
    ls -la >&2
    exit 1
fi

mkdir -p "$PREFIX"
cp libcurl-impersonate.a "$PREFIX/libcurl-impersonate.a"
cp -R include "$PREFIX/include"
