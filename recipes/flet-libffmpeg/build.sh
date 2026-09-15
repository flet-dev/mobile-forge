#!/bin/bash
# flet-libffmpeg: FFmpeg's seven libav* libraries, built SHARED, for the `av`
# (PyAV) recipe. PyAV compiles 49 Cython extension modules against them and
# refuses a static FFmpeg outright ("Building PyAV against static FFmpeg
# libraries is not supported" — setup.py), so shared is the only shape that
# works; it is also the only one that doesn't fold a copy of libavcodec into
# each of those 49 modules.
#
# Delivery mirrors flet-libarrow -> pyarrow, the proven linked-consumer chain:
#   Android: opt/lib/lib<name>.so, unversioned, SONAME == filename. FFmpeg's
#            own `android` target already emits exactly that (configure:6040).
#            serious_python copies them into the APK's jniLibs, where the
#            consumer's DT_NEEDED resolves them by basename.
#   iOS:     opt/lib/lib<name>.dylib, unversioned, install-id @rpath/lib<name>.dylib.
#            flet turns each into a per-slice *.framework; a versioned dylib
#            plus its symlinks breaks that conversion (three files match the
#            lipo glob), hence the SLIBNAME_WITH_* overrides below.
#
# Licence-relevant: no --enable-gpl, no --enable-nonfree, no --enable-version3,
# and no external codec libraries. This is a plain LGPL-2.1-or-later FFmpeg.
set -eu

# FFmpeg's configure takes its whole toolchain through its own flags. forge's
# CC/CFLAGS/LDFLAGS are composed for autotools and CMake consumers (they carry
# Python include/lib paths, an -F "..." framework path with literal quotes on
# iOS, ...) and configure would fold them into every probe. Drive it explicitly.
unset CC CXX CFLAGS CPPFLAGS LDFLAGS AR RANLIB STRIP NM || true

COMMON_ARGS="
    --prefix=$PREFIX
    --libdir=$PREFIX/lib
    --incdir=$PREFIX/include
    --pkgconfigdir=$PREFIX/lib/pkgconfig
    --enable-cross-compile
    --enable-shared
    --disable-static
    --enable-pic
    --disable-programs
    --disable-doc
    --disable-debug
    --disable-devices
    --disable-autodetect
    --disable-iconv
    --enable-zlib
"
# --disable-autodetect is the deterministic switch: it turns off every library
#   FFmpeg would otherwise probe for on the build host or in the SDK, so the
#   same source produces the same feature set on a laptop and in CI. It also
#   takes the hardware-accel list with it (videotoolbox/audiotoolbox on iOS,
#   v4l2-m2m and vulkan on Android) — none of which a Flet app can drive today
#   without a JavaVM handle or a Metal/VT session, and all of which would make
#   the two platforms diverge.
# --enable-zlib is then re-requested explicitly: both the NDK sysroot and the
#   iOS SDK ship libz, several codecs and the Matroska demuxer want it, and an
#   explicit --enable- turns "not found" into a hard configure failure instead
#   of a silently reduced build.
# --disable-iconv keeps the two platforms symmetric: Android's bionic has no
#   iconv before API 28, iOS has one, and the only thing that turns on is
#   subtitle charset conversion (`sub_charenc`).
# --disable-devices drops libavdevice's in/out devices (v4l2, AVFoundation).
#   libavdevice itself still builds — PyAV links it and calls
#   avdevice_register_all() — it just registers nothing.

if [ "$CROSS_VENV_SDK" = "android" ]; then
    TOOLCHAIN_BIN="$(echo "$NDK_ROOT"/toolchains/llvm/prebuilt/*/bin)"
    [ -d "$TOOLCHAIN_BIN" ] || { echo "ERROR: no NDK toolchain under $NDK_ROOT"; exit 1; }

    # FFmpeg names architectures its own way, and the NDK's clang driver is
    # named after the *compiler* triplet, which for 32-bit ARM is armv7a-...
    # and not the armeabi/arm-linux-androideabi forms used elsewhere.
    EXTRA_ARGS=""
    case "$ANDROID_ABI" in
        arm64-v8a)   FF_ARCH=aarch64; FF_CPU=armv8-a; CC_TRIPLET=aarch64-linux-android ;;
        armeabi-v7a) FF_ARCH=arm;     FF_CPU=armv7-a; CC_TRIPLET=armv7a-linux-androideabi
                     EXTRA_ARGS="--enable-thumb" ;;
        x86_64)      FF_ARCH=x86_64;  FF_CPU=x86-64;  CC_TRIPLET=x86_64-linux-android
                     EXTRA_ARGS="--disable-x86asm" ;;
        x86)         FF_ARCH=x86;     FF_CPU=i686;    CC_TRIPLET=i686-linux-android
                     EXTRA_ARGS="--disable-x86asm" ;;
        *) echo "ERROR: unhandled ANDROID_ABI $ANDROID_ABI"; exit 1 ;;
    esac

    echo "=== configure (android $ANDROID_ABI, arch $FF_ARCH) ==="
    ./configure $COMMON_ARGS $EXTRA_ARGS \
        --target-os=android \
        --arch="$FF_ARCH" \
        --cpu="$FF_CPU" \
        --sysroot="$TOOLCHAIN_BIN/../sysroot" \
        --cc="$TOOLCHAIN_BIN/${CC_TRIPLET}${ANDROID_API_LEVEL}-clang" \
        --cxx="$TOOLCHAIN_BIN/${CC_TRIPLET}${ANDROID_API_LEVEL}-clang++" \
        --ar="$TOOLCHAIN_BIN/llvm-ar" \
        --nm="$TOOLCHAIN_BIN/llvm-nm" \
        --ranlib="$TOOLCHAIN_BIN/llvm-ranlib" \
        --strip="$TOOLCHAIN_BIN/llvm-strip" \
        --extra-ldflags="-Wl,-z,max-page-size=16384"

    echo "=== build + install ==="
    make -j "${CPU_COUNT:-4}"
    make install
