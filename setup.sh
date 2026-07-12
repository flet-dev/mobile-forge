usage() {
    echo "Usage:"
    echo
    echo "    source $1 <python version>"
    echo
    echo "<python version> may be a minor (3.13) or full (3.13.14) version;"
    echo "a minor is resolved to the patch from the pinned python-build release."
    echo "for example:"
    echo
    echo "    source $1 3.13"
    echo "    source $1 3.13.14"
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

# Pinned flet-dev/python-build release to consume (date-keyed YYYYMMDD, PBS-style).
PYTHON_BUILD_RELEASE="${PYTHON_BUILD_RELEASE:-20260712}"

# Resolve a full X.Y.Z from a bare X.Y minor using the pinned release's
# manifest.json (downloaded + cached under downloads/). Echoes the full version;
# returns non-zero (with a message on stderr) if the fetch or lookup fails.
resolve_full_version() {
    local minor="$1"
    local mf="downloads/python-build-manifest-${PYTHON_BUILD_RELEASE}.json"
    local murl="https://github.com/flet-dev/python-build/releases/download/${PYTHON_BUILD_RELEASE}/manifest.json"

    mkdir -p downloads
    if [ ! -f "$mf" ]; then
        if ! curl -fsSL -o "$mf" "$murl"; then
            echo "Failed to fetch python-build manifest ($murl)." >&2
            rm -f "$mf"
            return 1
        fi
    fi

    # Prefer jq, then python3; fall back to a scoped sed/grep over the (tiny,
    # stable-shape) manifest so this works on a bare machine with neither.
    local full=""
    if command -v jq >/dev/null 2>&1; then
        full="$(jq -r --arg m "$minor" '.pythons[$m].full_version // empty' "$mf" 2>/dev/null)"
    elif command -v python3 >/dev/null 2>&1; then
        full="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("pythons",{}).get(sys.argv[2],{}).get("full_version",""))' "$mf" "$minor" 2>/dev/null)"
    else
        # Match the minor literally in the sed range: a bare `.` is a regex
        # wildcard, so escape each dot to `[.]` (e.g. 3.13 -> 3[.]13).
        local minor_re="${minor//./[.]}"
        full="$(sed -n "/\"$minor_re\"[[:space:]]*:/,/}/p" "$mf" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9]*' | head -1)"
    fi

    if [ -z "$full" ]; then
        echo "python-build release ${PYTHON_BUILD_RELEASE} has no Python ${minor} in its manifest." >&2
        return 1
    fi
    echo "$full"
}

# Echo the space-separated Android ABI set for a bare X.Y minor, read from the same
# pinned python-build release manifest. Returns non-zero (empty) if the fetch or lookup fails.
resolve_android_abis() {
    local minor="$1"
    local mf="downloads/python-build-manifest-${PYTHON_BUILD_RELEASE}.json"
    local murl="https://github.com/flet-dev/python-build/releases/download/${PYTHON_BUILD_RELEASE}/manifest.json"

    mkdir -p downloads
    if [ ! -f "$mf" ]; then
        if ! curl -fsSL -o "$mf" "$murl"; then
            echo "Failed to fetch python-build manifest ($murl)." >&2
            rm -f "$mf"
            return 1
        fi
    fi

    local abis=""
    if command -v jq >/dev/null 2>&1; then
        abis="$(jq -r --arg m "$minor" '.pythons[$m].android_abis // [] | join(" ")' "$mf" 2>/dev/null)"
    elif command -v python3 >/dev/null 2>&1; then
        abis="$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1])).get("pythons",{}).get(sys.argv[2],{}).get("android_abis",[])))' "$mf" "$minor" 2>/dev/null)"
    else
        # Scope to the minor's block, then to the android_abis array, and collect the
        # quoted ABI tokens (dropping the "android_abis" key token itself).
        local minor_re="${minor//./[.]}"
        abis="$(sed -n "/\"$minor_re\"[[:space:]]*:/,/}/p" "$mf" \
            | sed -n '/"android_abis"/,/]/p' \
            | grep -oE '"[a-z0-9_-]+"' | tr -d '"' \
            | grep -vx 'android_abis' | tr '\n' ' ')"
    fi

    [ -n "$abis" ] || return 1
    # Trim trailing whitespace.
    echo "$abis" | xargs
}

