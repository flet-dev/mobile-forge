#!/bin/bash
# flet-libpq: PostgreSQL's libpq client library for the psycopg recipes. Ships:
#   - opt/lib/libpq.so                  shared lib for psycopg v3's ctypes loader
#   - opt/lib/libpq.a + libpgcommon.a + libpgport.a   static+PIC, for psycopg2
#                                       (compiled C-ext, static_libpq)
#   - opt/include/...                   headers for the psycopg2 compile
#   - opt/bin/pg_config                 relocatable shim psycopg2's setup.py queries
# TLS via the support-tree OpenSSL ($OPENSSL_DIR).
set -eu

NAME=pq
SRCROOT="$PWD"

# Point configure at the support-tree OpenSSL for TLS (libpq's --with-openssl).
export CPPFLAGS="${CPPFLAGS:-} -I$OPENSSL_DIR/include"
export LDFLAGS="${LDFLAGS:-} -L$OPENSSL_DIR/lib"

# -fPIC so the static .a objects fold cleanly into psycopg2's _psycopg.so.
export CFLAGS="${CFLAGS:-} -fPIC"
common_args="\
    --without-readline \
    --without-zlib \
    --without-zstd \
    --without-lz4 \
    --without-icu \
    --without-gssapi \
    --with-openssl"

build_libpq() {
    # Build libpq + its in-tree deps without the server. generated-headers runs
    # host perl/sed to emit errcodes.h etc. (libpgcommon needs them).
    make -C src/backend generated-headers
    make -C src/common  -j "$CPU_COUNT"
    make -C src/port    -j "$CPU_COUNT"
    # all-lib builds the static + shared libpq but skips libpq-refs-stamp, the
    # "libpq must not call exit()" sanity check. It false-positives on darwin/iOS
    # (_atexit is a normal undefined import from libSystem; the check greps
    # GNU-nm-style output). Pre-touch the stamp so `make install` sees it done.
    make -C src/interfaces/libpq -j "$CPU_COUNT" all-lib
    touch src/interfaces/libpq/libpq-refs-stamp
    make -C src/interfaces/libpq install
    make -C src/include install   # libpq-fe.h, postgres_ext.h, pg_config*.h, ...

    # psycopg2 (static_libpq) links libpq.a, which references symbols from
    # libpgcommon/libpgport. libpq.a uses the PLAIN symbol names, which live in
    # the *_shlib.a* variants (PostgreSQL namespaces the non-shlib archives'
    # internals with a _private suffix); the _shlib archives are also PIC, so
    # they fold cleanly into _psycopg.so. Ship those, renamed.
    cp "$SRCROOT/src/common/libpgcommon_shlib.a" "$PREFIX/lib/libpgcommon.a"
    cp "$SRCROOT/src/port/libpgport_shlib.a"     "$PREFIX/lib/libpgport.a"
}

if [ "$CROSS_VENV_SDK" = "android" ]; then
    # Android bionic only declares nl_langinfo() at API >= 26; we target API 24,
    # so its declaration is hidden and chklocale.c hits an implicit-declaration
    # (int-to-pointer) error under clang 18. Tell configure langinfo.h is absent
    # so libpq falls back to its non-langinfo encoding detection.
    ac_cv_header_langinfo_h=no \
        ./configure --host=$HOST_TRIPLET --prefix=$PREFIX $common_args
    build_libpq

    # Collapse the versioned .so + symlinks into a single unversioned libpq.so
    # (Android extracts only files literally matching lib*.so; psycopg dlopens
    # "libpq.so" by name).
    cd "$PREFIX/lib"
    real=$(readlink -f "lib$NAME.so")
    tmp=$(mktemp); cp "$real" "$tmp"
    rm -f "lib$NAME.so" "lib$NAME.so".*
    mv "$tmp" "lib$NAME.so"; chmod 755 "lib$NAME.so"
    cd - >/dev/null
else
    # config.sub doesn't know Apple-mobile triplets — feed it an equivalent
    # Darwin triplet (CC/CFLAGS from forge do the real targeting).
    case $HOST_TRIPLET in
        arm64-apple-ios)            host=arm-apple-darwin23 ;;
        arm64-apple-ios-simulator)  host=aarch64-apple-darwin23 ;;
        x86_64-apple-ios-simulator) host=x86_64-apple-darwin23 ;;
        *) echo "Unknown iOS host triplet: $HOST_TRIPLET"; exit 1 ;;
    esac
    # forge's iOS CFLAGS/LDFLAGS embed framework search paths as -F "…" with
    # literal quotes. PostgreSQL bakes the configure-time flags into
    # config_info.c as C string literals (-DVAL_CFLAGS="…" etc.); the embedded
    # quotes terminate the string early, so the path components parse as bare
    # identifiers ("use of undeclared identifier 'Users'") and 3.12.13 as a
    # float. Strip the quotes — the forge paths contain no spaces, so -F path
    # still resolves.
    export CFLAGS="$(printf '%s' "$CFLAGS" | tr -d '"')"
    export CPPFLAGS="$(printf '%s' "$CPPFLAGS" | tr -d '"')"
    export LDFLAGS="$(printf '%s' "$LDFLAGS" | tr -d '"')"
    ./configure --host=$host --prefix=$PREFIX $common_args
    build_libpq

    # PostgreSQL's Makefile.shlib emits a versioned darwin dylib; normalize to a
    # single libpq.so the ctypes loader can dlopen.
    cd "$PREFIX/lib"
    real=$(ls lib$NAME.*.dylib lib$NAME.dylib 2>/dev/null | head -1)
    if [ -n "$real" ]; then
        cp "$real" "_tmp_lib$NAME"
        rm -f "lib$NAME"*.dylib "lib$NAME.so"
        mv "_tmp_lib$NAME" "lib$NAME.so"
        install_name_tool -id "@rpath/lib$NAME.so" "lib$NAME.so" 2>/dev/null || true
    fi
    cd - >/dev/null
fi

# pg_config shim: psycopg2's setup.py shells out to pg_config to locate libpq.
# The real cross-built pg_config is a target binary that can't run on the build
# host, so ship a relocatable shell shim that reports paths relative to itself
# (opt/bin/pg_config -> opt/include, opt/lib).
mkdir -p "$PREFIX/bin"
cat > "$PREFIX/bin/pg_config" <<'PGC'
#!/bin/sh
here=$(cd "$(dirname "$0")/.." && pwd)
case "$1" in
  --includedir)         echo "$here/include" ;;
  --includedir-server)  echo "$here/include/postgresql/server" ;;
  --libdir|--pkglibdir) echo "$here/lib" ;;
  --bindir)             echo "$here/bin" ;;
  --version)            echo "PostgreSQL 17.5" ;;
  --cppflags|--cflags|--cflags_sl|--ldflags|--ldflags_ex|--ldflags_sl|--libs) echo "" ;;
  *) echo "" ;;
esac
PGC
chmod 755 "$PREFIX/bin/pg_config"

# Keep opt/lib/{libpq.so,*.a}, opt/include, opt/bin/pg_config. Drop pkgconfig,
# libtool archives, versioned dylibs/sonames, and share/.
shopt -s nullglob
rm -rf "$PREFIX/share"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX"/lib/*.la
rm -f "$PREFIX"/lib/lib$NAME.dylib "$PREFIX"/lib/lib$NAME.*.dylib
