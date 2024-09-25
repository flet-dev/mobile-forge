function publish_to_pypi() {
    if [[ "$APPVEYOR_PULL_REQUEST_NUMBER" == "" ]]; then
        for wheel in "$@"; do
            curl -F package=@$wheel https://$GEMFURY_TOKEN@push.fury.io/flet/
        done
    fi
}