# pymssql

[`pymssql`](https://pymssql.readthedocs.io/) is the Microsoft SQL Server driver: a DB-API 2.0
interface over [FreeTDS](https://www.freetds.org/), the free implementation of the TDS wire
protocol that SQL Server speaks. FreeTDS 1.4.27 is linked into the wheel — the version
`pymssql.get_freetds_version()` reads back — so a Flet app carries the whole client in two
compiled extensions and needs nothing installed on the device.

Talking to a database straight from a phone means a database credential shipped inside the app
and a socket the OS suspends whenever the user switches away; an HTTPS API in front of the
server is the usual shape. The rest of this page assumes you want the driver anyway.

## Install

Add pymssql to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pymssql",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`freetds-probe`](examples/freetds-probe) — reports the FreeTDS build, logs in to a socket in
  its own process to show what the handshake puts on the wire, and prints the exception a real
  connection raises.

## Usage in a Flet app

Connect, query, and put the rows into a Flet control:

```python
import pymssql

with pymssql.connect(server="10.0.0.5", port=1433, user="app", password=secret,
                     database="sales", tds_version="7.4",
                     login_timeout=5, timeout=15) as connection:
    cursor = connection.cursor(as_dict=True)
    cursor.execute("SELECT id, name FROM parts WHERE bin = %s", (bin_id,))
    rows = cursor.fetchall()

listing = ft.ListView(controls=[ft.Text(row["name"]) for row in rows])
```

`login_timeout` and `timeout` are worth setting every time: their defaults are 60 seconds and *no
limit*, which on a phone means a connection attempt that blocks a worker for a minute and a query
that never comes back when the network drops mid-result. `tds_version` earns its place for a
subtler reason — without it `login_timeout` is not binding, and a peer that opens the TCP
connection and then stalls blocks the worker for good. **Things to know** has the measurement.
[`as_dict=True`](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html#pymssql.Connection.cursor)
returns rows as dictionaries instead of tuples, which survives a `SELECT` list changing order.

### Storage

The driver keeps nothing on disk. The one file worth writing is a
[`freetds.conf`](https://www.freetds.org/userguide/freetdsconf.html), because it is the only way
to reach several settings the Python API does not expose — see **Encryption** below. Write it
into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
and name it in the environment before connecting:

```python
os.environ["FREETDSCONF"] = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "freetds.conf")
```

FreeTDS re-reads that file on every connection, so setting the variable once at startup is
enough and rewriting the file takes effect without a restart. Without the variable nothing is
read at all: the other candidates are `$FREETDS/etc/freetds.conf`, `~/.freetds.conf` — which no
device has — and a fallback compiled into the wheel that is the build machine's own path. A
certificate bundle ships with the app instead, so it belongs in the
[assets directory](https://flet.dev/docs/cookbook/assets), addressed through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
When a connection misbehaves, point `TDSDUMP` at a path under
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
and FreeTDS traces there, naming every setting it used and where it came from.

### Threading

pymssql reports `threadsafety = 1`: the module is safe to share, a connection is not. Give each
worker its own connection, or put one connection behind a `threading.Lock`.

FreeTDS releases the GIL around the calls that block — the connect, the query, and each row
fetch — so [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
keeps the UI moving while a query is outstanding. Catch exceptions inside the worker and finish
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

`login_timeout` looks per-connection and is not: `connect()` pushes it into DB-Library, where it
applies to the whole process, so two workers that disagree about it end up with whichever value
ran last. `pymssql.set_max_connections()` is process-wide too. Decide both once at startup.

### Encryption

**TLS is compiled in, and the driver says so on the wire.** Every TDS login opens with a
PRELOGIN packet whose encryption byte states what the client can do, and a build without TLS can
only answer `NOT_SUP`. This one answers `OFF` — *I can encrypt, you decide* — and when the server
says it has a certificate, FreeTDS opens a handshake offering TLS 1.3 and 1.2. Those bytes were
read on desktop; the `freetds-probe` example reads them again on the device.

**`connect(encryption="require")` does not require anything.** pymssql hands the value to
DB-Library's `DBSETLENCRYPT`, which FreeTDS leaves unimplemented — it returns a failure code
pymssql does not check — so the login proceeds at the default level with the argument discarded.
Against a server that answers "no encryption here", the login packet goes out in clear with the
user name, host name and application name readable and the password under the
[nibble swap and XOR with `0xA5`](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-tds/773a62b6-ee89-4c02-9e5e-344882630aac)
that MS-TDS specifies — a reversible scramble, not encryption; the `freetds-probe` example undoes
it in two lines. The platform will not stop it either: Flet's generated Android manifest carries
`android.permission.INTERNET`, which is all the socket needs, and the cleartext-traffic policy
that would otherwise object is enforced by Android's HTTP stacks — a raw TDS socket is not one
of them.

The setting that works lives in the conf file, together with the certificate check — FreeTDS
loads trust roots and checks the hostname only when a `ca file` is configured, so an
unconfigured TLS session is encrypted but unauthenticated:

```python
roots = os.path.join(os.getenv("FLET_ASSETS_DIR", "assets"), "roots.pem")
with open(os.environ["FREETDSCONF"], "w") as handle:
    handle.write("[warehouse]\nhost = sql.internal.example\ntds version = 7.4\n"
                 f"encryption = require\nca file = {roots}\n")

connection = pymssql.connect(server="warehouse", port=1433, user="app", password=secret)
```

The section name becomes the `server` value. Keep the port in the `port` argument: pymssql
appends it to the server string, and the appended value beats whatever `port` the conf file
sets.

### Parameters and types

`%s` is not a bound parameter. pymssql builds the SQL text on the device and sends a finished
statement, so
[`cursor.execute`](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html#pymssql.Cursor.execute)
is quoting, not binding, and that quoting is the whole of the injection defence — always pass
values as the second argument. What each Python type becomes:

| Passed in | Sent as |
| --- | --- |
| `str` | `N'…'`, with every `'` doubled |
| `int`, `float`, `Decimal` | the number, unquoted and unrounded |
| `bool` | `1` or `0` |
| `bytes` | `0x…`, a hex literal — but ASCII bytes with no NUL are sent as a quoted string instead, so `b"abc"` arrives as `'abc'`; `bytearray` always takes the hex path |
| `None` | `NULL` |
| `datetime` | `'…'` truncated to **milliseconds**, unless the connection was opened with `use_datetime2=True` |
| `date`, `time` | `'2026-08-21'`, `'12:30:45.000000'` |
| `tuple`, `list` | `(a,b,c)` — which is what makes `WHERE x IN %s` work |
| anything else | `ValueError: Unsupported parameter type: <class 'set'>` |

A timezone-aware `datetime` is the trap in that table: a UTC value loses its marker completely
and arrives looking naive and local, while a fixed offset is appended as text, which only some
column types accept. Convert to naive UTC before the call and keep the zone in your own code.

**Keep every `%` out of the SQL text and put your wildcards in the parameter.** Only `%s` and
`%d` are placeholders, matched anywhere in the string, quotes included — so with a parameter
tuple present the `%s` inside `LIKE '%sale%'` counts as one. Usually the placeholders then
outnumber the parameters and `execute` raises `ValueError: more placeholders in sql than params
available`; when the counts happen to line up nothing is raised at all and the statement leaves
as `LIKE 'N'v'ale%'`. Doubling to `'%%sale%%'` does not rescue it, because the second `%` still
stands in front of the `s`. `LIKE %s` with `("%sale%",)` is the form that works, and a `%`
followed by anything but `s` or `d` — `LIKE 'total%'` — was never in danger.

### App size

Expect approximately 0.45–2.5 MB compressed and 0.95–6.7 MB unpacked, and check which end your
build lands on: the Python version moves it further than the architecture does. The Android
wheels for CPython 3.12 and 3.13 borrow OpenSSL from the Python runtime and come to 0.45–0.51 MB
compressed; every other slice links OpenSSL in and runs 1.9–2.5 MB. The two extensions are 77% of
the smallest slice and 97% of the largest, `_mssql` alone accounting for 59% and 93% of those, so
there is nothing worth taking out of this wheel.

Leave the default cleanup on and there is nothing else to do. `flet-libfreetds`, which
pymssql's wheel requires, holds nothing your app runs: 6.10 MB of `opt/lib/libsybdb.a` and
`opt/lib/libct.a` plus 0.13 MB of headers on `arm64_v8a`, already folded into `_mssql` at link
time and never opened afterwards. Flet's
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) deletes `**.a` from
site-packages by default, so those archives do not reach the device — you pay the download and
the build-time disk rather than app size. Turn cleanup off and all 6.1 MB ships. There is no
`[tool.flet.cleanup]` glob worth adding for it: the default already covers `.a`.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI. These are payload figures, not the exact growth of the APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel, which carries its own FreeTDS build — the version string
happens to match today, but the two were configured separately. Your desk also has a real home
directory, and `~/.freetds.conf` is in FreeTDS's search path on every platform: a protocol
version or an encryption setting picked up from there makes a connection behave one way at your
desk and another on the phone, with nothing in either place saying so. (The `/etc/freetds.conf`
of the FreeTDS user guide is in play for neither wheel — both compile in their own build
machine's path.) Validate against the server on a device.

## Things to know

- **A failed connect reports a number that may belong to an earlier failure.** The exception is
  `pymssql.OperationalError` and `args[0]` is a `(number, message bytes)` pair, but that number
  is only replaced by an error of *higher* severity and every connection failure is severity 9,
  so the first failure in the process fixes it: a refused connection after an earlier hung-up one
  reported `20017` above a message naming `20009` twice. Match on the class and read the text.

- **Without `tds_version`, `login_timeout` is not a bound.** No protocol version is pinned into
  the build, so an address is tried as TDS 7.4 and then as TDS 5.0. When the peer refuses the
  connection or swallows the SYN, that costs only a duplicated message: a TEST-NET-1 address
  came back in exactly `login_timeout` seconds at 2, 3 and 6, pinned or not. When the peer
  *completes* the TCP handshake and then says nothing — a captive portal, a middlebox, a load
  balancer with no backend — `connect()` retries the version list in a loop and never returns at
  all: desktop attempts at `login_timeout` 1, 3 and 4 were still blocked when killed at 60, 30
  and 180 seconds. Passing any `tds_version` to
  [`connect`](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html#functions) ends it —
  `"7.4"` returned in 1.0, 3.0 and 8.0 seconds for `login_timeout` 1, 3 and 8. Pin it, or set
  `tds version` in the conf file, and a stalled login can no longer strand a worker thread.

- **Count the error blocks, do not assume two.** The retry above appends a message per attempt,
  and the total depends on how far the login got: a name that will not resolve produced one
  `DB-Lib error message` block, a refused port two, and a server that answered PRELOGIN and then
  hung up three. Parse none of this — read the text and match on the exception class.

- **Two argument mistakes escape `pymssql.Error` entirely.** An unknown `tds_version` raises
  `pymssql._mssql.MSSQLException`, outside the
  [DB-API hierarchy](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html#exceptions) and
  not exported from the top-level module; an unknown `encryption` raises `ValueError`. Both come
  from constants in your own code, so check them at startup rather than widening an `except`.

- **The `server` string quietly outranks `port`.** pymssql appends `port` only when the string
  has neither a colon nor a backslash, so `"host:1433"` beats the argument, a named instance like
  `"host\\SQLEXPRESS"` drops the port and sends FreeTDS to SQL Browser on UDP 1434, and a bare
  IPv6 literal gets no port at all — write `"[::1]:1433"`. The comma form `"host,1433"` is taken
  as a hostname and fails to resolve, and `"a\\b\\c"` raises a bare `ValueError` out of pymssql's
  own string split.

- **A `with` block rolls back.** `connect()` defaults to `autocommit=False` and leaving the block
  closes the connection, which discards every uncommitted transaction — so a write not followed
  by `connection.commit()` is silently lost, the opposite of what that shape does with `sqlite3`.
- **Licensing:** both halves are LGPL. pymssql itself is
  [LGPL-2.1-or-later](https://spdx.org/licenses/LGPL-2.1-or-later.html), and the FreeTDS that
  [`flet-libfreetds`](../flet-libfreetds) statically links into its extension is
  **[LGPL-2.0-or-later](https://spdx.org/licenses/LGPL-2.0-or-later.html)** — the 1991 *Library*
  GPL, not 2.1, which is easy to misread. FreeTDS also ships plain-GPL code under `src/pool` and
  `src/apps`; this build excludes both, so none of it is in the wheel. Because FreeTDS is linked
  statically there is no separate library file to replace, which is what LGPL section 6 asks for
  in a closed-source app; section 6a (shipping your object files) is the usual answer where it
  matters. Both licence texts ship in the wheel under `dist-info/licenses/`. Flagging it, not
  advising you — we are not lawyers.

## Build notes (maintainers)

### Recipe shape

Two recipes. FreeTDS is an autotools project that pymssql only links against, so it is built by
[`flet-libfreetds`](../flet-libfreetds) as a static, PIC archive and consumed here as a host
requirement; pymssql's `setup.py` already has the environment hooks to find it, which is why this
recipe needs no patches at all. Folding `libsybdb` and `libtds` into `_mssql` keeps the wheel at
two extension modules — an `_mssql` carrying the whole of FreeTDS and a thin `_pymssql` carrying
none of it — with no shared library to stage and no loader work on either platform.

That host requirement is `requirements.host_build`, not `requirements.host`, so
`flet-libfreetds` never reaches the wheel's `Requires-Dist`: the link absorbs the archives and
consuming apps neither resolve nor download them. It sat under `host` until build 2, which cost
every consumer a 6.2 MB install that the default cleanup then deleted again —
[`psycopg2`](../psycopg2) has always done it the right way with `flet-libpq`, and the two
sibling recipes disagreeing is what made the mistake visible.

### Upgrade hazards

- **The protocol default is whatever FreeTDS's `configure` decides.** `build.sh` passes no
  `--with-tdsver`, which currently means `auto`, spelled out in `src/tds/login.c` as a two-entry
  list: TDS 7.4, then TDS 5.0. Consumers see that as the version in the login packet, as the
  duplicated error text, and — because retrying the list re-enters the login without re-budgeting
  the timeout — as an unpinned `connect()` that never returns against a stalled peer. `configure`
  takes `--with-tdsver=7.4`, and the loop is guarded by `TDS_MAJOR(login) == 0`, so building with
  it should close that hole for every consumer at the cost of TDS 5.0 servers — untested here.
  Until someone tries it the page tells consumers to pass `tds_version` themselves.
- **`DBSETLENCRYPT` being unimplemented is what makes the `encryption` argument inert.** If
  FreeTDS implements it, the argument starts working and this page's central claim inverts. Check
  the `DBSETENCRYPT` case of `dbsetlbool` in `src/dblib/dblib.c` on every FreeTDS bump.
- **Where OpenSSL comes from is decided upstream of this recipe.** The Android wheels for
  CPython 3.12 and 3.13 resolve `libssl_python.so` and `libcrypto_python.so` from the Python
  runtime; the CPython 3.14 Android wheels and every iOS wheel absorb it statically. That is a
  python-build support-tree difference worth about five megabytes of `_mssql`, so a size
  regression after a support-tree bump is not necessarily a recipe fault.
- **The compiled-in `sysconfdir` is a CI path.** The consumer guidance that `$FREETDSCONF` is the
  only way to get a conf file read depends on it staying a path no device has.

### Re-verification checklist

- **The PRELOGIN encryption byte, on device, both platforms** — the only direct evidence that
  TLS is compiled in. A FreeTDS built without OpenSSL still builds, imports and passes an import
  test; it just answers `NOT_SUP`. The `freetds-probe` example reads the byte without a server,
  and the TDS version in the same login packet confirms the protocol default above.
- **Exception classes and payload shape** — the `(number, message)` pair, the
  `MSSQLDatabaseException` → `OperationalError` / `MSSQLDriverException` → `InterfaceError`
  mapping, and which argument errors escape the hierarchy.
- **Parameter quoting** — re-run the type table through `pymssql._mssql.substitute_params`; a
  release can change the datetime precision or the timezone handling with no build change.
- **`connect()` against a socket that accepts and then stays silent** — with no `tds_version` it
  must still hang, and with one it must return in `login_timeout` seconds. A FreeTDS that starts
  honouring the timeout across the version list, or a `--with-tdsver` added to `build.sh`, makes
  the advice on this page unnecessary rather than wrong, and nothing else would show it.
- **Android `DT_NEEDED` on every slice** — an OpenSSL that moves from the runtime's
  `libssl_python.so` to a static copy is invisible in a green build. On iOS, both extensions must
  be `MH_DYLIB`.
- **Size** — sum wheel bytes rather than using `du`, and keep the per-Python split in the figure;
  one architecture is not representative here.

### Coverage gaps

The device tests cover importing `pymssql` — which loads both extensions, since the package
`__init__` re-exports `_pymssql`, which in turn pulls in `_mssql` — and one connection to a
closed local port, which does drive the statically linked FreeTDS connect path in `_mssql` and
its translation into `pymssql.Error`. That test leans on the port *refusing*: it pins no
`tds_version`, so a port that swallowed the connection instead would hang the suite rather than
fail it. Nothing else runs there: no handshake, no encryption byte, no query, no parameter
substitution, no conf file, no server of any kind. Everything this page
says about the wire was measured against the PyPI desktop wheel of the same pymssql and FreeTDS
versions, or read out of the mobile wheels' binaries; the `freetds-probe` example is what moves
those checks onto a device, and only when somebody builds it.
