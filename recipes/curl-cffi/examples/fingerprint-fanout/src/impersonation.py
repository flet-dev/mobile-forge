"""The curl-cffi half: what this build knows offline, and what a server sees."""

import asyncio
import os
import platform
import ssl
import time

import certifi
import curl_cffi
from curl_cffi import Curl, CurlHttpVersion
from curl_cffi.curl import DEFAULT_CACERT
from curl_cffi.requests import AsyncSession

# Answers with the JA3/JA4 hashes of the ClientHello it just received, the
# HTTP/2 fingerprint, and the User-Agent it was sent. Only the far end of a
# handshake can see any of that, which is why this is the one thing in the
# example that leaves the device.
PROBE_URL = "https://tls.browserleaks.com/json"

# "off" is the sentinel for no impersonation. The other four name fingerprints
# compiled into the linked curl-impersonate build, so a bump can retire one.
TARGETS = ("chrome150", "chrome131_android", "safari260_ios", "firefox147", "off")

# curl-cffi's own default is 30 s, which on a phone that just lost signal is a
# spinner nobody waits out.
TIMEOUT = 15

FIELDS = ("ja4", "ja3n", "ja3", "h2", "ua")

VERSION = f"curl_cffi {curl_cffi.__version__} — Python {platform.python_version()}"
CURL_VERSION = curl_cffi.__curl_version__

# Response.http_version is a plain int; CurlHttpVersion is an IntEnum, so these
# keys match one.
HTTP_NAMES = {
    CurlHttpVersion.V1_0: "http/1.0",
    CurlHttpVersion.V1_1: "http/1.1",
    CurlHttpVersion.V2_0: "h2",
    CurlHttpVersion.V2TLS: "h2",
    CurlHttpVersion.V3: "h3",
}


def known_targets():
    """Ask the linked library which targets it holds fingerprints for, offline.

    curl_easy_impersonate() returns 0 when a target's TLS and HTTP/2 tables are compiled
    in and 43 when the name is unknown — it does not raise — so this separates "this
    build does not know that target" from "the request failed" without opening a socket,
    and goes red on its own if a bump retires one.
    """
    verdicts = {}
    for target in TARGETS:
        if target == "off":
            continue
        curl = Curl()
        try:
            verdicts[target] = curl.impersonate(target) == 0
        finally:
            curl.close()
    return verdicts


def cacert():
    """Describe the CA bundle curl-cffi resolved at import, and which source won.

    Its _default_cacert() tries SSL_CERT_FILE / CURL_CA_BUNDLE / REQUESTS_CA_BUNDLE,
    then OpenSSL's compiled-in path, then certifi — and the winner differs between a
    desktop `flet run` and a phone, so it is read back rather than assumed. On Android
    certifi's cacert.pem lives inside sitepackages.zip and certifi.where() unpacks it to
    a temporary file, so the path is a real one either way.
    """
    source = "unknown"
    for name in ("SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
        if os.environ.get(name) == DEFAULT_CACERT:
            source = f"${name}"
            break
    else:
        if ssl.get_default_verify_paths().cafile == DEFAULT_CACERT:
            source = "openssl default path"
        elif certifi.where() == DEFAULT_CACERT:
            source = f"certifi {certifi.__version__}"
    try:
        with open(DEFAULT_CACERT, "rb") as bundle:
            pem = bundle.read()
    except OSError as error:
        return source, DEFAULT_CACERT, f"unreadable: {error.strerror}"
    return (
        source,
        DEFAULT_CACERT,
        f"{len(pem):,} B · {pem.count(b'BEGIN CERTIFICATE')} certificates",
    )


async def probe(target):
    """Handshake once as `target` and return what the far end reports.

    One AsyncSession per target rather than one shared one: a session pools
    connections, and a pooled connection is a handshake that already happened,
    so a later target could be answered through an earlier one's fingerprint.
    `async with` matters — each session keeps a 0.1 s watchdog task alive until
    it is closed.
    """
    started = time.perf_counter()
    async with AsyncSession(
        impersonate=None if target == "off" else target, timeout=TIMEOUT
    ) as session:
        response = await session.get(PROBE_URL)
    seen = response.json()
    return {
        "status": response.status_code,
        "http": HTTP_NAMES.get(response.http_version, str(response.http_version)),
        "ms": (time.perf_counter() - started) * 1e3,
        # ja3 hashes the ClientHello as sent; ja3n sorts the extensions first.
        # Chrome shuffles that order every handshake and curl-impersonate copies
        # it, so ja3 moves between runs for a Chrome target while ja3n and ja4
        # (sorted by construction) hold still. Showing both is the point.
        "ja4": seen["ja4"],
        "ja3n": seen["ja3n_hash"],
        "ja3": seen["ja3_hash"],
        "h2": seen["akamai_hash"],
        "ua": seen["user_agent"] or "(none sent)",
    }


async def fanout(on_result):
    """Probe every target at once, calling `on_result(target, reading, error)`.

    One task per target under a single gather, so the wall clock is the slowest
    handshake rather than the sum of five — the shape a search app fanning out to
    several endpoints needs. Each task catches its own failure, so one unreachable
    target costs one row. Returns the wall clock in milliseconds, for the caller to
    compare against the summed per-probe times.
    """

    async def one(target):
        """Run a single probe and report it, however it ends."""
        try:
            on_result(target, await probe(target), None)
        except Exception as error:
            # libcurl tacks 74 characters of docs URL onto every message, which
            # on five stacked rows is most of the screen.
            detail = str(error).split(" See https://curl.se/", 1)[0]
            on_result(target, None, f"{type(error).__name__}: {detail}")

    started = time.perf_counter()
    await asyncio.gather(*(one(target) for target in TARGETS))
    return (time.perf_counter() - started) * 1e3
