# pyzmq

[`pyzmq`](https://pyzmq.readthedocs.io/) is the Python binding for
[ZeroMQ](https://zeromq.org/), a messaging library whose sockets carry whole messages between
queues instead of bytes between endpoints, and whose patterns — a PUSH/PULL work queue, PUB/SUB
fan-out, REQ/REP request-reply — come with the socket type rather than with your code. Import
the package as `zmq`.

On a phone the interesting endpoint is not the network. ZeroMQ's
[`inproc://`](https://libzmq.readthedocs.io/en/latest/zmq_inproc.html) transport connects
threads of the same process through memory, with no port, no permission and no network stack
involved, so those patterns become the plumbing between a Flet UI thread and the background
threads doing the work.

## Install

Add pyzmq to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pyzmq",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`inproc-bus`](examples/inproc-bus) — a PUSH/PULL worker pipeline between the UI thread and
  background threads, stopped by a PUB/SUB broadcast.

## Usage in a Flet app

A work queue is a few lines on each side. Every socket comes from one context, and each is
created in the thread that will use it:

```python
import zmq

CONTEXT = zmq.Context.instance()

def worker():
    jobs = CONTEXT.socket(zmq.PULL)
    jobs.connect("inproc://jobs")
    while True:
        index, payload = jobs.recv_multipart()
        ...

queue = CONTEXT.socket(zmq.PUSH)
queue.setsockopt(zmq.SNDTIMEO, 250)
queue.bind("inproc://jobs")

page.run_thread(worker)
queue.send_multipart([b"7", payload])
```

A message is bytes: anything supporting the buffer protocol goes out as one frame,
[`send_multipart`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Socket.send_multipart)
sends a list of them as one message, and
[`send_pyobj`/`send_json`](https://pyzmq.readthedocs.io/en/latest/howto/serialization.html) wrap
pickle and JSON for the cases where a dict is what you actually have.

### Threading

A [`Context`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Context) is thread-safe
and meant to be shared. A [`Socket`](https://libzmq.readthedocs.io/en/latest/zmq_socket.html) is
not, and nothing checks: four threads sending on one PUSH socket killed a desktop process in
every one of ten runs — a segmentation fault, or a libzmq assertion such as
`Assertion failed: rc == 0 (src/pipe.cpp:186)` — never a Python exception. On a device that is
the app vanishing. Create each socket inside the thread that will use it, and treat "one socket,
one thread" as absolute.

Long-lived loops need a budget.
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits to
the page's `ThreadPoolExecutor`, built with the default worker count — `min(32, cpu_count + 4)` —
so a worker that runs for the life of the app holds one of those slots for the life of the app,
and every other `run_thread` call shares what is left. Three or four workers is a design; a
thread per job is a leak.

A thread blocked in `recv()` cannot be asked to stop. Give the socket
[`RCVTIMEO`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Socket.setsockopt), or poll
it alongside a control socket with a
[`zmq.Poller`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Poller) so a PUB message
can end the loop. As a last resort from another thread,
[`ctx.term()`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Context.term) raises
[`zmq.ContextTerminated`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.ContextTerminated)
inside the blocked call — in well under a millisecond on desktop, out of `recv()` and out of
`Poller.poll()` alike; the woken thread closes its own socket and `term()` then returns. Not
`ctx.destroy()`, though — that closes every socket from the calling thread, which is the
cross-thread use described above, and three of fifteen desktop runs aborted the process rather
than raising anything.

None of this is parallelism. The workers are Python threads, so pure-Python work is still
serialised by the GIL and the bus buys structure and a responsive UI rather than speed. Work
that releases the GIL does scale: in the example, sixteen 256 KB blocks through `bz2` took about
200 ms with one worker and about 70 ms with four on desktop, while a pure-Python sieve measured
the same with four threads as with one. Either way, results arrive on a background thread, so
each repaint ends with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Transports

`inproc://name` is the one that fits a mobile app. The name is arbitrary and private to the
context that owns it, which is why every socket in an app has to come from the same
[`zmq.Context.instance()`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Context.instance).
It is also the fastest: a 64-byte REQ/REP round trip measured about 24 µs over `inproc` against
about 105 µs over TCP loopback, and 1 MB messages moved at roughly 25 GB/s against 2.7 GB/s,
both on desktop. Above pyzmq's 64 KB copy threshold, `send(..., copy=False)` hands libzmq the
buffer rather than a duplicate of it, so a large frame crosses the bus as a pointer — and stays
readable by the sender, which must therefore not overwrite it.

`tcp://127.0.0.1:0` works too; both mobile wheels have the TCP transport compiled in. It costs
an I/O thread — a context created with `zmq.Context(io_threads=0)` still serves `inproc`, while
binding TCP on it fails with `ZMQError: No thread available` — plus roughly four times the round
trip, the subscription delay described below, and a port that is not private to your app: on
Android any installed app holding the `INTERNET` permission can connect to it, and Android gates
socket creation itself on that permission, which `flet build` declares for every app. Reach for
it only when something outside the Python process has to connect.

`ipc://` is compiled in as well, and buys nothing here: it addresses a Unix socket in the
filesystem so that a *different process* can attach, and Flet supports no
[`multiprocessing`](https://flet.dev/docs/cookbook/multiprocessing/) on Android or iOS. One
process means `inproc`.

### App size

Expect approximately 0.6–0.7 MB of compressed wheel and 1.3–1.8 MB unpacked per architecture.
About three quarters of that is the single `zmq.backend.cython._zmq` extension, which has libzmq
and libsodium linked into it. The rest is the Python package, spread thinly enough over its
subpackages that
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has little to
work with.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA; packaging and compression determine that result.

### Other considerations

A desktop `flet run` uses PyPI's wheel. It is the same pyzmq with its own bundled libzmq, but
built by a different toolchain, so read `zmq.zmq_version()` and `zmq.has("curve")` /
`zmq.has("ipc")` / `zmq.has("draft")` when a capability matters rather than assuming the two
builds agree.

An async Flet app should use
[`zmq.asyncio`](https://pyzmq.readthedocs.io/en/latest/api/zmq.asyncio.html): its `Context`
returns sockets whose `recv()` is awaitable, so a coroutine handler yields to the event loop
instead of blocking it. That path is verified here on desktop only.

## Things to know

- **pyzmq publishes its own Android wheels, and an unpinned dependency can give your app a
  different pyzmq on each platform.** PyPI carries official
  [`android_24_*` wheels](https://pypi.org/project/pyzmq/#files) for CPython 3.13 and newer —
  arm64-v8a and x86_64 only, **no armeabi-v7a and no iOS at all**. So a bare `"pyzmq"` can
  resolve upstream's build on Android and this index's on iOS, and drop your 32-bit Android
  devices in the process.

  The two are built differently in a way that matters here. Upstream vendors its own
  `libc++_shared-<hash>.so` inside the wheel, the way `auditwheel` repairs a Linux wheel; this
  recipe instead declares [`flet-libcpp-shared`](https://pypi.flet.dev/flet-libcpp-shared/) and
  shares the single copy Flet already puts in the APK. Upstream's wheel is about 1.1 MB against
  this one's 0.6 MB, and the difference is mostly that second C++ runtime.

  Pin the version if you want one pyzmq everywhere:

  ```toml
  dependencies = ["flet", "pyzmq==<the version in this recipe's meta.yaml>"]
  ```

  At an equal version this index wins: its wheels carry a build tag and PyPI's do not, and a
  build tag outranks its absence.

- **One socket used from two threads is a crash, not an exception.** Handing a socket over to
  another thread and never touching it again is legal; two threads using it at once is not, and
  the failure is a native abort with no traceback. When a helper can be reached from more than
  one thread, give it a `threading.local()` socket instead of a shared one.

- **Two contexts never meet over `inproc`, and nothing says so.** `connect()` on a name bound in
  a different context returns cleanly, and which end then hangs depends on which end connected.
  The connecting socket gets a pipe of its own, so a connected PUSH, PUB or PAIR `send()`
  succeeds and the message is simply never delivered; a PUSH that *bound* has no peer at all and
  blocks in `send()` instead. Either way it is a hang with no error, at one end or the other, and
  a single `Context.instance()` for the whole app is the fix.

- **Bind and connect order no longer matters, but the context does.** Older ZeroMQ guides insist
  the `inproc` bind must happen before the connect. With the libzmq the wheel bundles, a message
  sent before the bind was still delivered afterwards. Following the old advice costs nothing;
  believing it is the *only* rule is what leads people to two contexts.

- **A PUSH socket with no PULL peer blocks in `send()`.** Not an error, not a drop — the call
  waits for a peer to appear, and on the UI thread that is a frozen app. Set
  [`SNDTIMEO`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Socket.setsockopt) so it
  raises [`zmq.Again`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Again) instead.
  The same block happens once the queue fills, and it fills later than the documented default
  suggests: the send and receive high-water marks are 1000 each and add together over `inproc`,
  so the 2001st unread message is the one that waits.

- **A worker that leaves takes its queued jobs with it.** PUSH round-robins into a per-peer
  queue and then forgets about them: twenty jobs across two workers, with one leaving after its
  first, delivered eleven. That is the price of a queue that never asks who is busy. If losing
  jobs matters — or if job durations vary a lot — invert the flow so workers request work
  (a DEALER/ROUTER broker) rather than being fed.

- **PUB drops what nobody has subscribed to yet.** A subscriber that connects and starts
  receiving immediately got all 200 messages over `inproc`, where the subscription is in place
  by the time `connect()` returns, and none of them over TCP loopback. Code that looks correct on
  `inproc` can therefore lose its first messages the day someone changes the endpoint to `tcp://`.

- **`term()` waits for open sockets; `destroy()` closes them.**
  [`ctx.term()`](https://libzmq.readthedocs.io/en/latest/zmq_ctx_term.html) called with a socket
  still open does not return — it unblocked the instant that socket was closed — and the default
  `LINGER` of -1 means a socket *closed* with a message still undelivered hangs `term()` for
  good. `ctx.destroy(linger=0)` closes the sockets for you and is the shutdown call, but it
  closes them from the calling thread: stop the workers and let each close its own sockets
  first, or it is the two-threads-one-socket crash again.

## Build notes (maintainers)

### Recipe shape

This is one self-contained recipe rather than a native-library recipe plus a consumer. pyzmq's
own CMake build fetches and compiles libzmq and libsodium and links both statically into the
single `_zmq` extension, so no pyzmq-side shared object has to be staged, relocated or
preloaded — the wheel is one binary. It is not free-standing on Android, where that binary lists
`libc++_shared.so` in `DT_NEEDED` and the `flet-libcpp-shared` host requirement supplies it; the
iOS build links only `libc++.1.dylib` and `libSystem`. The `meta.yaml` comments own the
individual build settings; do not restate them here.

PyPI also publishes official `android_24` wheels for pyzmq — at this version, cp313 for
`arm64_v8a` and `x86_64` only. pypi.flet.dev shadows them, and the recipe still supplies
`armeabi_v7a`, all three iOS slices, and 3.12 and 3.14 alongside 3.13. Check how far that
upstream coverage has grown before spending effort here; retiring the recipe becomes possible
only when it covers every slice the index serves.

### Upgrade hazards

The bundled library versions are pyzmq's, not the recipe's: `PYZMQ_LIBZMQ_VERSION` and
`PYZMQ_LIBSODIUM_VERSION` in the source tree's `CMakeLists.txt` decide what actually ships, so a
routine pyzmq bump can move libzmq underneath every behavioural claim on this page. The
connect-before-bind behaviour, the compiled-in transport list and CURVE support are all
properties of that build rather than of pyzmq or of the recipe.

Upstream's own Android wheels also make the version in `meta.yaml` load-bearing. pip ranks
candidates by version before it considers platform or build tags, so a newer pyzmq on PyPI
outranks anything this index holds at an older version, and an app silently moves to a wheel
set with no iOS slice, no `armeabi-v7a` and only the interpreters upstream builds for. Keep
this recipe at or ahead of PyPI's version, and re-read that wheel list at every bump.

### Re-verification checklist

- **Bundled versions and capabilities:** read `zmq.zmq_version()` and `zmq.has(...)` from the
  built wheel on device; the Transports section depends on both.
- **Android package layout:** the extension's suffix must match the target interpreter's
  `EXT_SUFFIX` — `_zmq.cpython-312.so` on 3.12, `_zmq.cpython-313-aarch64-linux-android.so` and
  its siblings from 3.13 on — and it must import from zipped site-packages. Add
  `extract_packages` to consumer guidance only if a real runtime filesystem read makes it
  mandatory, and include the failure symptom.
- **Android 16 KB alignment:** inspect every `PT_LOAD` segment of `_zmq`, since the max-page-size
  linker flags are set per-build and are easy to lose in a CMake argument reshuffle. Build 1
  aligns all three segments at `0x4000` on all ten Android wheels.
- **iOS file type:** `_zmq` must be `MH_DYLIB` on every iOS slice. serious_python makes each
  extension an xcframework that SwiftPM *links*, and `ld` rejects a Mach-O bundle —
  `unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB can be linked)` — so a slice that
  regressed to a bundle would fail at app build time, not at import. forge converts bundles on
  the way out, which is what keeps this true; check it rather than assume it.
- **Cython:** upstream asks for `cython>=3.0.0` with no ceiling, so the build takes whatever is
  current. Cython 3.3 rejects re-annotating an already-declared name, which older releases of
  `zmq/backend/cython/_zmq.py` do — the failure is `'hint' redeclared` / `'c_addr' redeclared`
  at Cython time, on every slice at once. If a bump ever reintroduces that pattern, take the
  upstream fix rather than pinning Cython back.
- **Size:** re-measure the compressed and unpacked ranges from the resulting wheels rather than
  scaling old figures.

### Coverage gaps

The device tests cover importing `zmq` and one `inproc` PAIR round trip. They do not exercise
PUSH/PULL, PUB/SUB, `zmq.Poller`, multi-threaded workers, the TCP or IPC transports, CURVE,
`zmq.asyncio`, or context termination. Every timing above was measured on desktop macOS and is
labelled as such; none of them should be repeated as a device figure.
