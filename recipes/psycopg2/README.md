# psycopg2

[`psycopg2`](https://www.psycopg.org/docs/) is the long-established PostgreSQL driver for
Python: a C extension wrapped around
[libpq](https://www.postgresql.org/docs/17/libpq.html), the client library PostgreSQL itself
ships. In these wheels libpq is linked *into* the extension, so the driver arrives as a single
compiled file carrying its own PostgreSQL 17.5 client, TLS included —
`psycopg2.extensions.libpq_version()` reads that number back on the device.

Three names sit close together. This page is about `psycopg2`; `psycopg2-binary` is the same
code packaged with its own libpq for desktop installs, and
[`psycopg`](https://www.psycopg.org/psycopg3/docs/) — psycopg 3 — is a separate project with a
different API.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "psycopg2",
]

[tool.flet.ios]
dependencies = [
    "psycopg2",
]
```

**The platform tables are not a style choice.** psycopg2 publishes wheels for exactly one
desktop: release 2.9.12 on PyPI is six `win_amd64` wheels and one `.tar.gz`. Everywhere else
that sdist gets built, and it shells out to `pg_config` and stops with `Error: pg_config
executable not found.` — measured 2026-08-21 on macOS with no PostgreSQL installed. A top-level
`"psycopg2"` belongs to *your own* project environment, so `uv sync` — which `uv run flet build
apk` performs before flet starts — walks into that. Resolution is not the step that fails:
`uv lock` succeeds and the error arrives when the sdist is built. Under the platform tables the
requirement never reaches your machine at all; flet
[appends](https://flet.dev/docs/publish/#app-dependencies) those entries to the project list and
passes the result to the device build, which resolves them against the mobile index.

The cost is worth stating plainly: **psycopg2 is then absent from `flet run` on your desktop**,
because nothing outside a `flet build` for Android or iOS reads those tables. Guard the import
so a desktop run explains itself instead of raising, as the
[`libpq-probe`](examples/libpq-probe) example does. For a desktop run that needs the driver
anyway, add `psycopg2-binary` to a dev dependency group — same import name, its own libpq, and
see [Other considerations](#other-considerations) for what that changes.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`libpq-probe`](examples/libpq-probe) — reports the libpq inside the wheel and the features
  compiled into it, normalises a connection string, and shows what a connection that cannot be
  made raises.

## Usage in a Flet app

```python
import psycopg2

conn = psycopg2.connect(
    "postgresql://app@db.example.com/orders"
    "?sslmode=verify-full&sslrootcert=/abs/path/roots.pem&connect_timeout=5"
)
with conn, conn.cursor() as cur:
    cur.execute("select id, celsius from readings where at > %s", (since,))
    rows = cur.fetchall()
conn.close()

table.rows = [
    ft.DataRow(cells=[ft.DataCell(ft.Text(str(value))) for value in row]) for row in rows
]
```

The second argument to
[`execute`](https://www.psycopg.org/docs/usage.html#passing-parameters-to-sql-queries) is how
values reach the server; formatting them into the string yourself is the
[injection](https://www.psycopg.org/docs/usage.html#sql-injection) everyone means.
[`with conn`](https://www.psycopg.org/docs/usage.html#with-statement) is a *transaction*, not
the connection's lifetime — it commits or rolls back and leaves the connection open, so the
`close()` still matters. Rows come back as ordinary tuples, ready for
[`ft.DataTable`](https://flet.dev/docs/controls/datatable/).

### Storage

libpq wants filesystem paths, and absolute ones. A CA bundle or client certificate that ships
with the app is an [asset](https://flet.dev/docs/cookbook/assets): build its path from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir). One
bundle is in your payload already — `certifi` arrives with Flet — so `sslrootcert=certifi.where()`
needs no asset at all. libpq's own defaults, `~/.pgpass` and `~/.postgresql/root.crt`, resolve
against a home directory a mobile app has no reason to trust; name every path explicitly.

An outbox of statements to replay when the network returns, or a cached result set the user
expects to survive a restart, belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
with [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for what you can fetch again. A local store that has to answer queries wants a local database
rather than a file of rows; [`apsw`](../apsw) and [`duckdb`](../duckdb) have recipes here.

### Threading

`psycopg2.threadsafety` is 2, and the two shapes upstream
[documents](https://www.psycopg.org/docs/usage.html#thread-and-process-safety) are not
equivalent. A connection per thread runs in parallel sessions; one connection with a cursor per
thread *serializes* onto a single session, and onto a single transaction unless the connection
is in autocommit — so two taps that each open a cursor do not overlap, the second waits.

Either way every call blocks the thread it is made on — the connect, the `execute`, the fetch —
so put them in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update):

```python
def load():
    try:
        with CONNECTION.cursor() as cur:
            cur.execute("select id, celsius from readings limit 100")
            table.rows = [...]
    except psycopg2.Error as error:
        status.value = str(error)
    page.update()

page.run_thread(load)
```

In an [async app](https://flet.dev/docs/cookbook/async-apps), hand the same blocking work to
`asyncio.to_thread`; psycopg2's asynchronous mode
([`set_wait_callback`](https://www.psycopg.org/docs/extensions.html#psycopg2.extensions.set_wait_callback)
with [`wait_select`](https://www.psycopg.org/docs/extras.html#psycopg2.extras.wait_select))
drives libpq from a `select()` loop of its own and does not join Flet's. Treat a connection as
short-lived either way: the OS suspends your process when the user switches away, so expect the
first statement after a resume to raise, rather than reaching for
[`ThreadedConnectionPool`](https://www.psycopg.org/docs/pool.html#psycopg2.pool.ThreadedConnectionPool).
That failure shape has not been measured on a device here.

### Connection strings and TLS

A phone holding a database password and speaking the PostgreSQL protocol straight to your
server is usually the wrong shape for an app; put an HTTPS API in front of the database and
keep the driver behind it. When you connect directly anyway — a network you control, a
diagnostic tool, a prototype — encryption is decided entirely by keywords you write, and the
default is not the safe one.

| `sslmode` | what the session gets |
| --- | --- |
| `disable`, `allow`, `prefer` | plaintext is accepted; `prefer` is what applies when you say nothing |
| `require` | encrypted, and whoever answered is trusted |
| `verify-ca` | encrypted, and the certificate chain is checked |
| `verify-full` | encrypted, chain checked, and the hostname must match |

**TLS is compiled in; GSSAPI is not.** libpq validates these keywords while parsing, before any
socket, so the binary answers for itself: ask for GSSAPI encryption and it refuses with
`OperationalError: gssencmode value "require" invalid when GSSAPI support is not compiled in`,
while every `sslmode` above survives parsing and the attempt proceeds to the network. That
refusal string is in every published wheel and its `sslmode` counterpart is in none of them —
checked with `strings` on 2026-08-21. Nothing else changes: with GSSAPI absent libpq's
`gssencmode` default is `disable`, so a connection string that never mentions it behaves
normally. Both questions run as recipe tests and in the
[`libpq-probe`](examples/libpq-probe) example.

`verify-ca` and `verify-full` need roots to check against, so pass `sslrootcert` explicitly.
Give `connect_timeout` a number too: left out, libpq waits for the operating system to give up
on the socket, which on a phone that just walked out of Wi-Fi range is a UI hung for as long as
the kernel likes. It is counted per host, so a string listing three can take three times what
you wrote. Android builds already carry `android.permission.INTERNET` in Flet's generated
manifest, so the connection itself needs nothing added to `pyproject.toml`. Android's
cleartext-traffic restriction is not a second gate on top of `sslmode`: it is enforced by the
platform HTTP stacks, not by the raw socket libpq opens.

### App size

The Android payload swings by roughly a factor of eight depending on which Python you bundle.
Measured from the published wheels on 2026-08-21, across every Android ABI (four on 3.12, three
after it) and the three iOS slices:

| bundled Python | Android wheel | iOS wheel |
| --- | --- | --- |
| 3.12, 3.13 | 0.25–0.29 MB compressed, 0.56–0.77 MB unpacked | 1.63–1.77 MB compressed, 4.18–4.27 MB unpacked |
| 3.14 | 1.9–2.3 MB compressed, 3.8–6.1 MB unpacked | 2.0–2.2 MB compressed, 5.2–5.3 MB unpacked |

OpenSSL is the whole of that difference: on Android 3.12 and 3.13 the extension leaves its TLS
symbols to the OpenSSL the Flet Python runtime already loads, while on 3.14 and on iOS
throughout it carries a copy of its own. `flet build` bundles the newest Python it supports
unless told otherwise — 3.14 with Flet 0.86.5, including when `requires-python` says only
`>=3.10` — so [`--python-version`](https://flet.dev/docs/publish/#choosing-a-python-version) is
the lever, and it swaps the runtime for every package in the app rather than for this one.

Nearly all of either payload is the single compiled file, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth taking. On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI. These figures describe the package payload, not the exact amount
added to the final APK or IPA.

### Other considerations

`psycopg2-binary` is the practical stand-in for a desktop `flet run` and the API is identical,
but it is a different build of libpq and of OpenSSL, so it is not evidence about the device.
Measured here on macOS, its libpq reports 17.9 against the `flet-libpq` recipe's PostgreSQL in
these wheels, and it answers the GSSAPI question above with `GSSAPI encryption required but no
credential cache` rather than `not compiled in`. Put anything that opens a socket, negotiates
TLS or reads a version on a device or emulator/simulator before believing it.

## Things to know

- **A connection failure carries no SQLSTATE.** A refused port, a name that will not resolve
  and an expired `connect_timeout` all arrive as
  [`psycopg2.OperationalError`](https://www.psycopg.org/docs/module.html#psycopg2.OperationalError)
  with `pgcode` and `diag.sqlstate` both `None` — a SQLSTATE comes from a server, and no server
  answered. Branch on the exception class for connection trouble and keep
  [`psycopg2.errors`](https://www.psycopg.org/docs/errors.html) (`UniqueViolation`,
  `SerializationFailure`, …) for what a live session returns; both sit under `psycopg2.Error`,
  so one `except psycopg2.Error` still catches everything.

- **`adapt()` runs offline, and escapes as if it had no server.**
  [`adapt(value).getquoted()`](https://www.psycopg.org/docs/extensions.html#psycopg2.extensions.adapt)
  works with nothing connected, which makes it a good way to see what psycopg2 would send —
  `Decimal("19.99")` as `19.99`, a `list` as `ARRAY[1,2,3]`, a `timedelta` as an `interval`. It
  is not a way to *build* SQL: with no connection to say otherwise psycopg2 assumes
  `standard_conforming_strings` is off, so `b"\x00\x01\xff"` comes back doubled-backslash octal,
  `'\\000\\001\\377'::bytea`, not hex.
  [`psycopg2.sql`](https://www.psycopg.org/docs/sql.html) refuses outright —
  `Identifier("t").as_string(None)` raises `TypeError: argument 2 must be a connection or a
  cursor` — so a query cannot be composed and inspected ahead of time.

- **A type with no adapter raises rather than guessing.** `adapt({"a": 1})` raises
  `ProgrammingError: can't adapt type 'dict'`, and a bare `uuid.UUID` raises the same for
  `'UUID'`. Wrap the first in
  [`psycopg2.extras.Json`](https://www.psycopg.org/docs/extras.html#psycopg2.extras.Json) and
  call `register_uuid()` for the second; both are local and take no argument.
  `register_hstore` is not local — it reads an OID out of the server's catalog, so it *requires*
  a connection argument, and `register_hstore(None)` raises `ProgrammingError: no connection or
  cursor provided`.

## Build notes (maintainers)

### Recipe shape

The wheel is one C extension with libpq *inside* it. `flet-libpq` is declared under
`requirements.host_build`, so its archives reach the cross environment for the link without
becoming a `Requires-Dist`; the alternative — a shared libpq as a normal host requirement —
would put a second wheel into every consuming app for a library only this extension calls.
`mobile.patch` makes setup.py cooperate: it flips `static_libpq`, adds `PG_CONFIG` as a source
for pg_config's path, and appends the PostgreSQL support archives and OpenSSL to the link line.
The patch preamble owns the reasoning for each; `meta.yaml` comments own the settings.

**OpenSSL is not linked the same way on every leg, and the recipe does not decide it — the
support tree does.** The `openssl` host requirement resolves out of python-build's per-minor
tree, and those trees differ:

| leg | how OpenSSL arrives | evidence in the wheel |
| --- | --- | --- |
| Android 3.12, 3.13 | shared, from the Flet runtime (OpenSSL 3.0.15 on 3.12, 3.0.21 on 3.13) | `DT_NEEDED` names `libssl_python.so` and `libcrypto_python.so`; 113 undefined `OPENSSL_3.0.0` symbols |
| Android 3.14 | static, folded into the extension (OpenSSL 3.5.7) | no OpenSSL in `DT_NEEDED`; zero undefined OpenSSL symbols; `SSL_connect` and `TLS_method` are *defined*; the binary carries the string `OpenSSL 3.5.7 9 Jun 2026` |
| iOS, all legs | static, folded in | only `Python.framework` and `libSystem` are linked; OpenSSL source paths appear in the binary's strings |

The 3.14 Android runtime still ships `libssl_python.so`, and at OpenSSL 3.5.7 — the release the
extension folded in — so that leg carries a second copy alongside the one the `ssl` module
uses. CPython `dlopen`s extensions with `RTLD_LOCAL`, so the duplicate should not interpose, but
that has not been observed on a device here and no test would notice if it did. All Android legs
are `BIND_NOW`, so a symbol that stopped resolving fails the *import*, not some later call.

### Upgrade hazards

- **The patch is addressed at `PostgresConfig.__init__` and `finalize_options`.** A psycopg2
  release that reworks either — or replaces the `setup.py`/`setup.cfg` build — needs the patch
  rewritten, not refreshed.
- **The static link depends on flet-libpq's file names.** `libpgcommon.a` and `libpgport.a` are
  PostgreSQL's `*_shlib.a` archives renamed by that recipe's `build.sh`; a PostgreSQL bump that
  changes how they are produced breaks this link and nothing else notices.
- **Compiled-in features are decided in flet-libpq, and this page states them.** Its configure
  line carries `--with-openssl` and `--without-gssapi`.
- **A python-build bump can move a leg between the two OpenSSL columns above without touching
  this recipe**, which changes the Android size figures by a factor of eight and invalidates the
  App size table. Nothing in the build goes red when it happens.

### Re-verification checklist

- **Feature flags** are covered by `test_compiled_in_features`, which is the check to trust over
  the configure line. Its asymmetry is deliberate: a build *with* TLS contains no `sslmode … not
  compiled in` string at all, so the TLS half asserts that the option survived parsing rather
  than matching a sentence the library never emits.
- **libpq version:** read `psycopg2.extensions.libpq_version()` on device. Because libpq is
  static it must equal `psycopg2.__libpq_version__`; a divergence means something else is being
  loaded.
- **iOS file type:** the extension must be `MH_DYLIB`. An `MH_BUNDLE` is not linkable and stops
  `flet build` with *Unsupported mach-o filetype*.
- **OpenSSL linkage, per Python minor, not once:** rebuild the table above from the wheels
  (`readelf -d`, `readelf --dyn-syms`, `strings`); one leg proves nothing about the others. Its
  runtime column is a separate read — `strings` on `libcrypto_python.so` inside python-build's
  `python-android-dart-<version>-<abi>.tar.gz` for the release date flet pins.
- **Size:** re-measure compressed and unpacked from the wheels for every supported Python,
  rather than scaling these numbers.

### Coverage gaps

The device tests are four: the import, the DB-API exception hierarchy, a refused connection to a
closed local port, and the option-validation probes that pin `--with-openssl --without-gssapi`.
The import is worth more than it looks — `BIND_NOW` means it resolves every libpq symbol, and
every OpenSSL symbol on the legs that borrow them, or fails. Between them they reach libpq's
connect path only as far as the TCP refusal. **No TLS handshake, no authentication, no query,
no cursor and no value adaptation has ever run on a device here**, and nothing asserts which way
OpenSSL was linked — the last is the gap that matters, because it is the one a python-build bump
moves. The `libpq-probe` example covers option validation and the
adaptation half, but only when somebody builds it. Everything this page says about a real
session is upstream behaviour plus a static link, not a measurement.