# Accept either a full X.Y.Z or a bare X.Y minor as $1. Derive the X.Y minor either
# way (cut handles both forms); when only the minor is given, resolve the patch from
# the pinned release's manifest. A full version is taken as-is (works offline and for
# the PYTHON_BUILD_RUN_ID path, which may build versions other than the pinned set).
PYTHON_INPUT="$1"
PYTHON_VER="$(echo "$PYTHON_INPUT" | cut -d. -f1-2)"
python_version_minor="${PYTHON_VER#*.}"

if echo "$PYTHON_INPUT" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]'; then
    PYTHON_VERSION="$PYTHON_INPUT"
else
    echo "Resolving Python $PYTHON_VER from python-build release $PYTHON_BUILD_RELEASE..."
    PYTHON_VERSION="$(resolve_full_version "$PYTHON_VER")" || return
fi

echo "Python version: $PYTHON_VERSION"
echo "Python short version: $PYTHON_VER"
echo "python-build release: $PYTHON_BUILD_RELEASE"

# Android ABI set for this minor, from the python-build manifest.
# Overridable by setting ANDROID_ABIS env var.
ANDROID_ABIS="${ANDROID_ABIS:-$(resolve_android_abis "$PYTHON_VER")}"
if [ -z "$ANDROID_ABIS" ]; then
    ANDROID_ABIS="arm64-v8a x86_64 armeabi-v7a"
    echo "Warning: manifest has no android_abis for $PYTHON_VER; defaulting to: $ANDROID_ABIS" >&2
fi
export ANDROID_ABIS
echo "Android ABIs: $ANDROID_ABIS"

# Download (and cache) a mobile-forge Python support package, extracting it
# into $2. Source is either the pinned date-keyed ($PYTHON_BUILD_RELEASE) release
# on flet-dev/python-build, or a specific Actions run's artifacts when
# $PYTHON_BUILD_RUN_ID is set (used in CI to validate unreleased
# python-build branches against the recipe matrix). Tarballs are cached
# under downloads/ (gitignored) and reused on subsequent runs.
#
# Reads from caller env:
#   PYTHON_BUILD_RUN_ID  — empty for release URL; non-empty for `gh run download`
#                          (requires `gh` installed and a GITHUB_TOKEN / login)
download_support() {
    local plat="$1" dest="$2"
    local tarball="python-${plat}-mobile-forge-${PYTHON_VERSION}.tar.gz"

    if [ -d "$dest/support" ]; then
        return 0
    fi

    mkdir -p downloads
    if [ ! -f "downloads/${tarball}" ]; then
        if [ -n "${PYTHON_BUILD_RUN_ID:-}" ]; then
            # python-build's CI uploads iOS tarballs under the "darwin" artifact
            # (it bundles iOS + macOS together). The android lane has a 1:1 artifact name.
            local artifact_plat="$plat"
            [ "$plat" = "ios" ] && artifact_plat="darwin"
            local artifact_name="python-${artifact_plat}-${PYTHON_VERSION}"

            echo "Fetching ${tarball} from python-build run ${PYTHON_BUILD_RUN_ID} (artifact: ${artifact_name})..."
            local stage
            stage="$(mktemp -d)"
            if ! gh run download "$PYTHON_BUILD_RUN_ID" \
                    --repo flet-dev/python-build \
                    --name "$artifact_name" \
                    --dir "$stage"; then
                echo "Failed to download artifact ${artifact_name} from run ${PYTHON_BUILD_RUN_ID}"
                rm -rf "$stage"
                return 1
            fi
            mv "$stage/${tarball}" "downloads/${tarball}"
            # Keep the on-device Python runtime tarballs (python-{android,ios}-dart-*)
            # from the same artifact. serious_python normally downloads these from a
            # hardcoded flet-dev/python-build RELEASE; keeping them here lets the
            # recipe-tester step seed serious_python's cache with THIS run's runtime,
            # so `flet build` validates an unreleased runtime fix (no release needed).
            cp "$stage"/python-*-dart-*.tar.gz "downloads/" 2>/dev/null || true
            rm -rf "$stage"
        else
            local url="https://github.com/flet-dev/python-build/releases/download/${PYTHON_BUILD_RELEASE}/${tarball}"
            echo "Downloading ${tarball}..."
            if ! curl -fL -o "downloads/${tarball}" "$url"; then
                echo "Failed to download ${url}"
                rm -f "downloads/${tarball}"
                return 1
            fi
        fi
    fi

    echo "Extracting ${tarball} into ${dest}..."
    mkdir -p "$dest"
    tar -xzf "downloads/${tarball}" -C "$dest"

    # Rewrite the `prefix=` line in every shipped `lib/pkgconfig/*.pc` to pkg-config's relocatable
    # form `prefix=${pcfiledir}/../..` so consumer pkg-config invocations resolve include/lib paths to the actual
    # on-disk install root, NOT the build-time `/usr/local` autoconf default that CPython bakes in. Without
    # this, meson's `py.dependency()` gets `-I/usr/local/include/python3.X` (a path that does not exist on
    # the CI runner) and reports the Python dep as "not found" — surfaced by numpy 2.4.6 on Python 3.14 Android.
    relocate_pkgconfig_prefix "$dest"
}

