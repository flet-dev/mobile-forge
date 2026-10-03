# thrift

[Apache Thrift](https://thrift.apache.org/)'s Python runtime: the protocols, transports and
servers that code generated from a `.thrift` IDL runs on. In a Flet app it is the client
side of a Thrift service — your own backend, or any system that speaks Thrift — over TCP
or HTTP.

This wheel compiles thrift's optional C++ codec, `thrift.protocol.fastbinary`, for Android
and iOS. The binary and compact protocols work without it, in pure Python. With it, a
message carrying lists and maps, like a batch of sensor readings, encoded and decoded 7 to
19 times faster in our emulator and simulator runs; a small flat struct gains less, about
two times on a desktop.

## Install

```toml
dependencies = [
    "flet",
    "thrift",
]
```

Do not list `thrift` in `[tool.flet] source_packages`, and remove it if you added it before
this wheel existed. That setting builds the codec for your computer instead of the phone,
so the app runs on thrift's pure-Python fallback while carrying a binary it cannot load.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`telemetry-rpc`](examples/telemetry-rpc) — calls a Thrift service over a loopback
  socket, receives a declared exception, and times each protocol native and pure.

## Usage in a Flet app

Generate the Python code from your IDL on your computer with the
[Thrift compiler](https://thrift.apache.org/download) (`thrift --gen py service.thrift`),
and put the generated package in your app's `src/`. The compiler is never needed on the
device. A client is then a socket, a transport and a protocol
([upstream tutorial](https://thrift.apache.org/tutorial/py)):

```python
from thrift.protocol import TBinaryProtocol
from thrift.transport import TSocket, TTransport

from telemetry import Telemetry  # generated from telemetry.thrift

socket = TSocket.TSocket("telemetry.example.com", 9090)
socket.setTimeout(5000)                          # ms; the default waits forever
transport = TTransport.TFramedTransport(socket)  # framed or buffered, as the server expects
client = Telemetry.Client(TBinaryProtocol.TBinaryProtocolAccelerated(transport))

transport.open()
try:
    summary = client.submit(readings)            # readings: a list of generated Reading
finally:
    transport.close()
```

Use the `*Accelerated` protocol classes: on this wheel they run the native codec. Requests
are encoded natively on any transport, but replies are decoded natively only through
`TFramedTransport` or `TBufferedTransport`. So always wrap the connection: in whichever of
the two the server speaks (`TBufferedTransport` is the same on the wire as a bare socket),
and over HTTP, `TTransport.TBufferedTransport(THttpClient.THttpClient(url))`.

Serializing without a connection, for a cache file or a message payload, is one call each
way with [`thrift.TSerialization`](https://github.com/apache/thrift/blob/master/lib/py/src/TSerialization.py):

```python
from thrift.TSerialization import deserialize, serialize

from telemetry.ttypes import Summary

factory = TBinaryProtocol.TBinaryProtocolAcceleratedFactory()
data = serialize(summary, factory)
copy = deserialize(Summary(), data, factory)
```

### Threading

Every call blocks on the network. Make it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the worker with [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — a
background thread does not get the automatic one. A transport and its client hold
connection state, so give each thread its own.

Set the socket timeout. A phone moving between Wi-Fi and cellular can leave a connection
dead without closing it, and with no timeout the worker waits on it forever.

### TLS

`TSSLSocket` will not verify a server until it is told which certificates to trust, and
raises `ValueError: ca_certs is needed when cert_reqs is not ssl.CERT_NONE` otherwise. Pass
it the default context, which in a Flet app trusts the `certifi` bundle that Flet points
`SSL_CERT_FILE` at:

```python
import ssl

from thrift.transport import TSSLSocket

socket = TSSLSocket.TSSLSocket(
    "telemetry.example.com", 9443, ssl_context=ssl.create_default_context()
)
```

`THttpClient` with an `https://` URL needs nothing extra. For a server signed by a private
CA, build the context with `ssl.create_default_context(cafile=...)` and pass it as
`ssl_context=` to either class; `THttpClient`'s own `cafile=` argument raises `TypeError`
unless a client certificate is given too.

A certificate the device rejects surfaces differently per class. `TSSLSocket.open()` raises
`TTransportException: Could not connect to any of [...]`, the same message as an
unreachable host, with the `ssl.SSLCertVerificationError` in the exception's `inner`.
`THttpClient` raises the `ssl.SSLCertVerificationError` itself.

### App size

The wheel unpacks to about 0.3 MB per Android ABI or iOS slice, of which the native codec
is 40–105 KB. On Android the codec also needs the C++ runtime, `libc++_shared.so`, about
0.9–1.3 MB per ABI, carried once however many C++ packages the app uses. That runtime is
the bigger share, and the lever is the ABI list: `[tool.flet.android] target_arch` drops
whole ABIs you do not ship.

### Other considerations

`flet run` on a desktop installs PyPI's own thrift wheels, which carry the same native
codec, so desktop and device take the same code paths.

## Things to know

- **Without the codec, the Accelerated classes are slower than the plain ones.** They fall
  back to pure Python silently, and every one created retries the missing import, so code
  that builds a protocol per message, as `TSerialization` does, pays for it each time: a
  small struct ran over ten times slower than with `TBinaryProtocol`. Pass `fallback=False`
  to make a missing codec raise `ImportError` when the protocol is created, or check that
  `from thrift.protocol import fastbinary` succeeds.

- **A bare `TSocket`, `TSSLSocket` or `THttpClient` bypasses the native decoder.** Requests
  are still encoded natively, but every reply is decoded in pure Python. Nothing fails; it
  is only slower.

- **`TJSONProtocol` has no native codec.** For a batch of readings it is about 2.3 times the
  size of binary and slower than either binary or compact in pure Python. Use it where a
  human needs to read the bytes, not for traffic.

## Build notes (maintainers)

### Recipe shape

A setuptools package with one optional C++ extension. Upstream publishes desktop wheels
only, built with cibuildwheel since 0.24.0, and no pure-Python wheel, so without a mobile
wheel pip has nothing it can install for Android or iOS. The `source_packages` route that
would otherwise apply compiles the extension for the build host: pip's isolated build drops
serious_python's platform-faking `sitecustomize`, `setup.py` runs as macOS, and the macOS
`.so` lands in every mobile site-packages directory (pip never checks the tags of a wheel it
built itself). On an iPhone simulator that shipped a broken framework stub, and the
Accelerated classes retrying it ran 12–23 times slower than the plain ones.

Shipping the pure-Python build instead was rejected: it works, at a fraction of the speed,
and it brings the silent-fallback trap above.

If upstream adds iOS and Android rows to its cibuildwheel matrix, those wheels will cover
CPython 3.13+ on arm64 and x86_64 only. armeabi-v7a, which `flet build apk` builds by
default, and CPython 3.12 would still need this recipe.

### Upgrade hazards

- **The forced build depends on `setup.py`'s `CIBUILDWHEEL` check.** If upstream renames or
  drops it, a failed compile quietly produces a pure-Python wheel again. The build log then
  says `Attempting to build without the extension now`, and `test_fastbinary_is_native`
  fails on device.
- **A newer upstream release with mobile wheels outranks this one** on the Pythons it
  covers. Bump the recipe to the same version, or the same app can resolve different thrift
  versions on different ABIs.
- **The example's generated code comes from the compiler matching the recipe's version.**
  Regenerate it when bumping (see the example's README) rather than assuming the old output
  stays valid.

### Re-verification checklist

- Every build log shows `building 'thrift.protocol.fastbinary' extension` and no fallback
  banner, and every wheel contains `thrift/protocol/fastbinary.cpython-*.so`.
- Android: `DT_NEEDED` lists `libc++_shared.so`, every `LOAD` segment is aligned `0x4000`, and
  METADATA requires `flet-libcpp-shared`. iOS: `otool -hv` reports `DYLIB`.
- The device tests pass, and still fail against a pure-Python build of thrift
  (`CC=false CXX=false pip install --no-binary thrift`) — run that negative control after
  any change to the tests, since a fallback can make a weak test pass.
- The example's status line reads "native fastbinary codec" on both platforms.

### Coverage gaps

The device tests cover the codec loading, the Accelerated protocols binding it, byte-for-byte
agreement with pure Python, round trips, and loopback calls over TCP (framed, buffered and
bare) and HTTP (buffered and bare). They use hand-written structs, so the generated service
code — `Client`, `Processor`, declared exceptions — runs only in the example. `TSSLSocket`
and HTTPS were checked by hand against public servers, since they need a network; the server
classes other than `TThreadedServer` and `THttpServer`, `THeaderProtocol` and
`TZlibTransport` are untested. The armeabi-v7a and iPhone-device slices are built but never
run, and every timing quoted here comes from emulators, simulators and a desktop, not from
phones.