else
    # One clang -target triple carries arch, platform, minimum version and the
    # simulator marker; passing them as separate -arch/-mios-*-version-min flags
    # is what gets an arm64 simulator slice built as a device slice.
    case "$CROSS_VENV_SDK" in
        iphoneos)        TARGET_TRIPLET="${HOST_ARCH}-apple-ios${SDK_VERSION}" ;;
        iphonesimulator) TARGET_TRIPLET="${HOST_ARCH}-apple-ios${SDK_VERSION}-simulator" ;;
        *) echo "ERROR: unhandled SDK $CROSS_VENV_SDK"; exit 1 ;;
    esac

    # No nasm/yasm is guaranteed on a macOS build host or CI runner, and the
    # x86_64 slices only ever run in the Simulator.
    EXTRA_ARGS=""
    [ "$HOST_ARCH" = "x86_64" ] && EXTRA_ARGS="--disable-x86asm"

    echo "=== configure (iOS $HOST_ARCH, $TARGET_TRIPLET) ==="
    ./configure $COMMON_ARGS $EXTRA_ARGS \
        --target-os=darwin \
        --arch="$HOST_ARCH" \
        --cc="$(xcrun -sdk "$CROSS_VENV_SDK" -f clang)" \
        --cxx="$(xcrun -sdk "$CROSS_VENV_SDK" -f clang++)" \
        --extra-cflags="-target $TARGET_TRIPLET -isysroot $SDK_ROOT" \
        --extra-ldflags="-target $TARGET_TRIPLET -isysroot $SDK_ROOT -Wl,-headerpad_max_install_names" \
        --install-name-dir=@rpath

    # -headerpad_max_install_names is load-bearing, not hygiene: flet renames each
    # of these into a framework and rewrites every install name to the much longer
    # @rpath/opt.lib.lib<name>.framework/opt.lib.lib<name>. Without the padding
    # install_name_tool fails with "larger updated load commands do not fit", which
    # aborts serious_python's reconcile pass — and the app is then built with NO
    # site-packages at all rather than failing outright.
    #
    # Collapse Darwin's versioned dylib triplet (libavcodec.62.1.100.dylib plus
    # two symlinks) to a single unversioned libavcodec.dylib. SHFLAGS embeds
    # $(SLIBNAME_WITH_MAJOR) as the install name, so overriding it here also
    # makes the install-id @rpath/libavcodec.dylib — which is what the `av`
    # extension modules record, and what flet's framework relocation rewrites.
    # Command-line make variables beat the config.mak assignments.
    DEVERSION="SLIBNAME_WITH_VERSION=\$(SLIBNAME) SLIBNAME_WITH_MAJOR=\$(SLIBNAME)"

    echo "=== build + install ==="
    make -j "${CPU_COUNT:-4}" $DEVERSION
    make install $DEVERSION 'SLIB_INSTALL_NAME=$(SLIBNAME)' SLIB_INSTALL_LINKS=
fi

# The .pc files land with absolute paths into this build's staging directory —
# and FFmpeg writes libdir/includedir out in full rather than deriving them from
# ${prefix}, so all three lines need rewriting. The wheel unpacks somewhere else
# entirely, so put them in pkg-config's relocatable form: forge adds
# <site-packages>/opt/lib/pkgconfig to PKG_CONFIG_LIBDIR for consumers, and
# PyAV's setup.py finds FFmpeg *only* through pkg-config.
echo "=== relocate pkg-config prefixes ==="
for pc in "$PREFIX"/lib/pkgconfig/*.pc; do
    [ -f "$pc" ] || continue
    sed -E -e 's|^prefix=.*|prefix=${pcfiledir}/../..|' \
           -e 's|^libdir=.*|libdir=${prefix}/lib|' \
           -e 's|^includedir=.*|includedir=${prefix}/include|' \
           "$pc" > "$pc.tmp" && mv "$pc.tmp" "$pc"
done

# FFmpeg's LGPL notice does not cover everything in the binary: libavcodec's
# jrevdct.c, jfdctfst.c and jfdctint_template.c come from the Independent JPEG
# Group, carry their own grant in a header comment rather than a separate file,
# and are all compiled in (the MJPEG codec pulls them). Extract that notice so
# the wheel ships it, taking it from the source being built rather than a copy
# checked into the recipe — a copy would drift silently on the next bump.
echo "=== extract the IJG notice ==="
{
    echo "The notice below covers libavcodec/jrevdct.c, libavcodec/jfdctfst.c and"
    echo "libavcodec/jfdctint_template.c, which FFmpeg takes from the Independent JPEG"
    echo "Group's software and compiles into libavcodec. It is the verbatim header of"
    echo "jrevdct.c; the other two carry the same terms under a different copyright year."
    echo
    echo "----------------------------------------------------------------------------"
    echo
    awk 'NR==1,/^ \*\/$/' libavcodec/jrevdct.c
} > COPYING.IJG
grep -q "Independent JPEG Group" COPYING.IJG || {
    echo "ERROR: no IJG notice in libavcodec/jrevdct.c — has upstream moved it?"; exit 1; }

# Nothing downstream consumes these, and .la files carry absolute build paths.
shopt -s nullglob
rm -rf "$PREFIX/share"
rm -f "$PREFIX"/lib/*.la

echo "=== installed ==="
ls -la "$PREFIX/lib"
