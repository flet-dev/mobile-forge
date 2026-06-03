def test_channel_credentials():
    """grpcio's C-extension (`_cython`) is the reason this is a recipe.
    Creating credentials + a channel object touches the cython binding
    without needing an actual server."""
    import grpc

    creds = grpc.ssl_channel_credentials()
    assert creds is not None

    channel = grpc.insecure_channel("localhost:9999")
    assert channel is not None
    channel.close()


def test_status_codes():
    """StatusCode is a Cython enum — import + value access exercises the
    C-typed bridge."""
    import grpc

    assert grpc.StatusCode.OK.value[0] == 0
    assert grpc.StatusCode.NOT_FOUND.value[0] == 5
    assert grpc.StatusCode.UNAUTHENTICATED.value[0] == 16
