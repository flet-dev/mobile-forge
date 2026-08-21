# Flet app-layer catalogue (consumer app code, not the wheel)

Symptom → cause → fix for things that go wrong in **the Flet app that uses a wheel**,
as opposed to the wheel itself. Sibling of
[`failure-catalogue.md`](failure-catalogue.md), which covers builds and the
packaging/loader layer.

**Which file do I want?** If the failure is `dlopen`, a missing symbol, a `.soref`,
`sitepackages.zip`, a data file that vanished, or an import that never completes — it is
the wheel: use `failure-catalogue.md`. If the package imports fine and *then* the app
misbehaves — a handler does nothing, the UI renders wrong, an API raises `TypeError` on a
keyword you were sure existed — it is here.

Everything below is verified against **Flet 0.86.5** unless stated. Where a fact is
version-coupled, the version is named so a stale entry is self-evidently stale.

---

## Threading and updates

### A `page.run_thread` worker silently does nothing (no crash, no log, no result)

**Symptom:** the user taps a button whose handler calls `page.run_thread(work, …)` and
nothing happens — no error dialog, no `SESSION_CRASHED`, nothing on the `flet` logger,
nothing in `console.log`. Intermittent: it works most of the time.

**Cause:** `Page.run_thread` does `loop.run_in_executor(...)` and never retrieves the
resulting future, so **any exception raised inside the worker is swallowed entirely** (it
surfaces only as an asyncio "Future exception was never retrieved" at GC time, which
nothing on device reads). Verified on 0.86.5: a worker raising `RuntimeError` produced 0
SESSION_CRASHED messages and 0 log records.

The intermittency usually comes from the second half of this trap: `run_thread` submits to
a shared `concurrent.futures.ThreadPoolExecutor`, so **workers genuinely run
concurrently** — two taps in quick succession overlap. Any native handle that is not safe
for concurrent use raises from inside the worker, and the raise is invisible per the above.

**Concrete instance:** one `apsw.Connection` shared across `run_thread` handlers. apsw
permits a connection on *any* thread but not two at once — it raises
`ThreadingViolationError: Cursor couldn't run because the Connection is busy in another
thread`. Measured on desktop with the exact insert-then-read pair an app performs: 12
threads × 200 iterations dropped 100–200 rows on 3 of 5 runs, with 1–4 raised exceptions
per run, every one invisible.

**Fix:** serialise the shared handle with a `threading.Lock` — take it around the *whole*
use; for a DB cursor, materialise the `SELECT` inside the lock, since an unconsumed cursor
is what leaves the connection busy — or give each thread its own handle. Independently,
wrap worker bodies in `try/except` and surface failures, because the framework will not.

**Tell it apart from** a wheel/loader problem: a loader failure fails on the FIRST call and
usually leaves something in logcat/console; this one succeeds most of the time and leaves
nothing anywhere.

### UI doesn't refresh from a background thread

**Cause:** 0.86 auto-updates after every event handler and after `main()` returns
(`Session.after_event` → `__auto_update`), but that only fires at handler/`main`
boundaries. Work running inside a `page.run_thread` worker is outside them.

**Fix:** end a `run_thread` handler with an explicit `page.update()`. Everywhere else,
mutating `page.controls` or a control's `controls` list inside a handler renders without
one — an explicit `page.update()` is still correct and harmless, just not required.

---

## Layout on device

### The first line of content renders under the status bar / notch

**Symptom:** on a phone (both platforms) the top of the app is clipped by the status bar
or the Dynamic Island; on the desktop window it looked fine.

**Cause:** `page.add(...)` places content in the raw window; nothing insets it for system
chrome.

**Fix:** either an `ft.AppBar` on the page or an `ft.SafeArea(expand=True, content=...)`
around the content resolves the top — you do not need both. They are not interchangeable
though: `AppBar` insets the top and gives you a title bar, while `SafeArea` insets every
edge, including the bottom home indicator. So reach for `SafeArea` when there is no app
bar, and use both when you want a title *and* bottom-edge safety.

Verified on an Android emulator and an iPhone simulator: with **neither**, the header text
sits under the status bar on both platforms; with both, it is clear on both.

### Everything below the AppBar is blank on iOS, and Android renders it fine

