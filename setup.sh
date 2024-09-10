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

PYTHON_URL_PREFIX=https://github.com/indygreg/python-build-standalone/releases/download/20240415/cpython-3.12.3+20240415

PYTHON_VERSION=$1
read python_version_major python_version_minor < <(echo $PYTHON_VERSION | sed -E 's/^([0-9]+)\.([0-9]+).*/\1 \2/')
PYTHON_VER=$python_version_major.$python_version_minor
CMAKE_VERSION="3.27.4"

echo "Python version: $PYTHON_VERSION"
echo "Python short version: $PYTHON_VER"

if [[ -z "$MOBILE_FORGE_IOS_SUPPORT_PATH" && -z "$MOBILE_FORGE_ANDROID_SUPPORT_PATH" ]]; then
    echo "Neither MOBILE_FORGE_IOS_SUPPORT_PATH nor MOBILE_FORGE_ANDROID_SUPPORT_PATH are defined."
    return
fi

if [ ! -z "$VIRTUAL_ENV" ]; then
    deactivate
fi

venv_dir="$(pwd)/venv$PYTHON_VER"

if [ ! -d $venv_dir ]; then
    echo "Creating Python $PYTHON_VER virtual environment for build in $venv_dir..."

    # if ! [ -d "tools/python" ]; then
    #     if [ $(uname) = "Darwin" ]; then
    #         # macOS
    #         if [ $(uname -m) = "arm64" ]; then
    #             PYTHON_SUFFIX="aarch64-apple-darwin-install_only.tar.gz"
    #         else
    #             PYTHON_SUFFIX="x86_64-apple-darwin-install_only.tar.gz"
    #         fi
    #     else
    #         # Linux
    #         if [ $(uname -m) = "arm64" ]; then
    #             PYTHON_SUFFIX="aarch64-unknown-linux-gnu-install_only.tar.gz"
    #         else
    #             PYTHON_SUFFIX="x86_64_v3-unknown-linux-gnu-install_only.tar.gz"
    #         fi
    #     fi

    #     if ! [ -f "downloads/python-${PYTHON_VERSION}-${PYTHON_SUFFIX}" ]; then
    #         echo "Downloading Python ${PYTHON_VERSION}"
    #         mkdir -p downloads
    #         curl --location --progress-bar "${PYTHON_URL_PREFIX}-${PYTHON_SUFFIX}" --output "downloads/python-${PYTHON_VERSION}-${PYTHON_SUFFIX}"
    #     fi

    #     mkdir -p tools
    #     tar -xzf "downloads/python-${PYTHON_VERSION}-${PYTHON_SUFFIX}" -C tools
    # fi

    BUILD_PYTHON=$(which python$PYTHON_VER)
    if [ $? -ne 0 ]; then
        echo "Can't find a Python $PYTHON_VER binary on the path."
        return
    fi

    # tools/python/bin/python -m venv $venv_dir
    echo "Using $BUILD_PYTHON as the build python"
    $BUILD_PYTHON -m venv $venv_dir
    source $venv_dir/bin/activate

    pip install -U pip
    pip install -e . wheel

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

    if [ ! -d $MOBILE_FORGE_IOS_SUPPORT_PATH/install ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not point at a valid location."
        return
    fi

    if [ ! -e $MOBILE_FORGE_IOS_SUPPORT_PATH/install/iOS/arm64-apple-ios/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION iOS ARM64 device binary."
        return
    fi

    if [ ! -e $MOBILE_FORGE_IOS_SUPPORT_PATH/install/iOS/arm64-apple-ios-simulator/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION iOS ARM64 simulator binary."
        return
    fi

    if [ ! -e $MOBILE_FORGE_IOS_SUPPORT_PATH/install/iOS/x86_64-apple-ios-simulator/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION iOS x86-64 simulator binary."
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

    if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/armeabi-v7a/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android armeabi-v7a device binary."
        return
    fi

    if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/x86_64/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android x86_64 device binary."
        return
    fi

    if [ ! -e $MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/x86/python-$PYTHON_VERSION/bin/python$PYTHON_VER ]; then
        echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android x86 device binary."
        return
    fi

    echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH: $MOBILE_FORGE_ANDROID_SUPPORT_PATH"
fi

# Ensure CMake is installed
if [ $(uname) = "Darwin" ]; then
    if ! [ -d "tools/CMake.app" ]; then
        if ! [ -f "downloads/cmake-${CMAKE_VERSION}-macos-universal.tar.gz" ]; then
            echo "Downloading CMake"
            mkdir -p downloads
            curl --location --progress-bar "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-macos-universal.tar.gz" --output downloads/cmake-${CMAKE_VERSION}-macos-universal.tar.gz
        fi

        echo "Installing CMake"
        mkdir -p tools
        tar -xzf downloads/cmake-${CMAKE_VERSION}-macos-universal.tar.gz
        mv cmake-${CMAKE_VERSION}-macos-universal/CMake.app tools
        rm -rf cmake-${CMAKE_VERSION}-macos-universal
    fi
    export PATH="$PATH:$(pwd)/tools/CMake.app/Contents/bin"
else
    if ! [ -d "tools/cmake" ]; then
        if ! [ -f "downloads/cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz" ]; then
            echo "Downloading CMake"
            mkdir -p downloads
            curl --location --progress-bar "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz" --output downloads/cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz
        fi

        echo "Installing CMake"
        mkdir -p tools
        tar -xzf downloads/cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz
        mv cmake-${CMAKE_VERSION}-linux-x86_64/bin tools/cmake
        rm -rf cmake-${CMAKE_VERSION}-linux-x86_64
    fi
    export PATH="$PATH:$(pwd)/tools/cmake"
fi

# Create wheels for ninja that can be installed in the host environment
if ! [ -f "dist/ninja-1.11.1-py3-none-any.whl" ]; then
    echo "Downloading Ninja"
    python -m pip wheel --no-deps -w dist ninja==1.11.1
    mv dist/ninja-1.11.1-*.whl dist/ninja-1.11.1-py3-none-any.whl
fi

# Create wheels for cmake that can be installed in the host environment
if ! [ -f "dist/cmake-3.29.6-py3-none-any.whl" ]; then
    echo "Downloading CMake"
    python -m pip wheel --no-deps -w dist cmake==3.29.6
    mv dist/cmake-3.29.6-*.whl dist/cmake-3.29.6-py3-none-any.whl
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