# psycopg2 libpq probe

There is no PostgreSQL server on your phone, and this app does not want one. It reports the
libpq built into the wheel and asks that binary which optional pieces were compiled into it,
takes a connection string apart the way libpq would, and then makes a connection that cannot
succeed so you can see exactly what an app has to catch. Every line on screen is computed on
the device.

What it demonstrates:

- **Asking the binary what it contains, instead of trusting a changelog** —
  [`psycopg2.__libpq_version__`](https://www.psycopg.org/docs/module.html#psycopg2.__libpq_version__)
  is compiled in, while
  [`libpq_version()`](https://www.psycopg.org/docs/extensions.html#psycopg2.extensions.libpq_version)
  asks the library that actually loaded; in these wheels libpq is linked into the extension, so
  the two can never drift apart. The feature flags below them come from a trick: libpq validates
  connection options *before* it opens a socket, so setting
  [`sslmode=require`](https://www.postgresql.org/docs/17/libpq-connect.html#LIBPQ-CONNECT-SSLMODE)
  or `gssencmode=require` against a closed port makes the library say whether that feature was
  compiled in. Only the *absent* feature says so in words — a build that has one compiles the
  refusal out — so a green dot means the option was accepted and the attempt reached the network.
- **Reading a connection string without connecting** —
  [`parse_dsn`](https://www.psycopg.org/docs/extensions.html#psycopg2.extensions.parse_dsn)
  is `PQconninfoParse`: it takes the URI or the `key=value`
  [form](https://www.postgresql.org/docs/17/libpq-connect.html#LIBPQ-CONNSTRING), rejects a
  keyword that does not exist, and returns only what you wrote down. Because it returns only
  that, the app lists separately what libpq will supply for everything you left out — the row
  worth reading being `sslmode`, whose default is `prefer`.
- **The exception a failed connection raises** — a refused port, a name that will not resolve
  and an expired
  [`connect_timeout`](https://www.postgresql.org/docs/17/libpq-connect.html#LIBPQ-CONNECT-CONNECT-TIMEOUT)
  all arrive as
  [`OperationalError`](https://www.psycopg.org/docs/module.html#psycopg2.OperationalError),
  with `pgcode` printed as `None` — a SQLSTATE comes from a server, and no server answered.
- **Type adaptation, which is entirely client-side** —
  [`adapt`](https://www.psycopg.org/docs/extensions.html#psycopg2.extensions.adapt) turns a
  Python value into the SQL literal psycopg2 would send, with no connection in sight. `dict`
  is in the list because it has no adapter and raises instead of guessing.
- **Blocking work off the UI thread** — libpq holds the calling thread for the whole attempt,
  so the probe runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a [`ProgressRing`](https://flet.dev/docs/controls/progressring/) up. The
  worker body is wrapped whole and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.

Edit the string and probe again. Point it at `10.255.255.1:5432` and `Connection refused`
becomes `timeout expired` after exactly the seconds you allowed; delete `connect_timeout` and
the spinner keeps turning until the operating system gives up on the socket, which is the
number your app's responsiveness actually rests on. Delete `sslmode=require` and the keyword
leaves one list for the other and the verdict under them rewords — but the padlock does not
move, and that is the point of it being on screen. `require` encrypts and then trusts whoever
answered, so it is no better authenticated than the plaintext-accepting default; only
`verify-ca` or `verify-full` closes the lock.

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