**Symptom:** the app builds its whole control tree — the log shows every `Text build:`,
`Column build:`, the computed values, the `applyPatch` messages — and the screen shows the
AppBar title over empty space. **No exception, no overflow stripes, no error of any kind**, on
either side. The same build renders correctly on Android.

**Cause:** a control with `expand=True` sitting as a **direct child of a scrolling `Column`**
(`ft.Column(scroll=ft.ScrollMode.AUTO, controls=[... ft.SegmentedButton(expand=True) ...])`).
A scroll viewport is unbounded in its scroll direction, so a flex child has nothing to expand
into. Android tolerates it; iOS collapses **the entire viewport** to zero height, taking every
sibling with it, which is why the failure looks like "the app produced nothing" rather than
"one control is wrong".

**Fix:** give it a bounded parent, or drop the `expand`. Wrapping in a `Row` keeps the
full-width appearance:

```python
ft.Row(controls=[ft.SegmentedButton(expand=True, ...)])   # renders on both
```

Measured 2026-08-20 across five examples built the same day, which isolates it cleanly: two
with `expand=True` inside a `Row` rendered, two with no `expand` as direct children rendered,
and the one with `expand=True` as a direct child of the scrolling `Column` was blank on iOS and
correct on Android.

**Diagnosing it:** the tell is that the log is *healthy*. If you see the control tree being
built and patched with real values while the screen stays empty, stop looking for an exception
and start looking for a layout contradiction — an `expand` under a scroll, an unbounded
`ListView` inside a `Column`, or a `Row` inside a horizontally-unbounded parent.

### A control row shows Flutter's yellow/black "OVERFLOWED BY n PIXELS" stripes

**Symptom:** a striped marker down one edge of the screen, with the overflow amount
printed sideways in red. Only ever visible on a narrow (phone-width) screen.

**Cause:** a non-scrolling `ft.Row` whose children are wider than the viewport. It is not
always *your* Row — a composite control can carry one. `flet_charts`'
`MatplotlibChartWithToolbar` lays six `IconButton`s plus a `Dropdown` and a message `Text`
in one plain `Row`, which overflows by ~122 px at 393 pt (verified on an iPhone simulator).

**Fix:** for your own rows, `scroll=ft.ScrollMode.AUTO`, `ft.ResponsiveRow`, or `wrap=True`.
For a composite whose internals you should not reach into, drop to the plain control and
build the toolbar yourself — `MatplotlibChart` exposes `home()`, `back()`, `forward()`,
`pan()` and `zoom()` publicly, so three buttons reproduce what a phone actually needs.

### Date-axis tick labels collide into an unreadable smear once zoomed

**Symptom:** a matplotlib date axis is legible at full extent, then overlaps into a solid
run of digits after zooming in (`202120122-01212-032203…`).

**Cause:** the default `AutoDateFormatter` spells each tick out in full, and a phone-width
axis has no room for them once the locator switches to days.

**Fix:** `mdates.ConciseDateFormatter(locator)` with an `AutoDateLocator` — it omits
whatever the neighbouring tick already implies, so labels stay short at every zoom level.

### A blank white screen right after launching on an emulator

**Not necessarily a failure.** Flet's first draw on a software-GPU emulator can take well
over a minute — an observed `ActivityTaskManager: Displayed … +1m24s537ms`. A screenshot
taken before that shows an empty screen with no error anywhere.

**Fix:** wait for `Displayed`/`Fully drawn` in `logcat`, or poll the screenshot until it
changes, before concluding anything. Check `console.log` and the app's storage dir for
evidence the Python side already ran.

---

## Packaging the app (`pyproject.toml`)

### Junk files ship inside the app bundle

**Symptom:** the app payload (`assets/app.zip` on Android) contains `README.md`,
`pyproject.toml`, `.gitignore`, `__pycache__/`, `.ruff_cache/` — anything sitting in the
project directory.

**Cause:** `[tool.flet.app] path = "."` packages the whole directory.

**Fix:** keep app code in `src/` and set `path = "src"` (what `flet create` generates).
Measured: an example app with `path = "."` shipped 7 files, of which 1 was the app.

### A library reads its own source with `open(__file__)` and gets bytecode

**Symptom:** a package that inspects its own file at runtime — self-tests, doctest collectors,
`inspect.getsource`, license printers — fails or returns garbage on device, on **both** platforms,
while working on desktop.

