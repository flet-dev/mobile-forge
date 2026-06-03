function publish_to_pypi() {
    for wheel in "$@"; do
        curl -F package=@$wheel https://$GEMFURY_TOKEN@push.fury.io/flet/
    done
}

# Resolve which python-build tarball source to use.
# When PYTHON_BUILD_RUN_ID is set (workflow_dispatch input), fetch the
# named tarball from that python-build Actions run's artifacts; otherwise
# download from the canonical v<version> release URL.
#
# Args:
#   $1 artifact_platform — "android" | "darwin" (matches the python-build artifact name)
#   $2 tarball           — e.g. python-android-mobile-forge-3.12.tar.gz
#   $3 extract_dir       — local dir to extract the tarball into
#
# Caller env:
#   PYTHON_SHORT_VERSION — e.g. 3.12 (required)
#   PYTHON_BUILD_RUN_ID  — empty for release URL; non-empty for `gh run download`
#   GH_TOKEN             — needed only when PYTHON_BUILD_RUN_ID is set
#   RUNNER_TEMP          — GitHub Actions runner temp dir (only used in override path)
function fetch_python_build_tarball() {
    local artifact_platform="$1"
    local tarball="$2"
    local extract_dir="$3"
    if [[ -n "${PYTHON_BUILD_RUN_ID:-}" ]]; then
        echo "Fetching $tarball from python-build run $PYTHON_BUILD_RUN_ID"
        local stage="$RUNNER_TEMP/python-build-artifact"
        rm -rf "$stage"
        mkdir -p "$stage"
        gh run download "$PYTHON_BUILD_RUN_ID" \
            --repo flet-dev/python-build \
            --name "python-${artifact_platform}-${PYTHON_SHORT_VERSION}" \
            --dir "$stage"
        tar -xzf "$stage/$tarball" -C "$extract_dir"
    else
        curl -#OL "https://github.com/flet-dev/python-build/releases/download/v${PYTHON_SHORT_VERSION}/$tarball"
        tar -xzf "$tarball" -C "$extract_dir"
    fi
}
