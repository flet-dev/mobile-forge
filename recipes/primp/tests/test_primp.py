def test_import_and_client_construction():
    """primp is a Rust-backed HTTP client (PyO3 binding). Importing
    the package and constructing a Client is the smallest call we can
    make that exercises the compiled extension's symbol load. No
    network I/O — that would be flaky in CI."""
    import primp

    # Default constructor — no impersonation, no proxy.
    client = primp.Client()
    # Methods exposed by the Rust binding (per the .pyi).
    for attr in ("get", "post", "head", "put", "delete", "request"):
        assert callable(getattr(client, attr)), f"Client missing {attr}"


def test_exception_hierarchy():
    """Verifies the exception classes the Rust binding exports are
    importable and form the documented hierarchy."""
    import primp

    assert issubclass(primp.RequestError, primp.PrimpError)
    assert issubclass(primp.ConnectError, primp.RequestError)
    assert issubclass(primp.TimeoutError, primp.RequestError)
    assert issubclass(primp.StatusError, primp.PrimpError)


def test_https_request_does_not_abort_process():
    """A first HTTPS request should either complete or raise a Python error.

    Mobile runtimes must not abort the process while initializing DNS, TLS, or
    other native request machinery.
    """
    import primp

    client = primp.Client(timeout=10, connect_timeout=10)
    try:
        response = client.get("https://example.com")
    except primp.RequestError:
        print("primp HTTPS request result: RequestError")
        # Some device/CI environments have restricted outbound networking.
        # The regression we need to catch is a native abort, not a Python-level
        # request failure.
        return

    print(f"primp HTTPS request result: status={response.status_code}")
    assert response.status_code < 600