**Cause:** `compile.packages` defaults to true, so what ships is `foo.pyc` with no `foo.py`
alongside it. On a sourceless module `__file__` points at the **`.pyc`**, so `open(__file__, "rb")`
hands back bytecode starting with the magic number, not source. Verified 2026-08-19 with
`compileall -b`, deleting the source, then reading `m.__file__` — it resolves to the `.pyc` and the
first bytes are `2b0e0d0a` (the CPython 3.14 magic). `extract_packages` does not help: it changes
*where* the file lives, not whether a `.py` exists beside it.

**Fix:** set `compile.packages = false` in `[tool.flet]` if you need real source on device, or
avoid the code path. Do not assume this is iOS-only — the sourceless `__file__` is identical on
Android, and a page claiming otherwise is wrong.

### `sitepackages.zip` contains `__init__.py` files that exist in no wheel

**Symptom:** a check like "package X's test suite can never be imported, because there is no
`X/tests/__init__.py`" is false on Android, and any conclusion resting on it is wrong.

**Cause:** `zipimport` has **no namespace-package support**, so serious_python's zip step
synthesises a **zero-byte `__init__.py`** for every namespace directory on the way in. Measured
2026-08-19 in a built APK: `regex/tests/__init__.py` and `flet/messaging/__init__.py` were both
present at zero bytes in `assets/sitepackages.zip` and in no wheel; the iOS `build/site-packages/`
tree — a real directory, not a zip — had neither.

**Consequence:** Android turns namespace dirs into importable packages and iOS does not, so
"is it importable?" can differ per platform for the same source. Check the built payload, not the
wheel:

```bash
unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep '__init__.py'
```

### `flet build` fails resolving deps, but only from a clean checkout

**Symptom:** `No solution found when resolving dependencies for split (markers:
python_full_version == '3.10.*')` — e.g. "numpy==2.4.6 depends on Python>=3.11 … your
project's requirements are unsatisfiable". The same project built fine minutes earlier.

**Cause:** `flet create` writes `requires-python = ">=3.10"`, and uv resolves for *every*
version in that range, not just the interpreter in use. A dependency pinned with `==` whose
own floor is higher than 3.10 makes the lowest split unsatisfiable. It stays hidden while a
`.venv`/lock from before the pin exists, and only surfaces once those are removed — which
is exactly the state a consumer cloning the repo is in.

**Fix:** raise `requires-python` to the true floor of the pinned set. Floors that bite at
the versions used here: `numpy==2.4.6`, `pandas==3.0.3`, `scikit-learn==1.9.0` → `>=3.11`;
`scipy==1.18.0` → `>=3.12`.

**Verify like a consumer would:** copy the `pyproject.toml` alone into an empty directory
and run `uv lock` there. Deleting `.venv` and `uv.lock` in place works too. Do not treat a
build that reused an existing lock as evidence.

### `flet build apk` fails with a wheel hash mismatch that the server disproves

**Symptom:** the Android build dies in the pip step with

