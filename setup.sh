usage() {
    echo "Usage:"
    echo
    echo "    source $1 <python version>"
    echo
    echo "for example:"
    echo
    echo "    source $1 3.13"
    echo
}

# make sure the script is sourced
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "This script must be sourced."
    echo
    usage $0
    exit 1
fi

if [ -z "$1" ]; then
    echo "Python version is not provided."
    echo
    usage $0
    return
fi

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Install it with:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    return
fi

PYTHON_VERSION=$1
PYTHON_VER="${PYTHON_VERSION%.*}"
python_version_minor="${PYTHON_VER#*.}"

echo "Python version: $PYTHON_VERSION"
echo "Python short version: $PYTHON_VER"

# Per-version support-path overrides: MOBILE_FORGE_{IOS,ANDROID}_SUPPORT_PATH_<MAJOR>_<MINOR>
# (e.g. MOBILE_FORGE_IOS_SUPPORT_PATH_3_13). When set, they take precedence over
# the unversioned variable for this session, so .envrc can declare paths for
# 3.12 / 3.13 / 3.14 side-by-side and `source ./setup.sh <ver>` picks the right one.
versioned_suffix="${PYTHON_VER//./_}"
ios_versioned_var="MOBILE_FORGE_IOS_SUPPORT_PATH_${versioned_suffix}"
android_versioned_var="MOBILE_FORGE_ANDROID_SUPPORT_PATH_${versioned_suffix}"
if [ -n "${!ios_versioned_var}" ]; then
    export MOBILE_FORGE_IOS_SUPPORT_PATH="${!ios_versioned_var}"
fi
if [ -n "${!android_versioned_var}" ]; then
    export MOBILE_FORGE_ANDROID_SUPPORT_PATH="${!android_versioned_var}"
fi

if [[ -z "$MOBILE_FORGE_IOS_SUPPORT_PATH" && -z "$MOBILE_FORGE_ANDROID_SUPPORT_PATH" ]]; then
    echo "Neither MOBILE_FORGE_IOS_SUPPORT_PATH nor MOBILE_FORGE_ANDROID_SUPPORT_PATH are defined."
    echo "Set MOBILE_FORGE_{IOS,ANDROID}_SUPPORT_PATH or per-version overrides"
    echo "MOBILE_FORGE_{IOS,ANDROID}_SUPPORT_PATH_${versioned_suffix}."
    return
fi

venv_dir="$(pwd)/venv$PYTHON_VER"

if [ ! -d $venv_dir ]; then
    echo "Creating Python $PYTHON_VER virtual environment for build in $venv_dir..."

    uv venv --seed --python="$PYTHON_VERSION" $venv_dir
    source $venv_dir/bin/activate

    uv pip install -e .

    echo "Building platform dependency wheels..."
    if [ ! -z "$MOBILE_FORGE_IOS_SUPPORT_PATH" ]; then
        python -m make_dep_wheels iOS
        if [ $? -ne 0 ]; then
            return
        fi
    fi

    if [ ! -z "$MOBILE_FORGE_ANDROID_SUPPORT_PATH" ]; then
        python -m make_dep_wheels android
        if [ $? -ne 0 ]; then
            return
        fi
    fi

    echo "Python $PYTHON_VERSION environment has been created."
    echo
else
    echo "Using existing Python $PYTHON_VERSION environment."
    source $venv_dir/bin/activate
fi

# configure iOS paths
if [ ! -z "$MOBILE_FORGE_IOS_SUPPORT_PATH" ]; then

    if [ ! -d $MOBILE_FORGE_IOS_SUPPORT_PATH/support/$PYTHON_VER/iOS/Python.xcframework ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not point at a valid location."
        return
    fi

    if [ ! -e $MOBILE_FORGE_IOS_SUPPORT_PATH/support/$PYTHON_VER/iOS/Python.xcframework/ios-arm64/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION iOS ARM64 device binary."
        return
    fi

    if [ ! -e $MOBILE_FORGE_IOS_SUPPORT_PATH/support/$PYTHON_VER/iOS/Python.xcframework/ios-arm64_x86_64-simulator/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION iOS ARM64/x86_64 simulator binaries."
        return
    fi

    echo "MOBILE_FORGE_IOS_SUPPORT_PATH: $MOBILE_FORGE_IOS_SUPPORT_PATH"
fi

# configure Android paths
if [ ! -z "$MOBILE_FORGE_ANDROID_SUPPORT_PATH" ]; then
    if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/arm64-v8a/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android arm64-v8a device binary."
        return
    fi

    if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/x86_64/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android x86_64 device binary."
        return
    fi

    if [ "$python_version_minor" -lt 13 ]; then
        if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/armeabi-v7a/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
            echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android armeabi-v7a device binary."
            return
        fi

        if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/x86/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
            echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android x86 device binary."
            return
        fi
    fi

    echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH: $MOBILE_FORGE_ANDROID_SUPPORT_PATH"
fi

echo
echo "You can now build packages with forge; e.g.:"
echo
echo "Build all packages for all iOS targets:"
echo "   forge iOS"
echo
echo "Build only the non-python packages, for all iOS targets:"
echo "   forge iOS -s non-py"
echo
echo "Build all packages needed for a smoke test, for all iOS targets:"
echo "   forge iOS -s smoke"
echo
echo "Build lru-dict for all iOS targets:"
echo "   forge iOS lru-dict"
echo
echo "Build lru-dict for the ARM64 device target:"
echo "   forge iphoneos:arm64 lru-dict"
echo
echo "Build all applicable versions of lru-dict for all iOS targets:"
echo "   forge iOS --all-versions lru-dict"
echo
