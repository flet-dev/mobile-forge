# curl-cffi

[`curl-cffi`](https://curl-cffi.readthedocs.io/en/latest/) is an HTTP client that passes itself
off as a real browser. It binds, through cffi, to
[curl-impersonate](https://github.com/lexiforest/curl-impersonate) — a patched libcurl built
against BoringSSL — so the TLS ClientHello, the HTTP/2 settings and the header order that go out
on the wire are a named browser's rather than a Python library's, and a server that fingerprints
its callers by [JA3/JA4](https://github.com/FoxIO-LLC/ja4) or by frame shape sees Chrome. Reach
for it in a Flet app when an API or page you need answers an ordinary client with a challenge
page, a 403 or a silent block.

The API is `requests`-shaped and everything is re-exported at the top level:
[`curl_cffi.get(url, ...)`](https://curl-cffi.readthedocs.io/en/latest/quick_start.html) for a
one-shot, `Session` or
[`AsyncSession`](https://curl-cffi.readthedocs.io/en/latest/asyncio.html) when you want the
connection pool and the cookie jar to survive between calls, and
[`WebSocket`](https://curl-cffi.readthedocs.io/en/latest/websockets.html) for a socket.

## Install

Add curl-cffi to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "curl-cffi",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

**The [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) line
is required, not optional.** No `armeabi-v7a` wheel is published — upstream ships no 32-bit ARM
build of curl-impersonate for anything to link against — so a default `flet build apk`, which
targets all three ABIs, fails at dependency resolution for the 32-bit one after the other two
have already resolved, which makes the failure look like a fluke. Spell the ABI names out in
full; `arm64` and `x64` are the macOS spellings and Flet rejects them here. Dropping 32-bit ARM
costs you old hardware rather than current users — 64-bit has been mandatory for Play Store
uploads since 2019.

**On Python 3.13 and 3.14, Android arm64-v8a can resolve to upstream's own wheel rather than
this index's.** `flet build` installs with `pip install --upgrade --only-binary :all:
--extra-index-url https://pypi.flet.dev`, so pip sees PyPI too, and upstream publishes exactly
one mobile wheel per minor there — `cp313` and `cp314`, `android_24_arm64_v8a`, at the same
version this index carries; no cp312, no x86_64, no armeabi-v7a, no iOS. One Android build can
therefore carry two different builds of a single version across its ABIs, and a `==` pin cannot
separate them because the versions agree. They are not the same payload — upstream's arm64-v8a
wheel is 8.2 MB compressed and 25.2 MB unpacked against 2.7 MB and 6.3 MB here — and which one an
unpinned resolve prefers was not measured.

The lever is the **Python** version, not a `curl-cffi` pin: upstream publishes no cp312 mobile wheel
at all, so building on 3.12 is what settles it. Note `flet build` takes the **highest** stable Python
your `requires-python` admits, so the common `>=3.10` lands on 3.14 — exactly the range where the
two builds overlap. Say `requires-python = "==3.12.*"`, or pass `--python-version 3.12`, as the
[`fingerprint-fanout`](examples/fingerprint-fanout) example does.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`fingerprint-fanout`](examples/fingerprint-fanout) — five browser profiles probed at once,
  with the fingerprints each one produced.

## Usage in a Flet app

Build a session inside a handler, name a profile, and put the decoded body into a control:

```python
import curl_cffi
import flet as ft


async def main(page: ft.Page):
    async def load(e):
        async with curl_cffi.AsyncSession(impersonate="chrome", timeout=15) as session:
            response = await session.get("https://api.example.com/items")
        feed.controls = [ft.Text(item["title"]) for item in response.json()]
        page.update()

    page.add(ft.Button("Load", on_click=load), feed := ft.Column())
```

The two arguments a mobile app should not leave to the defaults are both there. `impersonate=`
is the whole reason for the package and is off unless you pass it. `timeout=` defaults to 30
seconds, which on a phone that just lost its signal is a spinner nobody waits out.

The synchronous `Session` has the same shape, but its request blocks the calling thread outright
and must go through a worker — see [Threading](#threading).

### Storage

Bodies arrive in memory (`response.content` is `bytes`, `response.text` is `str`). Anything the
user expects to keep belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is never auto-deleted.

Two paths the library picks for itself. The first is the response cache: `FileCacheBackend`
defaults to `tempfile.gettempdir() / "curl_cffi_cache"`, wherever the stdlib puts that on device.
Point it somewhere you chose:

```python
import os
from datetime import timedelta

from curl_cffi import FileCacheBackend, Session

cache_dir = os.path.join(os.getenv("FLET_APP_STORAGE_CACHE", "."), "http-cache")
session = Session(cache=FileCacheBackend(expires=timedelta(hours=1), path=cache_dir))
```

`expires` is required, and `cache=` also takes a bare `int` of seconds or a `timedelta` — which
builds a `FileCacheBackend` in the default directory, the one case where the path above is silently
skipped. [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
is the right guarantee for bodies you can fetch again: the OS may purge it under storage pressure,
where [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
can vanish between launches.

The second is the fingerprint store. `FingerprintManager` resolves `$XDG_CONFIG_HOME/impersonate`,
falling back to `~/.config/impersonate`, and every request naming a target the wheel does not carry
natively reads `fingerprints.json` from there. Set `IMPERSONATE_CONFIG_DIR` to a directory under
`FLET_APP_STORAGE_DATA` before `import curl_cffi` if you ship extra fingerprints; `~` on device is
not a directory you chose.

Caching is synchronous-only: `AsyncSession(cache=...)` raises
`NotImplementedError: AsyncSession does not support cache yet because CacheBackend I/O is
blocking.` Cookies live in the session and die with it, so persist any you need yourself.

### Threading

**Prefer `AsyncSession`, and drive it from Flet's own loop.** It does not use threads: it runs
`curl_multi` through the running asyncio loop's `add_reader`/`add_writer`, so it needs a loop and
takes the one it finds. Write `async def main(page)` and start work with
[`page.run_task(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_task) — never
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), which hands
the work to an executor with no running loop and then discards the future, so whatever the worker
raises disappears without a traceback. Four consequences follow:

- **The first request binds the session to whichever loop is running then**, permanently.
  Constructing one at module scope is harmless; using it from a second loop is not.
- **Close every session** — `async with`, or `await session.close()`. Each one keeps a background
  task that wakes every 0.1 s until closed, which on a phone is battery spent on nothing.
- **Put the re-entrancy guard in the handler, not in the coroutine.** `run_task` only schedules,
  so a `disabled = True` set inside the task has not happened when the handler returns and Flet
  pushes the control's state.
- **End the task with an explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)** — auto-update fires only
  around event handlers and around `main`.
- **Concurrency is capped at `max_clients`, 10 by default** — an `asyncio.gather` over more URLs
  than that queues the rest rather than failing.

For the synchronous `Session`, the request blocks the calling thread inside `curl_easy_perform`,
so it belongs in a `page.run_thread(...)` worker. A session is thread-safe — it mints a fresh
curl handle per thread — but its own docstring recommends one session per thread, and that is the
shape to copy.

### Certificates

curl-cffi resolves one CA bundle at **import** time and hands the path to libcurl at request
time. It tries `SSL_CERT_FILE`, `CURL_CA_BUNDLE` and `REQUESTS_CA_BUNDLE` in that order, then
OpenSSL's built-in path, then `certifi.where()` — and on device the first step wins, because
Flet's generated startup code sets `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to `certifi.where()`
before your module runs (read out of the `lib/python.dart` a `flet build` generates). So the
bundle is certifi's on both platforms, and `tests/` asserts on device that the resolved path is a
readable PEM. That it is *certifi's* follows from the startup code, not from the test.

Two things follow. Overriding the bundle means setting `SSL_CERT_FILE` **above** your
`import curl_cffi` — the resolution happens at that import, not at Flet's startup — and a value
naming a file that does not exist is skipped silently. And **the trust anchors on device are only
certifi's**, so a corporate root or an intercepting debug proxy such as mitmproxy, which a
desktop `flet run` picks up out of the machine's own trust store, fails on the phone with a
`CertificateVerifyError` against a host the browser is perfectly happy with. Ship your own PEM in
`src/assets/` and name it per session or per request:

```python
roots = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "roots.pem")
session = curl_cffi.Session(verify=roots)
```

[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir) is where
`flet build` puts `src/assets/`. `verify=` covers the origin and the proxy alike, and unlike the env
var it cannot be defeated by import order.

### Impersonation

`impersonate="chrome"` is an alias that resolves to one particular Chrome build, chosen by the
release rather than by you; a versioned name such as `impersonate="chrome131_android"` says which.
[Upstream's table](https://curl-cffi.readthedocs.io/en/latest/impersonate/targets.html) is the
only complete list.

**The built-in targets are compiled into the wheel, so that list is fixed at build time**, and
checkable offline: `Curl().impersonate(name)` returns `0` when that name's fingerprint tables are
present and a non-zero code when they are not, without raising — which separates "this build does
not know that target" from "the request failed" on a device with no connectivity. Through a
`Session` the same miss surfaces as `ImpersonateError` instead.

That list is not the whole story: a name the wheel does not carry natively is looked up in
`fingerprints.json` under the directory in [Storage](#storage) and applied from Python, so extra
targets are shippable without a new wheel. Fetching them is
`FingerprintManager.update_fingerprints()` — importable on device, but it needs an
`IMPERSONATE_API_KEY` for impersonate.pro and writes into that config dir. Run it on a laptop and
ship the resulting `fingerprints.json`.

### Android

**The `INTERNET` permission is already there.** `flet build` starts its
[permission table](https://flet.dev/docs/publish/android/#permissions) from
`{"android.permission.INTERNET": True}` and merges your entries into it, so an outbound request
needs no `pyproject.toml` entry. This is the only platform where the question exists.

**Site-packages is a ZIP here, a directory on iOS**, and curl-cffi runs out of it as-is: nothing
in the package needs a filesystem path of its own, so there is no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry to write. The
CA bundle is the one file that does need one, and it is already a real path by the time curl-cffi
looks — `certifi.where()` unpacks its roughly 240 KB `cacert.pem` to a temporary file when the
package it lives in is zipped.

### App size

2.6–2.9 MB compressed and 6.3–7.0 MB unpacked per slice, measured across all five cp312 wheels
at this version (the x86_64 slices are the large end of each range; both platforms sit in it). Nearly all of it is the single
`_wrapper` extension, which carries the whole of curl, BoringSSL, nghttp2, nghttp3, ngtcp2,
brotli, zstd and zlib inside it — so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing worth
removing. Android adds a shared C++ runtime of about 1.3 MB per ABI, which every C++ package in
your app shares rather than duplicating.

The levers are an app bundle, split APKs, or the narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) that
[Install](#install) already forces you to write. These are payload figures, not the exact amount
added to the finished APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel, and the native library behind it is the same
curl-impersonate release this recipe pins — `scripts/build.py` names the version and `meta.yaml`
matches it — so the impersonation targets are the same set in both places.

The trust store is what differs, in the direction that produces "works on my laptop": the desktop
run finds the operating system's bundle where the device finds certifi's, so a root installed on
your machine is invisible on the phone. See [Certificates](#certificates). One real HTTPS request
against your own backend, on a device, is the thing to validate.

## Things to know

- **Every warning the library raises is silenced before you see it.** `curl_cffi/__init__.py`
  ends with `config_warnings(on=False)`, a `simplefilter("ignore")` over the package's own warning
  class — so the one it emits when a session built with its own `curl=` handle is used from a
  second thread never reaches a log, on a platform where reading logs is already the hard part. Call
  `curl_cffi.config_warnings(on=True)` while debugging, and do not read a silent run as a clean
  one.

- **Retries are off by default** (`retry=0`), and with the 30 s timeout that means a request made
  as the radio drops fails once and stays failed. Both are worth setting deliberately for a phone;
  see upstream's [advanced usage](https://curl-cffi.readthedocs.io/en/latest/advanced.html).

- **HTTP/3 is compiled in but unproven on a device.** The shipped Android extension carries
  ngtcp2 and nghttp3 symbols, and `http_version="v3"` exists in the API, but nothing here has run
  a QUIC request from a phone or through an emulator's NAT. Read `curl_cffi.__curl_version__` on
  the device you care about before designing around it — it is a real call into the linked
  library, not a constant.

- **Licensing:** curl_cffi is [MIT](https://spdx.org/licenses/MIT.html) and that is all its
  metadata declares, but nine projects are compiled into the extension — patched curl,
  curl-impersonate's own patches, BoringSSL, nghttp2, nghttp3, ngtcp2, brotli, zstd and zlib —
  arriving as one static archive from
  [`flet-libcurl-impersonate`](../flet-libcurl-impersonate). Every one of those licences
  ([curl](https://spdx.org/licenses/curl.html), [MIT](https://spdx.org/licenses/MIT.html),
  [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html),
  [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html),
  [Zlib](https://spdx.org/licenses/Zlib.html)) is permissive and none restricts what you may
  ship, but each asks that its copyright notice travel with the binary — and **those notices are
  not in the curl_cffi wheel**. Its `dist-info/licenses/` holds one file, curl_cffi's own MIT
  text, because the archive links in as a build-time dependency that ships nothing else to the
  device. The nine texts are in `flet-libcurl-impersonate`'s wheel, under the same
  `dist-info/licenses/`, and beside its `meta.yaml`; copy them into whatever acknowledgements
  screen your app has. Flagging it, not advising you — we are not lawyers.

## Build notes (maintainers)

`patches/mobile.patch` explains its own hunks in its preamble, and `meta.yaml` justifies
`excluded_arches`, the `IMPERSONATE_*` environment and the host pins inline in both recipes. What
is left is shape, hazards, and what a green run does not prove.

### Recipe shape

**Two recipes because the payload is a prebuilt binary, not a build.**
`flet-libcurl-impersonate` repackages upstream's per-slice release tarball — a single
`libcurl-impersonate.a` merging nine projects — into `{platlib}/opt`, and curl-cffi links that.
Building curl and BoringSSL from source across five slices was rejected: BoringSSL's build system
is a project of its own, and a rebuild would drift from the fingerprints upstream actually tests.
The cost is that upstream's release assets are now the supply chain, which is what
[Upgrade hazards](#upgrade-hazards) is mostly about.

It sits under `requirements.host_build`, so it links in without appearing in the consumer's
`Requires-Dist` and ships nothing to the device: `unzip -l` on the Android arm64-v8a wheel shows
36 files and no `opt/` directory, against 25 files and a 43 MB `opt/libcurl-impersonate.a` in the
library wheel it linked against.

The platforms are asymmetric in one place, and it is why the Android wheel — and only the Android
wheel — declares `flet-libcpp-shared`: the arm64-v8a extension's `DT_NEEDED` is `libm`,
`libpython3.<minor>`, `libc++_shared`, `libdl`, `libc`, where iOS links libc++ statically.
`patches/mobile.patch` has the link recipes.

### Upgrade hazards

- **The two versions move independently.** A curl-cffi bump can expect a curl-impersonate release
  whose assets `flet-libcurl-impersonate` does not pin, and a curl-impersonate bump can rename or
  drop a per-slice asset. `scripts/build.py`'s own `__version__` is the number to compare the pin
  against; when they diverge, the desktop-versus-device claim in
  [Other considerations](#other-considerations) stops being true.
- **Upstream's release-asset naming and slice coverage is the single point of failure** for the
  whole chain: `aarch64-linux-android`, `x86_64-linux-android`, `arm64-apple-ios` and the two
  simulator assets. `excluded_arches: [armeabi-v7a]` is what makes `target_arch` mandatory in
  [Install](#install); if a 32-bit ARM asset ever appears, that paragraph and the example's
  `pyproject.toml` entry both stop being necessary.
- **`scripts/build.py` is the patch target.** A restructure of `detect_arch()` or of `libs.json`
  makes the patch fail to apply — or worse, apply into a build that falls back to the host's
  `uname` and downloads a host-architecture archive.
- **The target table, the trust anchors and the component set all move with the vendored
  library**, without any recipe change — the last of those is what the Licensing bullet in
  [Things to know](#things-to-know) rests on. So does upstream's own PyPI mobile coverage, which
  [Install](#install) describes.

### Re-verification checklist

- `__curl_version__` on device still names an `impersonate` build, and
  `curl_easy_impersonate("chrome110")` still returns 0 — `tests/` covers both.
- `DEFAULT_CACERT` is still a readable PEM on device (`tests/` covers this too), and Flet's
  generated `lib/python.dart` still sets `SSL_CERT_FILE`. All of [Certificates](#certificates)
  rests on that startup code, which is template output and can change under a Flet upgrade
  without anything here failing.
- The consumer wheel still has no `opt/` directory and no second copy of anything from the
  archive; the file count and `DT_NEEDED` set are unchanged.
- The licence texts actually present under `dist-info/licenses/` in both shipped wheels — the
  Licensing bullet is a claim about what is and is not in them.
- Sizes re-measured per slice off the published wheels, summing file bytes rather than reading
  `du`, which answers in binary units.
- Which wheel a bare `curl-cffi` resolves to, per slice and per minor, once this index publishes
  one: `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev`,
  then read the filename. [Install](#install) currently says that is unmeasured.
- iOS `MH_DYLIB`; Android 16 KB `PT_LOAD` alignment.

### Coverage gaps

`tests/` is four network-free functions by design — an emulator has no guaranteed connectivity —
so **no test has ever made an HTTPS request from a device with this wheel.** They prove the
archive linked, that the library is the impersonate build, that one fingerprint table is present
and that the CA bundle path is readable. Nothing exercises `Session` or `AsyncSession`, a
handshake, cookies, proxies, HTTP/2 or HTTP/3, and nothing shows a fingerprint being accepted by a
real server. An import-and-construct suite passes even where the first request would fail; the
[`fingerprint-fanout`](examples/fingerprint-fanout) example is the thing to build and install to
close that gap. The current versions have also not been through a CI run — the established green
result is for the previous curl-cffi and curl-impersonate pair.
