# thrift telemetry RPC

A Thrift service defined in [`telemetry.thrift`](telemetry.thrift), the Python code the
Thrift compiler generated from it in [`src/telemetry/`](src/telemetry), and a Flet app that
calls it. The app starts the service on `127.0.0.1` inside itself, so it runs with no
backend: it sends a batch of sensor readings through a real TCP socket and shows the
summary that comes back.

What it demonstrates:

- **The client setup to copy.** `submit()` in [`src/station.py`](src/station.py) is the
  part a real app keeps: a `TSocket` with a timeout, wrapped in a `TFramedTransport`,
  speaking `TBinaryProtocolAccelerated`. Point it at your own host and port, and match
  your server's transport, framed or buffered. Everything else in that file is the
  stand-in server, the sample readings and the codec benchmark.
- **Errors arrive as exceptions.** The second call includes an impossible temperature. The
  server raises `InvalidReading`, which the IDL declares, and the client receives it as a
  Python exception with its fields intact.
- **The native codec, measured on your device.** The table serializes and deserializes the
  `submit` payload in each protocol, once with the C++ `fastbinary` codec ("native") and
  once with thrift's pure-Python code ("pure"). The line under the app bar says which one
  the app loaded; "pure Python only" means it was built without this recipe's wheel.
- **Network calls off the UI thread.** Each pass runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and
  ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs.

The throughput figures are the best of several short, alternating native and pure windows,
and still vary from run to run with whatever else the device is doing. The gain depends on
the message too: this batch of readings, with its lists and maps, gains far more than a
small flat struct would.

If the server cannot be reached, the RPC lines show the `TTransportException` instead —
the same thing you will see when pointing `submit()` at a host that is down.

## Regenerating the Thrift code

`src/telemetry/` is generated. After editing the IDL, regenerate it on your computer with
the compiler whose version matches the `thrift` pin in `pyproject.toml`; the app ships only
the generated Python, never the compiler:

```bash
thrift --gen py -out src telemetry.thrift
rm src/__init__.py src/telemetry/Telemetry-remote
```

The second line removes what the compiler writes besides the package: an empty
`src/__init__.py` and a command-line client script.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