# Walk every `.pc` file under <dest>/.../lib/pkgconfig/ and rewrite the (literal absolute-path) `prefix=`
# line to pkg-config's standard relocatable `prefix=${pcfiledir}/../..`. Idempotent — if the line is
# already in the relocatable form, the sed substitution silently leaves the file alone. Safe to call
# across versions/platforms; the find prunes to pkgconfig dirs explicitly.
relocate_pkgconfig_prefix() {
    local dest="$1"
    # Find every lib/pkgconfig dir under the extracted tree. CPython ships .pc files under
    # <install>/<abi>/python-<ver>/lib/pkgconfig on Android and under <Python.xcframework>/<slice>/lib/pkgconfig on iOS.
    find "$dest" -type d -name pkgconfig 2>/dev/null | while read -r pcdir; do
        # `prefix=${pcfiledir}/../..` -- pkg-config/pkgconf substitutes ${pcfiledir} with the .pc
        # file's actual directory at lookup time. <dir>/../.. on a .pc at <install>/lib/pkgconfig/*.pc
        # resolves to <install> -- the consumer's real install prefix.
        #
        # Also substitute `$(BLDLIBRARY)` in the Libs: line. CPython's autoconf-built python-X.Y.pc
        # ships `Libs: -L${libdir} $(BLDLIBRARY)` -- the `$(BLDLIBRARY)` is supposed to expand to `-lpython3.X`
        # at install time but never does, and pkg-config passes the literal through to the linker which then
        # fails with `clang++: error: no such file or directory: '$(BLDLIBRARY)'`. Only the python-X.Y.pc files
        # are affected; python-X.Y-embed.pc already has `-lpythonX.Y` written directly. We fix both
        # idempotently by rewriting `$(BLDLIBRARY)` -> `-lpython${ver}` where ver is derived from the .pc filename.
        for pc in "$pcdir"/*.pc; do
            [ -f "$pc" ] || continue
            # macOS sed doesn't have -i without an extension arg; use a portable in-place edit via a temp file.
            local tmp
            tmp="$(mktemp)"
            sed -E 's|^prefix=.*|prefix=${pcfiledir}/../..|' "$pc" > "$tmp" && mv "$tmp" "$pc"

            # If this is a python-X.Y.pc (not the -embed variant or some other recipe-shipped .pc), substitute
            # $(BLDLIBRARY) with the matching -lpythonX.Y.
            local base
            base="$(basename "$pc")"
            if [[ "$base" =~ ^python-([0-9]+\.[0-9]+)\.pc$ ]]; then
                local ver="${BASH_REMATCH[1]}"
                tmp="$(mktemp)"
                sed -E 's|\$\(BLDLIBRARY\)|-lpython'"$ver"'|g' "$pc" > "$tmp" && mv "$tmp" "$pc"
            fi
        done
    done
}

# Echo the directory that actually contains the support/ tree: $1 itself, or a
# single wrapper subdirectory if the tarball ships one.
resolve_support_root() {
    local d="$1"
    if [ -d "$d/support" ]; then
        echo "$d"
        return
    fi
    local sub
    for sub in "$d"/*/; do
        if [ -d "${sub}support" ]; then
            echo "${sub%/}"
            return
        fi
    done
    echo "$d"
}

# Default-initialize so the script is safe under `set -u` even when the caller
# (e.g. CI) hasn't exported these. Real values are filled in below.
export MOBILE_FORGE_IOS_SUPPORT_PATH="${MOBILE_FORGE_IOS_SUPPORT_PATH:-}"
export MOBILE_FORGE_ANDROID_SUPPORT_PATH="${MOBILE_FORGE_ANDROID_SUPPORT_PATH:-}"

