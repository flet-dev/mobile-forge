# oracledb thin client

Everything the Oracle driver can tell you about itself on a phone with no database anywhere
near it. The first screen already has answers on it: which driver loaded, how long it will
wait, and a connect string taken apart into host, port, service and the descriptor the driver
would put on the wire. Pick another sample or type your own, press **Connect**, and the thin
driver runs its real network path against an address that will not answer — then reports the
class, the code and the milliseconds.

What it demonstrates:

- **Which mode is loaded, and what the other one costs.**
  [`is_thin_mode()`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.is_thin_mode)
  answers `True` and stays that way, because
  [`init_oracle_client()`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.init_oracle_client)
  has nothing to load: press that button and the driver's own `DPI-1047` text, carrying
  whatever the platform's dlopen said, lands on screen. The same absence makes
  [`clientversion()`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.clientversion)
  raise `DPY-2021` up in the driver panel.
- **Parsing and type mapping are compiled work that needs no network.**
  [`ConnectParams.parse_connect_string`](https://python-oracledb.readthedocs.io/en/latest/api_manual/connect_params.html#oracledb.ConnectParams.parse_connect_string)
  accepts [easy connect](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html#easy-connect-syntax-for-connection-strings),
  a `tcps` URL with query parameters, a whole `DESCRIPTION`, or a bare alias, and
  `get_connect_string()` writes the normalised descriptor back out. The last sample is the
  form it rejects with `DPY-4018`, credentials being the job of
  [`parse_dsn_with_credentials`](https://python-oracledb.readthedocs.io/en/latest/api_manual/connect_params.html#oracledb.ConnectParams.parse_dsn_with_credentials).
  The closing block asks every `DB_TYPE_*` value which of
  [`cursor.description`](https://python-oracledb.readthedocs.io/en/latest/api_manual/cursor.html#oracledb.Cursor.description)'s
  five DB-API groups it belongs to, computing the table rather than copying it — last row
  included, the near-half that belong to none, where a `description` branch written on
  `STRING`/`NUMBER` alone quietly falls through.
- **An alias needs a file, and the app writes one.** A
  [tnsnames.ora](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html#tns-aliases-for-connection-strings)
  lands in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  with [`defaults.config_dir`](https://python-oracledb.readthedocs.io/en/latest/api_manual/defaults.html#oracledb.Defaults.config_dir)
  pointing at it, so `sales` resolves to two addresses and a retry policy.
- **What a failed connection actually is.** A refused port gives
  [`OperationalError`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.OperationalError)
  carrying `DPY-6005` and the OS reason; an unroutable address gives the same code and `timed
  out` after the timeout the app passes. A host that does not resolve gives `socket.gaierror`,
  not an [`oracledb.Error`](https://python-oracledb.readthedocs.io/en/latest/api_manual/module.html#oracledb.Error)
  at all — the **base class** row makes that jump visible.
- **Compute off the UI thread, and survive it going wrong.** Each attempt runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button locked and a spinner up — the unroutable sample sits in a socket for the whole
  timeout — and ends in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs, placed in a `finally`: `run_thread` swallows what the worker raises, and one
  unhandled error would leave the button disabled for good.

None of this needs a server, and that is the useful part: the pieces of the driver an app gets
wrong — the connect string, the timeout, the exception it forgot to catch — are all checkable
before there is a database to point at.

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
