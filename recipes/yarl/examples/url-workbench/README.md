# yarl URL workbench

One screen that hands the same URL to `yarl.URL` and to `urllib.parse` and prints both
answers side by side. The top three panels re-run whenever you edit the field or tap one
of the three samples; below them are three comparisons that need URLs of their own —
RFC 3986's reference-resolution vectors, a URL carried inside another URL's query, and a
host that is not the host it appears to be. The last panel times yarl's C quoter against
the pure-Python one that ships beside it in the same wheel.

Nothing is bundled: every URL is a string constant in `main.py`, so the same build
produces the same output on every device and a phone can be compared with the desktop
figures below.

What it demonstrates:

- **`urlsplit` returns the characters it was handed; `URL` returns a URL.** Given
  `https://Example.COM:443/search results/über?tag=x&tag=y&empty=#frag ment`,
  `urlsplit(...).geturl()` returns that string back unchanged — spaces, mixed-case host,
  redundant `:443` and all — while yarl produces
  `https://example.com/search%20results/%C3%BCber?tag=x&tag=y&empty=#frag%20ment`. The
  `port` row is the smallest version of the same point, and you have to switch to the
  `idn` sample to see it, because this one states `:443` outright and both libraries then
  answer `443`. On a URL with no port yarl still answers `443` — it knows the scheme's
  default, and separates the two in `explicit_port` — while `urlsplit(...).port` answers
  `None`, having never heard of one.
- **IDN is done, not deferred.** For `https://пример.рф/каталог/книга 42.html?…` yarl's
  `raw_host` is `xn--e1afmkfd.xn--p1ai`, which is what actually goes into a `Host:`
  header; `urlsplit(...).hostname` is `пример.рф`, and `geturl().encode("ascii")` on that
  URL raises `UnicodeEncodeError: 'ascii' codec can't encode characters in position 8-13`.
  `human_repr()` gives the Cyrillic form back for display.
- **What "re-encode this URL" does to an escaped slash.** `quote(unquote(path))` is the
  stdlib idiom, and on `https://files.example.com/box/a%2Fb/%c3%bc` it produces
  `/box/a/b/%C3%BC` — the escaped `%2F`, which was one path segment named `a/b`, has
  become a real separator and two segments. yarl re-quotes without decoding first and
  keeps `/box/a%2Fb/%C3%BC`, with `.parts` reporting `('/', 'box', 'a/b', 'ü')`. Both
  answers upper-case `%c3%bc`, but only one of them earns it: the stdlib gets there by
  decoding and re-encoding, the very step that destroyed the `%2F`. yarl normalises escape
  case in place, so `URL("https://x/%2fc")` is `https://x/%2Fc` — the form RFC 3986 prefers,
  reached without ever decoding.
- **Four readings of one query string, which do not agree.** On
  `?tag=x&tag=y&empty=`: `parse_qs` gives `{'tag': ['x', 'y']}` — the blank key is gone
  unless you pass `keep_blank_values=True`; yarl's multidict gives
  `[('tag', 'x'), ('tag', 'y'), ('empty', '')]`, keeping both the repeat and the blank.
  The trap is the fourth reading, `dict(url.query)`, which returns
  `{'tag': 'x', 'empty': ''}` — it silently keeps the **first** value of a repeated key,
  so the app prints it next to `getall` rather than letting you find it in production.
- **RFC 3986 §5.4's reference vectors, all 42, resolved on the device.** These are the
  normative examples for relative-URL resolution, so the score is correctness, not taste.
  Both libraries get **41 of 42** on this desktop and both miss the same one: for `http:g`
  the RFC's strict answer is `http:g` and both return `http://a/b/c/g`, which the RFC
  itself permits for backward compatibility. A tie is a useful result — it means
  `urljoin` is not the weak part of the standard library.
- **The one join where they genuinely differ, which the RFC's own table never covers.**
  Every vector in §5.4 uses a base with no fragment. Give the base one —
  `urljoin("http://a/b/c/d;p?q#frag", "?y")` — and RFC 3986 §5.3 says the result takes its
  fragment from the *reference*, so the answer is `http://a/b/c/d;p?y`. `urljoin` returns
  that. yarl returns `http://a/b/c/d;p?y#frag`, carrying the base's fragment forward,
  because a `yarl.URL` has no way to distinguish "no fragment" from "empty fragment"
  (`URL("?y").fragment` is `''`, not `None`). Measured identically on yarl 1.24.2 and
  1.24.5.
- **A URL inside a query parameter, built both ways.** Concatenating
  `"…/fetch?url=" + "https://cdn.example.com/img.png?w=100&h=50"` looks right and is
  broken: `parse_qs` on the result returns
  `{'url': ['https://cdn.example.com/img.png?w=100'], 'h': ['50']}` — the inner URL is
  truncated at its own `&` and `h=50` has been promoted into the outer query.
  `with_query({"url": inner})` escapes `&` and `=` and nothing else, and the value reads
  back byte-exact.
- **A host that is not the host it looks like.** `http://аpple.com/login` begins with
  Cyrillic U+0430. `urlsplit(...).hostname` hands back `аpple.com`, which renders
  identically to the real thing in any UI; yarl's `raw_host` is `xn--pple-43d.com`, which
  does not. If your app ever shows a user which host a link goes to, that is the string to
  show.
- **Whether the C accelerator is actually the code that ran.** The header prints
  `yarl._quoting._Quoter.__module__` alongside multidict's and propcache's, and the
  button times both quoters over 2,000 Cyrillic path segments. Measured on this desktop
  (best of five passes, µs per call):

  | | µs/call |
  | --- | --- |
  | C quoter (`yarl._quoting_c`) | 0.22 |
  | pure-Python quoter (`yarl._quoting_py`) | 5.03 |
  | `URL(str)` | 1.83 |
  | `URL(str)` then `.query.getall("tag")` | 2.60 |

  23× between the two quoters, and **2,000 of 2,000 paths encode identically** — the
  fallback is byte-for-byte correct, so nothing but the clock can tell you which one your
  build got. The two URL rows are separate because yarl builds the query multidict lazily:
  the first row never touches multidict and the second does. Re-run with
  `MULTIDICT_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1`, which is the combination a mobile
  build actually gets, and the last row moves from 2.60 µs to **6.67 µs** while the first
  stays at 1.78. Expect up to 10% of run-to-run drift in all of these; the ratios hold.
- **Degrading instead of crashing.** The `yarl` import is guarded. Without the wheel the
  header turns red and names what the import raised, every stdlib answer is still
  computed, the RFC scoreboard reads `yarl absent, urljoin 41/42` rather than 42 phantom
  failures, and each yarl cell reads `-`.

All the figures above are **desktop** measurements (Apple M4, macOS 26.6, CPython 3.14.6,
`yarl` 1.24.2 with `multidict` 6.7.1 and `propcache` 0.5.2 from PyPI, all three with their
C extensions). The point of running the app is to replace them with the device's own.

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

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the
panels before committing to a build — but note that a desktop resolve gets PyPI's own
compiled wheel, so the header will report `multidict._multidict` where a phone reports
`multidict._multidict_py`.