```
ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.
    <pkg>==<ver> from https://pypi.flet.dev/-/ver_XXXX/<wheel>.whl#sha256=<expected>
        Expected sha256 <expected>
             Got e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

**Read the "Got" value first.** `e3b0c442…b855` is the SHA-256 of the **empty string** — pip
received zero bytes, so this is a truncated download or a cached empty body, not a tampered or
mis-published wheel. Confirm the index is fine before blaming it:

```bash
curl -sL -o /tmp/w.whl "<the URL from the error>" && wc -c /tmp/w.whl && shasum -a 256 /tmp/w.whl
```

Observed 2026-08-18 on `tflite_runtime … android_24_armeabi_v7a.whl`: the server served
1,983,598 bytes with the expected digest, while the build failed identically **twice** — so a
plain retry does not clear it.

**Fix:** bypass pip's cache for the build.

```bash
PIP_NO_CACHE_DIR=1 uv run flet build apk
```

That built first time. Note this is pip's cache inside the app build, not uv's — clearing
`~/.cache/uv` will not help, and neither will `rm -rf build/`.

### Blank screen, no traceback, and the log stops at `after Py_Initialize()`

**Symptom:** `flet build` succeeds, the app installs and launches, the activity reports
`Fully drawn`, and the screen stays blank forever. logcat shows serious_python getting as far as:

```
[serious_python] CPython loaded
[serious_python] after Py_Initialize()
```

and then **nothing** — no `Traceback`, no `ModuleNotFoundError`, no crash. The app is not hung on
your code; it never reached it.

**Cause:** the build targeted a **different Python minor version than the one that compiled the
payload**. flet compiles `main.py` and the site-packages to bytecode with the *host* interpreter,
so a 3.14 host against a 3.12 runtime produces `.pyc` files whose magic number the runtime
rejects, and the import machinery fails before any Python-level error handler exists to report it.

Observed 2026-08-20: four examples that had built and run correctly at 3.14 rebuilt two hours later
targeting 3.12 — same `flet-cli` 0.86.5, same default `v0.85.2` template, same 3.14 host venv, same
sources. The trigger was a **mutated project venv**: a process had rewritten packages inside
`.venv` between the two runs.

**Diagnose in one command** — the APK names the runtime it will load:

```bash
unzip -l build/apk/<app>.apk | grep -oE 'libpython3\.[0-9]+\.so' | head -1
```

Compare it against the host that did the compiling (`.venv/bin/python -V`). They must agree on the
minor version. The iOS equivalent is the extension suffix under `build/site-packages/`:
`foo.cpython-312-iphoneos.so` vs `cpython-314`.

**Fix:** delete the project venv *and* the lock, then rebuild — clearing `build/` alone is not
enough, because the wrong runtime is chosen during dependency resolution:

```bash
rm -rf .venv uv.lock build && uv run flet build apk
```

**Do not chase this in your app code.** Nothing in `main.py` can cause it and nothing in `main.py`
can fix it; the symptom is identical for every app in the batch, which is the tell that it is
environmental rather than a bug you introduced.

### A build reports OK but the app on screen is a DIFFERENT app

**Symptom:** `flet build` succeeds, the artifact installs, and the running app shows content that
does not exist anywhere in your `src/main.py` — a screen from some other project entirely.

**Cause:** the packaged payload was reused from a stale cache rather than rebuilt. Observed
2026-08-18: an iOS bundle shipped an 8,191-byte `main.pyc` from an unrelated probe app while the
same build's `build/python-app/main.pyc` was the correct 22,847-byte file, and the APK from that
same run was correct. `rm -rf build` alone did NOT prevent it; the hashes under `build/.hash`
(`package`, `template-*`, `icons`, `splashes`) let the iOS half skip re-packaging.

**Fix:** clear the hash cache and the Flutter tree, not just `build/`:

```bash
rm -rf build/.hash build/flutter build/ios-simulator && uv run flet build ios-simulator
```

**Detect it before shipping — never trust "apk OK" alone.** Diff the payload against something
only your code contains:

```bash
strings "$(find build/ios-simulator -name main.pyc -path '*app*' | head -1)" | grep -c '<a string only your app has>'
```

Do the same for Android via `assets/app.zip`. A payload whose size or contents disagree with
`build/python-app/main.pyc` is the tell. This is the sibling failure to the crossed-`sitepackages`
bundle above: there the *dependency* half was wrong, here the *app* half is.

**Do not compare `main.pyc` by hash across two builds — it always mismatches, and the mismatch
means nothing.** serious_python compiles the app in a fresh `mkdtemp`, so `co_filename` carries a
random 6-character suffix (`/T/serious_python_tempme0dSM/main.py`) that is baked into the `.pyc`.
Measured 2026-08-19 on fiona: the Android and iOS payloads from one back-to-back pair differed in
exactly 6 bytes, all inside that suffix, with identical 16-byte headers (same source mtime, same
source size) and identical 19,835-byte body lengths. Two consequences:

- `build/python-app/main.pyc` is only a valid reference **for the build that just ran** — the next
  build overwrites it, so check each artifact before starting the next one.
- To compare two artifacts, compare the bodies with the temp path normalised, not the raw bytes:

```bash
python3 -c 'import re,sys; f=lambda p: re.sub(rb"serious_python_temp.{6}", b"T", open(p,"rb").read()[16:]); print("MATCH" if f(sys.argv[1])==f(sys.argv[2]) else "DIFFER")' a/main.pyc b/main.pyc
```

A real crossed payload is nothing like 6 bytes: the 2026-08-18 case was 8,191 bytes against 22,847.

### Never run two `flet build`s at the same time on one machine

**Run them one after another.** Concurrent builds share mutable state and fail in three ways,
two loud and one silent. All three observed on 2026-08-17 building three examples at once:

| Symptom | Where the sharing is |
|---|---|
| `Gradle task assembleRelease failed` … `libpythonbundle.so missing in jniLibs/armeabi-v7a` from `:serious_python_android:splitStdlib_<abi>` | `serious_python_android` lives in the shared pub cache; every build populates the *same* `jniLibs`, so one wipes what another is reading |
| `Error (Xcode): could not determine executable path for bundle`, often after `Waiting for another flutter command to release the startup lock...` | the Flutter startup lock and shared build state are global |
| **Nothing at all** — the build reports OK and the app hangs on the Flet splash screen on device | the app payload got another build's site-packages |

The silent one is the dangerous one, and it does not look like a build problem on device — it
looks like a broken recipe. Diagnose it by opening the payload rather than guessing:

```bash
unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep -c <your-package>
```

A count of 0 for the package the app is *about* (and a nonzero count for some other example's
package) is the crossed bundle. The measured case: the lxml example's APK carried 0 lxml
entries and 9 `pydantic_core` ones, with lxml's native `.so` files correctly present in
`lib/<abi>/` — so the jniLibs half was right and only the Python half was crossed. A clean
rebuild of that one example gave 75 lxml entries and 0 pydantic.

Sequential builds of the same three examples all passed. Parallelism buys nothing here anyway:
each build already saturates the machine, and a starved Android emulator then wedges its own
SystemUI (see the blank-screen entry above).

### Pinning `flet` in a snippet people copy

Not a failure, a rot source: a bare `flet` resolves to the latest release, so a version in
a pasted snippet is a pin the reader still carries two releases later. State a genuine
minimum in prose instead. (Verified no-op today: `flet` and `flet>=0.86.0` both resolve to
0.86.5.)

---

## API traps in 0.86

These construct or import cleanly at a glance and fail at the point of use. All verified
by introspection against an installed 0.86.5.

| You write | What happens | Use instead |
|---|---|---|
| `ft.app(main)` | Deprecated since 0.80 — **and** `ft.app` is shadowed by the `flet.app` *module* once `ft.run` has been touched, so it can raise `TypeError: 'module' object is not callable` | `ft.run(main)` |
| `ft.ElevatedButton(...)` | Deprecated since 0.80, deleted in 1.0 | `ft.Button` (or `ft.FilledButton` / `ft.TextButton`) |
| `ft.Button(text="Save")` | `TypeError` — there is no `text` param | `ft.Button("Save")` or `content=` |
| `ft.TextField(error_text=...)` | `TypeError: … Did you mean 'error_style'?` | `error=` |
| `ft.Card(color=...)` | `TypeError: … Did you mean 'bgcolor'?` | `bgcolor=` |
| `ft.DataRow(on_select_changed=...)` | `TypeError` | `on_select_change` (no "d") |
| `page.open(dlg)` / `page.snack_bar` | Do not exist in 0.86 | `page.show_dialog(ft.SnackBar(content="…"))`, `page.pop_dialog()` |
| `page.storage_paths` | Deprecated, **deleted in 0.90.0** | `ft.StoragePaths()` (async) or the env vars |
| `ft.colors.RED` | `ft.colors` does not exist at all | `ft.Colors.RED` |
| `ft.icons.DELETE` | Resolves to a *module*, then `AttributeError` | `ft.Icons.DELETE` |
| `ft.Icons.DATABASE` | Not a member | `ft.Icons.STORAGE` / `TABLE_CHART` / `DATASET` |
| `ft.UserControl`, `ft.MaterialState` | Removed / renamed | subclass a control or `ft.Component`; `ft.ControlState` |
| `page.platform == "android"` | Always `False` — `PagePlatform` is a str-valued Enum but **not** a `str` subclass | `page.platform == ft.PagePlatform.ANDROID`, or `.value` / `.is_mobile()` / `.is_apple()` |
| `ft.SegmentedButton(selected={"a"})` | `TypeError: can not serialize 'set' object` from `msgpack._packer`, **only once a real client attaches** — the docstring still says "a set of `Segment.value`s", but the field is declared `list[str]` | `selected=["a"]`, read back with `selected[0]` |

Event handlers may take **zero** arguments or exactly one `ft.Event[T]` — a bare
`def on_click():` is fully supported and is the cleanest choice when the event is unused.

---

## Platform differences at runtime

### `ModuleNotFoundError: No module named 'pwd'` on iOS only

**Cause:** Flet's iOS Python runtime ships no `pwd` module and leaves
`LOGNAME`/`USER`/`LNAME`/`USERNAME` unset, so `getpass.getuser()` falls through to
`import pwd` and raises. Android ships `pwd` and is fine, which is why this only ever
shows up on an iOS run.

**Fix (app side, before importing the offending package):**

```python
import os
os.environ.setdefault("LOGNAME", os.environ.get("USER") or "fletuser")
```

Harmless on Android. Confirmed case: aiomysql's `DEFAULT_USER = getpass.getuser()`
guarded only by `except KeyError`. General lesson: a **pure-Python** package is not
guaranteed to import on iOS — test pure-Python packages on the iOS simulator too.

### A native library says the user "does not exist" on iOS

**Cause:** the C twin of the `pwd` entry above, and the `LOGNAME` workaround does **not** fix
it. iOS gives the app's uid no entry in the system passwd database, so a `getpwuid()` inside a
*compiled* dependency fails no matter what the environment says. Android synthesises an entry
for app uids, so the same code works there.

**Confirmed case:** libpq derives the connection's user from the OS when the string omits
`user`. On an iPhone 16 simulator `psycopg2.connect(host=..., port=...)` fails with
`OperationalError: local user with ID 501 does not exist` — raised *before* libpq validates any
other keyword.

**Fix (app side):** pass the username explicitly rather than letting the library infer it.

**Why it is worth an entry:** the error arrives early, so it *masks* whatever the call was
actually testing. The psycopg2 `libpq-probe` example asked libpq which features were compiled
in by reading which error came back, and on iOS every probe got this error instead — so a
GSSAPI-less build reported GSSAPI as **present**, in green, on a screen that otherwise looked
correct. If a probe decides something from "which error came back", make it require the error
it expects rather than treating anything-but-the-sentinel as success.

### A library silently returns nothing on iOS (empty list, zero results, no exception)

**Cause:** the iOS runtime reports `platform.system() == "iOS"` (PEP 730), not `"Darwin"`,
so code gating Darwin/BSD behaviour on `== "Darwin"` silently takes the Linux branch on a
Darwin ABI. The iOS twin of the Python 3.13+ `sys.platform == "android"` class.

**Fix:** in app code, test `in ("Darwin", "iOS", "iPadOS")`. When the gate is inside a
*dependency*, it needs a patched recipe instead — see the ifaddr entry in
`failure-catalogue.md`.

### Anything built for python-for-android / kivy

**Symptom:** on Android, an **uncatchable** `SIGABRT` at import (ART `JniAbort`) that no
`try/except` can trap; on iOS, `NotImplementedError` or a framework-load failure.

**Cause:** the package resolves `org.kivy.android.PythonActivity` or keys platform
detection off `ANDROID_ARGUMENT`/`KIVY_BUILD`. Those come from python-for-android, not
Flet's `serious_python`. Verified with plyer 2.1.0 on both platforms; in the same run
`autoclass("android.os.Build")` succeeded, proving pyjnius/JNI itself is fine under Flet.

**Fix:** there is no packaging fix — the backends need porting. Use Flet's own APIs, or
call native APIs directly:

```toml
[tool.flet.android]
dependencies = ["pyjnius"]
[tool.flet.ios]
dependencies = ["pyobjus"]
```

On Android, get Flet's activity (not kivy's):

```python
import os
from jnius import autoclass
activity = autoclass(os.getenv("MAIN_ACTIVITY_HOST_CLASS_NAME")).mActivity
```

On iOS, load frameworks via pyobjus's managed constants
(`load_framework(INCLUDE.Foundation)`), not absolute `/System/Library/Frameworks/…` paths,
which fail on the simulator.

---

## Adding entries

Same rules as `failure-catalogue.md`: lead with the **symptom as the reader sees it**,
give the cause in one paragraph, then the fix. State how to tell it apart from the
neighbouring wheel-layer failure when they look alike. If a claim is version-coupled, name
the version.
