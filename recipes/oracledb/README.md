# oracledb

[`oracledb`](https://python-oracledb.readthedocs.io/) is Oracle's own driver for Oracle
Database, and the successor to `cx_Oracle`. It ships two implementations of the same DB-API
interface. **Thin mode** speaks Oracle Net directly from compiled Python extensions over an
ordinary socket. **Thick mode** hands the work to the Oracle Instant Client, a set of native
libraries Oracle publishes for servers and desktops — and not for Android or iOS.

So on a phone the driver is thin mode, permanently. Thin mode is the default and needs no
decision to use; what it needs is knowing where its edges are, which is most of this page.

## Install

Add oracledb to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "oracledb",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`thin-client`](examples/thin-client) — reports the loaded driver, takes connect strings
  apart, and shows exactly how a connection to nothing at all fails.

## Usage in a Flet app

Connect, bind by name, fetch:

```python
import oracledb

oracledb.enable_thin_mode()

with oracledb.connect(
    user="app",
    password=secret,
    dsn="tcps://db.example.com:1522/orclpdb1",
    tcp_connect_timeout=8,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("select name, price from products where id = :id", id=7)
        rows = cursor.fetchall()
```

A phone holding a database credential and a long-lived pooled connection is usually the wrong
shape for an app: an HTTPS API in front of the database keeps the credential off the device and
survives the OS suspending your process. Everything below assumes you have weighed that and
gone ahead anyway.

[`enable_thin_mode()`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.enable_thin_mode)
is not required — thin mode is what you get anyway — but it states the intent and turns a
later thick-mode call into an immediate, legible error instead of a library hunt.
`paramstyle` is `named`, so binds are `:id` in the text and keyword arguments in the call;
string-formatting them into the SQL is how you get an injection instead of a bind.

### Storage

Two files can matter, and both are ordinary paths the driver reads at connect time.

