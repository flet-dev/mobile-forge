"""On-device smoke tests for curl_cffi — the cffi bindings around
curl-impersonate (a patched libcurl + BoringSSL + nghttp2/3 + ngtcp2 + brotli +
zstd + zlib, all statically linked into the `_wrapper` extension). These are
network-free: they exercise the compiled native library directly, without making
any HTTP request (an emulator/simulator has no guaranteed connectivity)."""


def test_import_loads_native_wrapper():
    """Importing curl_cffi loads its compiled cffi extension (_wrapper) — proves
    the mega-archive linked and _cffi_backend / libc++_shared resolve on load."""
    import curl_cffi
    from curl_cffi import _wrapper

    assert _wrapper.lib is not None
    assert _wrapper.ffi is not None


def test_linked_libcurl_is_impersonate_build():
    """__curl_version__ is a real lib.curl_version() call into the statically
    linked library; confirm it is the curl-impersonate build, not system curl."""
    import curl_cffi

    version = curl_cffi.__curl_version__
    assert version.startswith("libcurl/"), version
    assert "impersonate" in version.lower(), version


def test_curl_easy_impersonate_applies_fingerprint():
    """curl_easy_impersonate() succeeds for a known browser target, proving the
    TLS/HTTP2 fingerprint tables are compiled into the native library."""
    from curl_cffi import Curl

    curl = Curl()
    try:
        ret = curl.impersonate("chrome110")
        assert ret == 0, f"curl_easy_impersonate returned {ret}"
    finally:
        curl.close()


def test_default_cacert_resolves_to_a_readable_file():
    """curl_cffi picks its CA bundle once, at import, and hands the path straight
    to libcurl. Flet extracts certifi's bundle out of sitepackages.zip and points
    SSL_CERT_FILE at it, so the path lands on disk — if it ever didn't, every
    HTTPS request would fail with CURLE_SSL_CACERT_BADFILE instead."""
    import os

    from curl_cffi.curl import DEFAULT_CACERT

    assert os.path.isfile(DEFAULT_CACERT), DEFAULT_CACERT
    with open(DEFAULT_CACERT, "rb") as f:
        assert b"BEGIN CERTIFICATE" in f.read(), DEFAULT_CACERT
