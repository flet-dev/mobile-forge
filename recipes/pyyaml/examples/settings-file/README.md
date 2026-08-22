# PyYAML settings file

A slider sets how many service blocks to put in a settings document — 25 to 400. Let it go and the
app emits the document, saves it into app storage, reads it straight back with both of PyYAML's
loaders, and reports what each one cost. Below that, a text field holds a five-line settings
snippet you can break, parsed by both loaders side by side.

The point is that the recipe README's two central claims get checked on the phone instead of
quoted at you: that the C accelerator is worth switching to, and that switching is safe.

`src/settings.py` holds every line that touches PyYAML and returns plain strings and tuples;
`src/main.py` is the screen and its background-thread wiring.

What it demonstrates:

- **The gap the whole recipe exists to close.** The same bytes are read twice — once with
  [`yaml.safe_load`](https://pyyaml.org/wiki/PyYAMLDocumentation), which runs PyYAML's
  pure-Python scanner, and once with `yaml.load(text, Loader=CSafeLoader)`, which runs libyaml —
  and both times land in the table with the ratio between them. Emitting is measured the same way,
  `yaml.safe_dump` against `Dumper=CSafeDumper`.
- **Proof the swap is a drop-in, computed rather than asserted.** The C row says "same object"
  only because `parsed_c == parsed_pure` came out true, and "identical bytes" only because the two
  emitters produced the same string. If a future libyaml ever diverged, those cells would read
  `DIFFERENT OBJECT` / `DIFFERENT BYTES` and the speedup beside them would be worth nothing.
- **A file the app really wrote.** The document goes to `settings.yaml` in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  and is read back off disk, so the timings run on bytes that made a round trip rather than on a
  string in memory. The byte count in the summary is `os.path.getsize` of that file, and it matches
  the emit row's own count.
- **`allow_unicode=True` and `sort_keys=False`, in the file you can go and look at.** The document
  carries an accented label on purpose: with the two arguments the file reads
  `label: café — edge fleet`, and without them PyYAML escapes both the accent and the em dash and
  puts the top-level keys in alphabetical order.
- **The one thing the two loaders genuinely disagree about.** The editor is seeded with
  `retries:\t3` — a tab where a space belongs. `CSafeLoader` parses it into five keys;
  `SafeLoader` raises `ScannerError` at line 2, column 9 of the same file. Edit the text and press
  the button to try your own.
- **What an error report can and cannot say.** For each loader the table shows the exception class,
  the line and column, and whether `problem_mark.get_snippet()` produced anything. The seeded
  document only breaks the pure loader, so indent the `retries` line by two spaces to break both:
  the two rows then read `ScannerError` at line 2, column 10 with `caret` `yes` against `none`.
  Break a *later* line instead and the columns stop agreeing, because the pure loader still stops
  at the tab on line 2 first — the mark is where that loader gave up, not where the file is wrong.
  libyaml never hands PyYAML the buffer a caret would point into, so a config-editing screen has
  to draw its own.
- **How the extension got loaded, on this device.** The header line carries `yaml.__version__`,
  `yaml._yaml.get_version_string()` (the libyaml actually compiled in), `yaml.__with_libyaml__`,
  the Python version, `page.platform.value`, and the basename of `yaml._yaml.__file__`. That last
  field is the one that differs between the platforms, because Flet moves native extensions out of
  site-packages: run the app on each and read the two values off the screen. The
  [recipe README](../../README.md) explains what they mean and why code should not build paths
  from them.
- **Compute off the UI thread** — the run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The body is wrapped in `try/except` because `run_thread` discards anything a worker
  raises, and it empties the table on the way out so last run's timings cannot sit under this
  run's error. Keeping one writer on the file is the click handler's job, not the worker's: it
  tests and sets the slider's `disabled` itself, where that is synchronous, and disables the
  parse button alongside it so nothing else rewrites the same column from another thread.

The document is generated in code from the slider position with no randomness, so the same
position produces the same bytes on every install and two devices can be compared directly. The
`from yaml import CSafeDumper, CSafeLoader` at the top of `src/settings.py` is deliberate too: it
is the recommended shape, because a wheel without the accelerator would fail there instead of
running several times slower in silence.

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

`pyproject.toml` pins both `flet` and `pyyaml`, which is the combination that was verified.
`requires-python` stays at `>=3.10`: PyYAML's own floor is `>=3.8`, so every split uv resolves for
is satisfiable.