A [tnsnames.ora](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html#tns-aliases-for-connection-strings)
lets a connect string be a bare alias. Thin mode looks for it in
[`defaults.config_dir`](https://python-oracledb.readthedocs.io/en/latest/api_manual/defaults.html#oracledb.Defaults.config_dir),
which starts out as `TNS_ADMIN` from the environment and is therefore unset on a device. A
file shipped with the app belongs in the
[assets directory](https://flet.dev/docs/cookbook/assets); one written or downloaded at
runtime belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
oracledb.defaults.config_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
connection = oracledb.connect(user="app", password=secret, dsn="sales")
```

A wallet is the second. `wallet_location` names a *directory*, and thin mode reads
`ewallet.pem` from it for TLS material — that same durable directory is the right home, since
a wallet is not regenerable on the device. `sqlnet.ora` is a thick-mode file and is never
read, so anything configured there has to move into the connect string or the `connect()`
call.

Cached rows belong in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache).
For a local store that outlives the network, [`apsw`](../apsw) and [`duckdb`](../duckdb) have
recipes here.

### Threading

`oracledb.threadsafety` is `2`: the module and its connections may be shared between threads,
cursors may not. Sharing is safe rather than parallel — the thin protocol holds a
`threading.Lock` across each round trip, so two threads on one connection queue up. Give each
worker its own connection to overlap them, and never a shared cursor.

Everything on a connection blocks, starting with the connection itself: the default
`tcp_connect_timeout` is **20 seconds**, which is 20 seconds of frozen UI if you call
`connect()` from a handler. Pass a short one and move the call, and every query, into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread):

```python
def load():
    try:
        with CONNECTION.cursor() as cursor:
            rows = cursor.execute(QUERY).fetchall()
        table.rows = [render(row) for row in rows]
    except (oracledb.Error, OSError) as exc:
        status.value = str(exc)
    finally:
        button.disabled = False
        page.update()  # auto-update does not reach background threads
```

`run_thread` swallows what the worker raises, so an uncaught exception leaves the button
disabled and the spinner turning forever — put the re-enable in a `finally`, as above. The
alternative is [`connect_async`](https://python-oracledb.readthedocs.io/en/latest/user_guide/asyncio.html)
and `AsyncConnection`, thin-mode features that fit an
[async Flet app](https://flet.dev/docs/cookbook/async-apps) without a thread pool at all.

### Thick mode

Calling [`init_oracle_client()`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.init_oracle_client)
raises `oracledb.DatabaseError` with code **`DPI-1047`**, quoting the platform's own dlopen
error for `libclntsh` — `.so` on Android, `.dylib` on iOS, each name present as a string in
that platform's own `thick_impl`. No wheel carries the Instant Client and Oracle publishes no
mobile build of it, so nothing about this is fixable from the app. Until that call succeeds
[`clientversion()`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.clientversion)
raises too, with `DPY-2021`; call `enable_thin_mode()` at startup and the reply becomes
`DPY-2019`, thick mode refused because thin mode is already enabled, which is a clearer thing
to find in a crash report.

What thin mode cannot do is therefore what the app cannot do. Upstream's
[feature comparison](https://python-oracledb.readthedocs.io/en/latest/user_guide/appendix_a.html)
is the full list; the entries that most often decide an architecture are the SODA document
API, external authentication including Kerberos and RADIUS, Application Continuity and
Transparent Application Failover, Fast Application Notification, sharded databases, database
startup and shutdown, and Oracle's native network encryption — for which the thin-mode answer
is TLS. Named time zones are a smaller casualty with a specific error, `DPY-3022`.

### App size

A wheel is 1.90–2.34 MB compressed. Unpacked it is 4.63–4.70 MB on 32-bit `armeabi_v7a`,
6.18–6.52 MB on the other Android ABIs and 7.33–7.60 MB on iOS, measured across every published
slice on 2026-08-21. Nearly all of it is the four Cython extensions; 0.70 MB is Python source,
and there is no data directory to trim.

About a sixth — 0.78 MB on `armeabi_v7a` up to 1.28 MB on iOS — is `thick_impl`, the mode
that cannot run here, and it **cannot be removed**.
`oracledb/__init__.py` does `from . import base_impl, thick_impl, thin_impl` unconditionally,
so deleting it with [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup)
turns `import oracledb` into `ImportError: cannot import name 'thick_impl' from partially
initialized module 'oracledb'`.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's own wheel and the Python API is identical — but a
development machine with an Instant Client installed can enter thick mode, and then any of the
features listed above appears to work. Call `enable_thin_mode()` before your first connection
everywhere, desktop included, so the desk and the device run the same driver.

## Things to know

- **A connect string is one of four things, and the driver tells you which one it could not
  read.** Easy connect (`host:port/service`), a `tcps://` URL with query parameters, a whole
  `(DESCRIPTION=...)`, or a tnsnames alias. A bare alias with no `config_dir` set raises
  `DPY-4027: no configuration directory specified`; an alias that is not in the file raises
  `DPY-4000: unable to find "..." in .../tnsnames.ora`. Passing `user/password@host/service`
  as the `dsn` raises `DPY-4018: cannot parse connect string` — that form is
  [`ConnectParams.parse_dsn_with_credentials`](https://python-oracledb.readthedocs.io/en/latest/api_manual/connect_params.html#oracledb.ConnectParams.parse_dsn_with_credentials),
  which splits it into the three arguments `connect()` wants.

- **A host that does not resolve is not an `oracledb.Error`.** Name resolution happens before
  the driver's own error handling, so a bad name arrives as `socket.gaierror` and walks
  straight past `except oracledb.Error`. A refused or unreachable port does go through the
  driver: `oracledb.OperationalError` with `DPY-6005: cannot connect to database
  (CONNECTION_ID=...)` and the OS reason appended — `Connection refused`, or `timed out` once
  `tcp_connect_timeout` expires. Catch `(oracledb.Error, OSError)` and you have both. That
  `CONNECTION_ID` is the driver's own tracing identifier, the string to quote to a DBA.

- **Thin mode is not pure sockets: it needs `cryptography`.** Authentication is encrypted
  whatever the protocol, so the driver checks that import as the first act of building a
  connection and raises `DPY-3016` if it failed — which puts the failure on the first
  `connect()`, not at `import oracledb`. It arrives with the wheel; do not add it to a
  `[tool.flet.cleanup]` list.

- **Reach a public database over `tcps`, and hand the driver a trust store.** With no
  `ssl_context` and no wallet, the driver's trust material is whatever
  `ssl.create_default_context()` finds — a system CA store a mobile runtime may not have, and
  the failure lands at handshake looking like a server problem. Pass one yourself:
  `ssl_context=ssl.create_default_context(cafile=certifi.where())`, `certifi` reaching the app
  through Flet's own `httpx` dependency. The driver imports `certifi` only to decide whether
  to read the macOS keychain instead, in a branch guarded by `sys.platform == "darwin"` that
  no device takes; it never calls `certifi.where()` for you. Read out of the driver's context
  construction, not settled by a handshake on a device here.

- **The network permission is already there on Android.** Flet's generated manifest includes
  `android.permission.INTERNET`, which is what the driver's socket needs, so
  [`[tool.flet.android.permission]`](https://flet.dev/docs/publish/android/#permissions) stays
  out of it. Android's cleartext-traffic restriction is enforced by the platform HTTP stacks
  rather than by raw sockets, so it is not what stands between an unencrypted Oracle Net
  connection and the wire — `tcps` is.

## Build notes (maintainers)

### Recipe shape

The sdist is self-contained, so the default Python-package path builds it as it is: ODPI-C
and nanoarrow are vendored in its own tree — ODPI-C 6.0.0 and nanoarrow 0.8.0 at 4.0.1, both
of which the built extensions still carry as version strings. `setup.py` names only the four
`.pyx` files (`base_impl`, `thin_impl`, `thick_impl`, `arrow_impl`) as sources; the C reaches
the compiler through `cdef extern from "impl/thick/odpi/embed/dpi.c"` and the nanoarrow
include directory, so each extension is one compilation unit. The one native library involved
— the Oracle Client — is dlopened at runtime rather than linked. No native-library recipe
precedes it and there is nothing to patch.

### Upgrade hazards

**`thick_impl` has to keep cross-compiling even though it can never run.** It is imported
unconditionally by `oracledb/__init__.py`, so a release that fails to build it — or a
well-meant attempt to skip it — breaks `import oracledb` outright rather than degrading to
thin mode. It is also the extension that compiles the vendored ODPI-C C sources rather than
only Cython output, which makes it the likeliest casualty of a toolchain change.

The runtime dependencies are `cryptography` and `typing_extensions`. The first is a recipe
here and the first connection fails without it; a release that raises its floor past what
pypi.flet.dev serves for a given Python fails at app-build time, not here.

### Re-verification checklist

- **Four extensions in every wheel:** `base_impl`, `thin_impl`, `thick_impl` and `arrow_impl`,
  and on iOS all four must be `MH_DYLIB` (`otool -h` filetype 6). A build-system change that
  produced `MH_BUNDLE` instead would pass forge and fail later, at `flet build`.
- **`thick_impl` links nothing it cannot find:** its only recorded dependencies should be
  libpython and the platform C runtime. If `libclntsh` ever becomes a link-time dependency
  rather than a dlopen, `import oracledb` stops working on device.
- **Thin mode is still the default,** and `init_oracle_client()` still fails as a catchable
  `oracledb.Error` rather than a crash.
- **The connection-failure contract:** `DPY-6005` from a refused port, and `socket.gaierror`
  still escaping unwrapped from name resolution. Both are consumer-facing claims above, and
  either can move in a minor release.
- **`getpass.getuser()` stays guarded:** the driver calls it once at import to fill
  `defaults.osuser`, inside a bare `except`. iOS has no `pwd` module, so a narrowed guard
  there breaks `import oracledb` on iOS only.
- **Android package layout:** test from zipped site-packages.
- **Size:** re-measure both ranges and the `thick_impl` share from the wheels themselves.

### Coverage gaps

The device tests do two things: import the package, which loads all four extensions, and
attempt one connection to an address where nothing is listening. So `thick_impl` and
`arrow_impl` are proven to *load* and no more, and `base_impl` only as far as parsing one
easy-connect string.

The connection test is weaker than it reads. It accepts any `oracledb.Error`, and the first
act of `connect()` is the `cryptography` check — so if that import ever failed on device the
test would catch `DPY-3016` and stay green with no socket opened at all. Asserting `DPY-6005`
rather than the base class is what would make it prove the network path ran.

No real server is involved anywhere, so authentication, TLS, statement execution, fetch,
LOBs, the Arrow path and connection pooling are unexercised on device, as is the `DPI-1047`
thick-mode failure. The `thin-client` example covers the parser, `tnsnames.ora` resolution,
the thick-mode error and the failure classes — but only when somebody builds it.
