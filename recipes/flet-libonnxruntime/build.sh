#!/bin/bash
set -eu

# Stage onnxruntime into $PREFIX/{lib,include} for consumers that link it at
# build time (sherpa-onnx reads SHERPA_ONNXRUNTIME_{INCLUDE,LIB}_DIR).
#   Android: the shared libonnxruntime.so; the consumer ships it in its wheel.
#   iOS: a static archive, normalized to libonnxruntime.a; the consumer links
#        it in, so nothing is bundled or loaded at runtime.

mkdir -p "$PREFIX/lib" "$PREFIX/include"

case "$CROSS_VENV_SDK" in
  android)
    SO="jni/$ANDROID_ABI/libonnxruntime.so"
    if [ ! -f "$SO" ]; then
        echo "flet-libonnxruntime: no $SO in the zip"
        exit 1
    fi
    cp "$SO" "$PREFIX/lib/"
    cp headers/*.h "$PREFIX/include/"
    ;;
  iphoneos|iphonesimulator)
    if [ "$CROSS_VENV_SDK" = "iphoneos" ]; then
        SLICE=ios-arm64
    else
        SLICE=ios-arm64_x86_64-simulator
    fi
    FRAMEWORK="onnxruntime.xcframework/$SLICE/onnxruntime.framework"
    if [ ! -f "$FRAMEWORK/onnxruntime" ]; then
        echo "flet-libonnxruntime: no $FRAMEWORK/onnxruntime in the zip"
        exit 1
    fi
    # The simulator archive is fat (arm64 + x86_64); keep only this slice's
    # arch so the consumer links what its wheel tag claims.
    if lipo -info "$FRAMEWORK/onnxruntime" | grep -q "Non-fat"; then
        cp "$FRAMEWORK/onnxruntime" "$PREFIX/lib/libonnxruntime.a"
    else
        lipo -thin "$HOST_ARCH" "$FRAMEWORK/onnxruntime" -output "$PREFIX/lib/libonnxruntime.a"
    fi
    cp "$FRAMEWORK/Headers/"*.h "$PREFIX/include/"
    ;;
  *)
    echo "flet-libonnxruntime: unsupported SDK '$CROSS_VENV_SDK'"
    exit 1
    ;;
esac
