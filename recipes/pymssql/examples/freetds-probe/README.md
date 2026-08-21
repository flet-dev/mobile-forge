# FreeTDS probe

The driver reports the [FreeTDS](https://www.freetds.org/) build it was compiled against, then
logs in four times to a socket this app opens in its own process — no SQL Server anywhere — and
shows what each attempt actually put on the wire. Type an address at the bottom and the app
prints what pymssql does to your server string, then the exception a real connection raises.

What it demonstrates:

- **Whether this build can do TLS, answered by the driver itself** — the
  [PRELOGIN](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-tds/60f56408-0188-4cd5-8b90-25c6f2423868)
  packet opens every TDS login with one byte saying what the client can encrypt. A FreeTDS
  built without TLS can only say `NOT_SUP`. This one says `OFF` — *I can, you decide* — and when
  the fake server offers encryption the next thing on the wire is a TLS ClientHello offering
  TLS 1.3.
- **What `encryption="require"` is worth** — pass it to
  [`pymssql.connect`](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html#functions) and
  the byte does not change: the app's third probe still hands its
  [LOGIN7](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-tds/773a62b6-ee89-4c02-9e5e-344882630aac)
  packet to a server that said it has no TLS, and the probe reads the user name, the app name
  and the password straight back out of it. The fourth probe asks for the same thing through a
  [`freetds.conf`](https://www.freetds.org/userguide/freetdsconf.html) written into
  [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
  and pointed at with `$FREETDSCONF` — that one flips the byte to `ON` and refuses to log in.
- **The exception a failed connection raises** — pymssql wraps FreeTDS in its
  [own hierarchy](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html#exceptions), so the
  Connect button reports the class, the base that catches it, and every line of the message. The
  address defaults to `127.0.0.1:1433`, where nothing is listening on a phone.
- **Native work off the UI thread** — the probes and the connection attempt run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind a
  [`ft.ProgressRing`](https://flet.dev/docs/controls/progressring/), because FreeTDS blocks while
  it logs in — it does release the GIL for that, which is what keeps the UI moving. Each worker
  ends in a `finally` that clears its spinner, re-enables whatever it locked, and calls
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

Two details reward a second look. The message from the Connect button arrives twice: FreeTDS's
compiled-in protocol default is `auto`, which tries TDS 7.4 and then TDS 5.0, and each attempt
files its own error. And the number on the `args[0][0]` line does not match the number in the
text below it — that field is only replaced by an error of *higher* severity, and every
connection failure is severity 9, so it keeps whatever the first failure in the process put
there. Match on the exception class, read the text, and never branch on the number.

The Connect button deliberately passes no `tds_version`, which is what makes that duplicate
visible — and also what makes the button the one control here that can hang. Aim it at an address
that accepts the connection and then stalls rather than refusing it, and retrying the version
list keeps `connect()` inside FreeTDS past `login_timeout` with the spinner still turning. Real
apps should pin the version; this one is showing you why.

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