# Per-version support-path overrides: MOBILE_FORGE_{IOS,ANDROID}_SUPPORT_PATH_<MAJOR>_<MINOR>
# (e.g. MOBILE_FORGE_IOS_SUPPORT_PATH_3_13). When set, they take precedence over
# the unversioned variable for this session, so .envrc can declare paths for
# 3.12 / 3.13 / 3.14 side-by-side and `source ./setup.sh <ver>` picks the right one.
versioned_suffix="${PYTHON_VER//./_}"
ios_versioned_var="MOBILE_FORGE_IOS_SUPPORT_PATH_${versioned_suffix}"
android_versioned_var="MOBILE_FORGE_ANDROID_SUPPORT_PATH_${versioned_suffix}"
# Indirect variable expansion: bash uses ${!var}, zsh uses ${(P)var}.
# `eval` is the portable form that works in both.
eval "ios_versioned_val=\${$ios_versioned_var:-}"
eval "android_versioned_val=\${$android_versioned_var:-}"
if [ -n "$ios_versioned_val" ]; then
    export MOBILE_FORGE_IOS_SUPPORT_PATH="$ios_versioned_val"
fi
if [ -n "$android_versioned_val" ]; then
    export MOBILE_FORGE_ANDROID_SUPPORT_PATH="$android_versioned_val"
fi

# Platforms with an explicit (possibly versioned) path are user-managed and
# authoritative — validate them as-is, never auto-download.
explicit=""
[ -n "$MOBILE_FORGE_IOS_SUPPORT_PATH" ]     && explicit="$explicit iOS"
[ -n "$MOBILE_FORGE_ANDROID_SUPPORT_PATH" ] && explicit="$explicit android"

if [ -z "$explicit" ]; then
    # Auto-download selection: 2nd arg, then $MOBILE_FORGE_PLATFORMS, then OS default.
    platforms="${2:-${MOBILE_FORGE_PLATFORMS:-}}"
    if [ -z "$platforms" ]; then
        [ "$(uname)" = "Darwin" ] && platforms="iOS android" || platforms="android"
    fi
    for p in $(echo "$platforms" | tr ',' ' '); do
        case "$(echo "$p" | tr '[:upper:]' '[:lower:]')" in
            ios)
                dest="$(pwd)/downloads/support/python-ios-mobile-forge-${PYTHON_VERSION}"
                download_support ios "$dest" || return
                export MOBILE_FORGE_IOS_SUPPORT_PATH="$(resolve_support_root "$dest")"
                ;;
            android)
                dest="$(pwd)/downloads/support/python-android-mobile-forge-${PYTHON_VERSION}"
                download_support android "$dest" || return
                export MOBILE_FORGE_ANDROID_SUPPORT_PATH="$(resolve_support_root "$dest")"
                ;;
            *) echo "Unknown platform: $p (expected iOS or android)" ;;
        esac
    done
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

    # `--python-preference only-managed` forces uv to use a relocatable
    # python-build-standalone interpreter and NEVER a system one.
    uv venv --seed --python-preference only-managed --python="$PYTHON_VERSION" $venv_dir
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

# configure Android paths — every ABI the manifest declares for this
# minor must have a device binary in the support tree
if [ ! -z "$MOBILE_FORGE_ANDROID_SUPPORT_PATH" ]; then
    for abi in $ANDROID_ABIS; do
        if [ ! -e "$MOBILE_FORGE_ANDROID_SUPPORT_PATH/install/android/$abi/python-$PYTHON_VERSION/bin/python$PYTHON_VER" ]; then
            echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH does not appear to contain a Python $PYTHON_VERSION Android $abi device binary."
            return
        fi
    done

    echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH: $MOBILE_FORGE_ANDROID_SUPPORT_PATH"
fi

# In GitHub Actions, persist the resolved support-tree paths to the job environment so
# later workflow steps can read them — exports from a `source`d script don't survive
# across steps. Consumed by the "Drop support-tree dep wheels" step, which reads each
# tree's VERSIONS manifest to know which wheels to drop. No-op locally ($GITHUB_ENV unset).
if [ -n "${GITHUB_ENV:-}" ]; then
    {
        echo "MOBILE_FORGE_IOS_SUPPORT_PATH=$MOBILE_FORGE_IOS_SUPPORT_PATH"
        echo "MOBILE_FORGE_ANDROID_SUPPORT_PATH=$MOBILE_FORGE_ANDROID_SUPPORT_PATH"
        echo "ANDROID_ABIS=$ANDROID_ABIS"
    } >> "$GITHUB_ENV"
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

# The script is sourced; don't leave helper functions in the user's shell.
unset -f download_support resolve_support_root relocate_pkgconfig_prefix resolve_full_version
