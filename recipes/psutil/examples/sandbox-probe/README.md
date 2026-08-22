# psutil sandbox probe

One screen that *is* the capability matrix. Twenty-one [psutil](https://psutil.io/) calls
run in a fixed order, each inside a guard that records either a short rendering of the
answer or the exception class that came back, and the results render as a numbered list with
a coloured dot per row. Nothing is filtered out — the calls that refuse are the point, and
the exception class is the payload.

What it demonstrates:

- **Which queries the Android sandbox actually allows**, rather than which ones psutil
  documents. The rows go system-wide first — `cpu_count`, `cpu_times`, `virtual_memory`,
  `swap_memory`, `disk_usage`, `disk_partitions` in both forms, `net_if_addrs`,
  `net_connections`, `boot_time` — then this process's own `/proc/<pid>/` tree, then
  `process_iter()`, reported as a count and the names behind it — that count is the sandbox
  story in one number.
- **Three outcomes, because two would lie.** Green is an answer, red is an exception, and
  amber is a call that returned without answering: `cpu_count(logical=False)` handing back
  `None`, or `swap_memory()` degrading to a `RuntimeWarning` and invented `sin`/`sout`
  values. The headline tally counts them separately, so a soft failure cannot pass for
  success.
- **Five answers checked against a second source that never touches psutil** —
  `os.cpu_count()`, `MemTotal` parsed by hand out of `/proc/meminfo`, RSS from
  `/proc/self/statm`, boot time derived from `time.CLOCK_BOOTTIME`, and `os.getcwd()` plus
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  against `Process().cwd()`. Each prints its own verdict, and a disagreement says so in
  capitals instead of being hidden. The CPU row also prints the affinity mask, but does not
  require it to match: Android confines an app to a cpuset, so a healthy device can
  legitimately let you run on fewer CPUs than it has online.
- **The Linux field names.** Every namedtuple is printed as `name=value` pairs, because the
  shapes here are not the ones a macOS development machine returns: `memory_info()` has
  seven fields against macOS's four, `virtual_memory()` eleven against eight.
- **RSS following a deliberate allocation.** A
  [`Slider`](https://flet.dev/docs/controls/slider/) picks 8–128 MB (decimal, 10⁶ bytes);
  releasing it allocates a `bytearray` of that size, writes one byte to every page so the
  kernel really commits them, and prints RSS before, while held and after `del`, with each
  delta. Whether the pages come back on release is an allocator question the device answers,
  not this app. The top stop is deliberately large enough to be visible in RSS, which on a
  low-RAM device means the app may be killed outright rather than reporting a failure:
  Android's low-memory killer terminates the process, so there is no `MemoryError` for the
  guard around the measurement to catch. That is itself the psutil-on-mobile lesson — an
  allocation you can watch is an allocation the OS can also refuse without telling Python.
- **Honest behaviour where psutil is absent.** The import is itself guarded, so on iOS and
  on a desktop `flet run` the screen starts, states the `ModuleNotFoundError` and why it
  happened, and disables the slider — instead of failing to launch.

The whole probe runs synchronously — about the 0.3 s `cpu_percent(interval=0.3)` spends
sampling — so it needs no
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and two runs
cannot overlap. It writes no files, makes no network requests and bundles no assets.

`src/sandbox.py` owns every psutil call, the cross-checks and the allocation measurement,
and returns plain tuples; `src/main.py` is the screen and its wiring.

psutil is declared under `[tool.flet.android] dependencies` rather than
`[project] dependencies`, because the recipe is Android-only and an iOS build has no wheel
to resolve. The cost is that a desktop `flet run` does not install psutil either, which is
why the import is guarded — see the [recipe README](../../README.md) for the rule behind it.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator:

```bash
uv run flet build apk
```

`flet build ipa` and `flet build ios-simulator` are worth running once, for what they show:
the iOS resolution never sees psutil, so the app builds and launches with an empty table and
the import error in its place.
