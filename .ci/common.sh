function publish_to_pypi() {
    for wheel in "$@"; do
        curl -F package=@$wheel https://$GEMFURY_TOKEN@push.fury.io/flet/
    done
}
