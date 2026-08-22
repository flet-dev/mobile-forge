# yarl URL workbench

One screen that hands the same URL to [`yarl.URL`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL)
and to `urllib.parse` and prints both answers side by side. The top panels re-run whenever you
edit the field or tap one of the three samples; below them are three comparisons that bring
URLs of their own. The last button times yarl's C quoter against the pure-Python one that ships
beside it in the same wheel.

Nothing is bundled — every URL is a constant in `src/urls.py`, which holds the comparisons, so
the same build produces the same output on every device.

What it demonstrates:

- **`urlsplit` returns the characters it was handed; `URL` returns a URL.** Given
  `https://Example.COM:443/search results/über?…`, `urlsplit(...).geturl()` hands that string
  back unchanged — spaces, mixed-case host and all — while yarl produces
  `https://example.com/search%20results/%C3%BCber?…`. Switch to the `idn` sample and
  `raw_host` is `xn--e1afmkfd.xn--p1ai`, which is what goes into a `Host:` header, where
  `urlsplit(...).hostname` is still `пример.рф`. `human_repr()` gives the readable form back
  for the screen.
- **What "re-encode this URL" does to an escaped slash.** On the `escaped` sample the stdlib
  idiom `quote(unquote(path))` turns `/box/a%2Fb` into `/box/a/b` — one segment named `a/b`
  has become two — while yarl re-quotes without decoding first and keeps it, with `.parts`
  reporting `('/', 'box', 'a/b', 'ü')`.
- **Four readings of one query string, which do not agree.** On `?tag=x&tag=y&empty=`,
  `parse_qs` loses the blank key unless you pass `keep_blank_values=True`, and yarl's multidict
  keeps both the repeat and the blank. The trap is the fourth reading, `dict(url.query)`, which
  quietly keeps only the **first** value of `tag` — printed next to `getall` here rather than
  found in production.
- **RFC 3986 [§5.4](https://www.rfc-editor.org/rfc/rfc3986#section-5.4)'s 42 reference vectors,
  scored on the device.** A tie is a useful result: it means `urljoin` is not the weak part of
  the standard library. The row under it is the one genuine divergence, and it goes against
  yarl — give the base a fragment and
  [§5.3](https://www.rfc-editor.org/rfc/rfc3986#section-5.3) says the result takes the
  reference's, which `urljoin` does and `join` does not.
- **Two ways to get an encoding wrong that look right.** Concatenating a URL into a query
  truncates it at its own `&` and promotes the rest into the outer query, where
  [`with_query`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.with_query) reads back
  byte-exact; and `http://аpple.com/login`, whose first letter is Cyrillic U+0430, is
  `аpple.com` to both `urlsplit` and yarl's `host` but `xn--pple-43d.com` to `raw_host` — the
  string to put in front of a user.
- **Which quoter you actually got.** The header prints
  `yarl._quoting._Quoter.__module__` beside multidict's and propcache's, and the button times
  both quoters over 2,000 Cyrillic path segments and reports how many encode identically. They
  all do, which is the point: the fallback is byte-for-byte correct, so only the clock can tell
  you which one your build got. The timing runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button locked and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs.

The `yarl` import is guarded, so a build that did not get the wheel still runs: the header turns
red and names what the import raised, every stdlib answer is still computed, and the RFC
scoreboard reads `yarl absent` rather than 42 phantom failures.

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

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the panels —
but a desktop resolve gets PyPI's own compiled dependencies, so the header reports
`multidict._multidict` where a phone reports `multidict._multidict_py`. That difference is the
reason to run it on the device.
