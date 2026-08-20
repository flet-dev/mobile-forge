# markupsafe

[`markupsafe`](https://markupsafe.palletsprojects.com/) is the escaping half of Python
templating. It provides
[`escape()`](https://markupsafe.palletsprojects.com/page/escaping/#markupsafe.escape),
which replaces the five characters that carry meaning in markup, and
[`Markup`](https://markupsafe.palletsprojects.com/page/escaping/#markupsafe.Markup), a
`str` subclass that marks a string as already safe so it is not escaped a second time.
In a Flet app it is what lets you build HTML from user text — a
[`WebView`](https://flet.dev/docs/controls/webview/) payload, an exported report, a
generated document — without that text being able to turn into markup.

The distribution is published as `MarkupSafe` and imported as `markupsafe`.

## Install

```toml
dependencies = [
    "flet",
    "markupsafe",
]
```

Nothing else is needed: the package is two small Python modules plus an optional C
extension, with no dependencies of its own, no native library, and nothing it has to
find on disk at runtime. Most apps never add it on purpose —
[Jinja2](https://jinja.palletsprojects.com/) requires `MarkupSafe>=2.0`, so anything
built on Jinja brings it in, and the mobile wheel is picked up automatically.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`escape-inspector`](examples/escape-inspector) — builds one comment four ways and
  counts the live tags the input smuggles into each.

## Usage in a Flet app

Two names do the work:

```python
from markupsafe import Markup, escape

body = Markup("<p>Comment from <b>{}</b></p>").format(user_text)
```

`escape()` returns `Markup`, and `Markup` is a `str` subclass whose operators escape
whatever they are combined with:
[`format`](https://markupsafe.palletsprojects.com/page/formatting/#format-method), `%`,
`+` and `join` all escape their arguments. The template's own tags stay live, the
interpolated value cannot add any.

### Storage

MarkupSafe itself reads and writes nothing; the storage question arrives with the HTML
you produce.
[`WebView.load_html`](https://flet.dev/docs/controls/webview/#flet_webview.WebView.load_html)
takes the string directly, so the common case needs no file at all. `WebView` comes from
the separate `flet-webview` distribution — `flet` does not pull it in — and `load_html`
is a coroutine, so await it from an async handler; called from a synchronous one it
returns an un-awaited coroutine, warns, and loads nothing:

```python
async def show(e):
    await view.load_html(str(body))
```

When you do want a file — an export the user keeps, or a page with relative asset
references handed to
[`WebView.load_file`](https://flet.dev/docs/controls/webview/#flet_webview.WebView.load_file)
— place it by lifetime:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something durable,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for a page you can regenerate,
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch. Templates, CSS and images that ship with the app are
[assets](https://flet.dev/docs/cookbook/assets), reached through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

### Threading

`escape()` and `Markup` are pure functions over immutable strings. There is no shared
state, nothing to lock, and no ordering requirement, so they are safe to call from any
thread.

The C accelerator does not release the GIL — `_speedups.c` contains no
`Py_BEGIN_ALLOW_THREADS` at all, and the escape is a character-at-a-time scan followed
by a character-at-a-time copy — so escaping a very large value blocks other Python
threads for its duration, and
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) will
keep your handler off the event loop without making the work concurrent. Escaping one
field at a time is what templating actually does and needs no thread at all; if you are
escaping megabytes in one call, split the value rather than threading it.

The extension uses multi-phase initialisation and declares both per-interpreter GIL and
free-threading support, and it imports successfully inside a subinterpreter on desktop
CPython 3.12.

### What actually needs escaping

`escape()` solves exactly one problem: HTML text, and attribute values that are inside
quotes. That is what the five characters are for — `&`, `<` and `>` keep the value out
of the markup grammar, and `'` and `"` keep it inside `attr='…'` or `attr="…"`. Every
other context is a different problem with different rules:

- **JavaScript.**
  [`run_javascript`](https://flet.dev/docs/controls/webview/#flet_webview.WebView.run_javascript)`(f"show('{escape(text)}')")`
  is wrong: a backslash or a newline breaks out of a JS string and `escape()` touches
  neither. Write `await view.run_javascript(f"show({json.dumps(text)})")` instead —
  `json.dumps` emits a complete JS literal, quotes included.
- **URLs.** `escape()` leaves `?`, `#`, `%` and spaces alone. Use
  `urllib.parse.quote`, then escape the result if it is going into HTML.
- **Unquoted attributes.** `<div class={{ value }}>` is unsafe no matter what
  `escape()` does, because a space ends the value and starts a new attribute.
- **Markdown.** [`ft.Markdown`](https://flet.dev/docs/controls/markdown/) renders
  Markdown, not HTML, and Markdown's dangerous characters are `[`, `]`, `(`, `)` and
  backticks. Escaping for HTML does nothing useful on the way in.

`Markup` is the other half, and it records a decision rather than making one. It never
inspects the string. `Markup(value)` where `value` came from a user is a
cross-site-scripting hole written in one call, and so is
`Markup("<b>" + value + "</b>")`, which looks like a template but does the
concatenation first. Bless only strings you built, and let the operators bring the
values in. And note that MarkupSafe escapes rather than sanitises: if your app needs to
accept *some* HTML from users, no combination of these functions is the right tool —
that job needs an HTML sanitiser, which is a different package.

### App size

Approximately 12 KB compressed per architecture, and roughly 30 KB unpacked on Android
and 90 KB on iOS. The extension is what differs: Android strips it to a few kilobytes,
so there the largest file in the wheel is `__init__.py` rather than the binary, while on
an iOS device the extension is about three quarters of the payload. There is nothing here
worth pulling a lever for: the biggest thing a
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) glob could
drop is the 4 KB `_speedups.c` the wheel ships beside the compiled extension — the only other
candidates are a 41-byte stub and an empty `py.typed` — and an app
bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
are worth using for the app as a whole but will not show a measurable difference here.

### Other considerations

A desktop `flet run` uses PyPI's wheel, which also carries the C accelerator on
CPython, and the output is identical either way: the public API is pure Python over a
single C function whose behaviour the fallback reproduces exactly. The difference that
can bite is silent rather than visible — an installation without the extension, such as
a source install whose compile failed, behaves the same apart from speed and warns
nobody. `markupsafe._escape_inner.__module__` is the answer: `markupsafe._speedups` when
the accelerator is live, `markupsafe._native` when it is not.

## Things to know

- **`Markup(value)` is a promise, not a check.** It never examines the string, so a
  value containing `<script>` becomes a real element rather than visible text. The
  symptom is markup that "works" — user content that renders as bold, or a link, or
  nothing at all. Bless only strings you assembled yourself.

- **Blessing after concatenation loses the escaping.** `Markup("<b>" + value +
  "</b>")` escapes nothing, while `Markup("<b>") + value + Markup("</b>")` escapes
  `value`. Both read like a template; only the second is one.

- **f-strings drop the `Markup` type.** `f"{Markup('<b>')}{value}"` returns a plain
  `str` and escapes nothing, because formatting goes through `__format__` on `str`.
  Use `Markup(...).format(...)` or `%`.

- **A `__html__` method that returns `str` breaks under `Markup.format`.**
  `escape()`, `Markup()` and `%` all take the returned string as-is, but
  `Markup.format` escapes whatever `__html__` returns, so the same object renders
  correctly in three places and arrives as visible `&lt;i&gt;` text in the fourth.
  Return `Markup` from `__html__`.

- **`escape(None)` is the string `"None"`.** For an optional value use
  [`escape_silent`](https://markupsafe.palletsprojects.com/page/escaping/#markupsafe.escape_silent),
  which renders `None` as the empty string.

- **The accelerator is not uniformly faster.** It sizes the result with one scan and
  then copies character by character, so it wins where escaping is dense — about 5x on
  a value that is all `&` — and loses to `str.replace`'s fast paths where a long string
  holds only a few specials: 0.8x on 32 KB containing a single `&` (desktop CPython
  3.12, macOS arm64). One more reason to escape a field at a time, not a document.

- **`markupsafe.__version__` is deprecated.** Reading it emits a `DeprecationWarning`
  naming 3.1 as the removal and returns what
  `importlib.metadata.version("markupsafe")` returns — use that instead.

## Build notes (maintainers)

### Recipe shape

A name, a version and a build number — no patches and no build settings: the sdist builds
a single optional C extension with plain setuptools, and forge's default Python path
handles it unchanged.

The recipe exists for resolution rather than for capability. MarkupSafe's pure-Python
fallback is complete, so the package would function perfectly well without the
extension — but PyPI publishes no `py3-none-any` wheel, only platform wheels and an
sdist, so a mobile install needs a wheel from somewhere regardless. Given that one has
to be built, building it with the accelerator costs nothing extra.

### Upgrade hazards

- **A failed compile does not fail the build.** `setup.py` catches compiler errors and
  re-runs `setup()` with `ext_modules=[]` unless `CIBUILDWHEEL=1` is set in the
  environment. A broken cross-compile therefore produces a green build and a wheel with
  no `.so` in it, and every consumer keeps working — more slowly, and silently. The
  device test `test_speedups_loaded` is the only thing between that and an unnoticed
  regression. If that test is ever relaxed, set `CIBUILDWHEEL=1` in
  `build.script_env` so the failure becomes hard instead.
- **The C entry point was renamed in 3.0**, from `escape` to `_escape_inner`; the
  device test probes both names so it survives a move in either direction. 3.1 removes
  `markupsafe.__version__`.
- **This page tells readers that `markupsafe._escape_inner.__module__` names the live
  engine.** That is a consequence of the `try`/`except ImportError` at the top of
  `__init__.py`, not a documented API. Re-check it on a major bump before repeating the
  claim.

### Re-verification checklist

- **Extension present in every slice:** list each built wheel and confirm a `_speedups`
  extension is in it. A wheel with only Python files in it is the expected shape of a
  silently failed compile, not of a broken build.
- **Accelerator wins the import on device:** `markupsafe._escape_inner.__module__` must
  read `markupsafe._speedups` on both platforms. A successful `import markupsafe` proves
  nothing, because the fallback import succeeds too.
- **The five replacements:** confirm `'` is still `&#39;` and `"` still `&#34;`. The
  advice about quoted attributes depends on both being escaped.
- **Deprecations and semantics:** re-read whether `__version__` has been removed and
  whether the `__html__` and formatting behaviours described above still hold.
- **Size:** re-measure from the resulting wheels rather than scaling the old figures.

### Coverage gaps

The device tests cover four of the five characters — between them the two test inputs
contain `<`, `>`, `'` and `&`, but never a `"`, so `&#34;` is asserted nowhere on
device — plus `Markup` pass-through and that `markupsafe._speedups` imported and
produces correct output. They do not exercise `Markup.format`, `%`, `join`, the
`__html__` protocol, `striptags`, `unescape`, or any timing at all. Every speed figure
on this page was measured on desktop CPython 3.12 on macOS arm64, not on a phone; the
`escape-inspector` example times both engines on the device so a reader can get real
numbers instead.
