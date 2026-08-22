# gRPC loopback RPC

A [gRPC server](https://grpc.github.io/grpc/python/grpc.html#grpc.server) and gRPC's own
[client](https://grpc.github.io/grpc/python/grpc.html#grpc.Channel) inside one Flet app on
`127.0.0.1`, with **no `.proto` file, no protoc and no generated `_pb2_grpc.py`** — the
messages are raw `bytes` and the serializers are the identity function. Sitting between the
two is a byte-counting TCP relay the app starts itself, so gRPC's framing overhead and its
compression are both visible on screen rather than taken on trust. A slider sets the payload
size; let it go and the six checks run again.

Nothing leaves the device: no external host, no DNS lookup, no TLS handshake, no bundled
asset and nothing written to storage. What the screen reports is the RPC stack itself
working.

The no-codegen shape is the point. `grpc.protos()` cannot work on device — it needs
`grpcio-tools`, which bundles protoc and is not on this index — so this is the one schema
story that is self-contained. See [Things to know](../../README.md#things-to-know) in the
recipe README for the two alternatives when you do want a schema.

What it demonstrates:

- **A service registered without any generated code.**
  [`grpc.method_handlers_generic_handler`](https://grpc.github.io/grpc/python/grpc.html#grpc.method_handlers_generic_handler)
  plus
  [`unary_unary_rpc_method_handler`](https://grpc.github.io/grpc/python/grpc.html#grpc.unary_unary_rpc_method_handler)
  and
  [`unary_stream_rpc_method_handler`](https://grpc.github.io/grpc/python/grpc.html#grpc.unary_stream_rpc_method_handler),
  each given `request_deserializer=raw` and `response_serializer=raw`, against a client
  built with `channel.unary_unary(path, request_serializer=raw, response_deserializer=raw)`.
  `raw` returns its argument. That is the entire schema layer.
- **A unary call whose answer the app can disprove.** The server returns the length *and*
  the SHA-256 of exactly the bytes that arrived, and the client compares both against its
  own — so a truncated or mangled message shows as a red row rather than a plausible number.
- **A server-streamed response**, every frame recomputed and compared, and the frame count
  checked against the count that was asked for.
- **A deadline that really expires**: `timeout=0.15` against a two-second handler comes back
  as `DEADLINE_EXCEEDED · 'Deadline Exceeded'`. The handler polls
  `context.is_active()` rather than sleeping straight through, so it releases its slot in the
  four-thread servicer pool the moment the client gives up — otherwise a few slider drags
  leave every later check queued behind an RPC nobody is waiting for.
- **An [`abort`](https://grpc.github.io/grpc/python/grpc.html#grpc.ServicerContext.abort)
  arriving with its code *and* its details intact**, as
  `FAILED_PRECONDITION · 'payload rejected on purpose'`.
- **Metadata round-tripping**: the client sends `x-req`, the handler reads it out of
  `context.invocation_metadata()` and hands it back through `set_trailing_metadata`.
- **gzip, weighed on the wire.** The same payload goes out twice, once with
  `compression=grpc.Compression.NoCompression` and once with `grpc.Compression.Gzip`, and the
  relay's counters are the only difference the app trusts. Measured on desktop at 8 KiB:
  `8,192 B → 8,250 B plain, 443 B gzipped`. gRPC's whole menu is `NoCompression`, `Deflate`
  and `Gzip` — no zstd, no brotli.

Above the checks it reports what a phone answers differently from a laptop:

- **The trust store**, as `trust store 264,440 B, 130 certificates`, read with
  `pkgutil.get_data("grpc._cython", "_credentials/roots.pem")` — the exact call the C core
  makes for itself when it needs default roots. This is the single most valuable line to read
  on a real device, because if packaging ever drops that file the failure otherwise lands at
  TLS handshake time and reads like a server problem. A failure here is rendered as
  `trust store UNREADABLE — …` rather than raised: an exception escaping `main` gets a Flet
  crash screen, which would bury the answer.
- **The OS threads gRPC's C core added** while the server and the channel were built, which
  is only answerable where `/proc/self/task` exists — Android. iOS and desktop print
  `OS thread count needs /proc, so Android only` instead of guessing. The threads are
  invisible to `threading.enumerate()` either way, and the count brackets both the server and
  the channel because whichever comes first is what starts the pool.
- **First-call and warm per-call milliseconds**, and the channel's connectivity transitions
  (`IDLE → CONNECTING → READY`) collected through
  [`channel.subscribe`](https://grpc.github.io/grpc/python/grpc.html#grpc.Channel.subscribe),
  because the synchronous `Channel` has no `get_state()` — that exists only on
  `grpc.aio.Channel`.

Two shapes in the source are there because getting them wrong fails quietly:

- **The server is parked in a module-level dict, not left in `start`'s locals.**
  `grpc._server._Server.__del__` sets a `server_deallocated` flag that the serving thread
  acts on, so a server whose last reference was a local variable stops serving shortly after
  `start` returns — and every later call comes back `UNAVAILABLE … failed to connect to all
  addresses`, naming the address rather than the mistake. Measured: without the reference the
  initial render is green and every run after it collapses to `UNAVAILABLE`.
- **The work runs in
  [`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), and catches
  `grpc.RpcError` by name.** The blocking API releases the GIL for the whole of a call, so a
  worker thread is the right home and the UI stays live — but `run_thread` never retrieves
  the worker's future, and `RpcError` is the exception a networking app raises constantly. An
  escaping one would produce no crash, no log line and no clue. The worker ends with an
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) for the
  same reason: Flet's auto-update fires around event handlers, not inside a thread. The
  slider is disabled in the *handler* and read back as the re-entrancy guard, because
  `run_thread` only schedules.

Each check is timed on its own and its own failure contained, so one broken path shows as one
red row instead of hiding the other five. The footer adds the six figures exactly as
displayed.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

The lines to read first on device are the two in the header: a port in
`serving 127.0.0.1:…` means the OS accepted the listening socket, and
`trust store 264,440 B, 130 certificates` means grpc's own CA bundle survived packaging.
Neither can be established from a desktop run. Nothing has to be configured for the sockets
on Android — `flet build` grants `android.permission.INTERNET` by default.

What this app deliberately does **not** settle is whether hostname resolution works: a
`127.0.0.1` literal skips DNS entirely. See the DNS bullet in the
[recipe README](../../README.md#android).
