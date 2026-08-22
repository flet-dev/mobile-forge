# bcrypt cost factor explorer

A slider picks a bcrypt cost factor — 8 to 15. Let it go and the app hashes one password at
that cost and verifies it, both best of two, and adds a row: the measured `hashpw` time, the
measured `checkpw` time, the ratio to the cost one step below, and a verdict against a 500 ms
login budget. Drag to each neighbouring cost in turn and the ratio column fills in.

The point is the one number a page of desktop measurements cannot give you: **milliseconds per
cost factor on the phone you actually ship to.** The cost factor is the single decision bcrypt
asks a developer to make, and a tutorial written on a workstation cannot make it for you.

What it demonstrates:

- **The cost curve, measured, with a noise gauge beside it.** bcrypt doubles its work for every
  step up, so the `x cost-1` column should *centre* on `2.00x`. **A ratio well off 2.00 does not
  mean bcrypt changed, it means that row was contended** — take it again. A phone throttles and
  migrates between big and little cores, so expect scatter; the trend across rows is the
  measurement, not any single row. The line underneath extrapolates the highest row to the next
  cost and to [`gensalt`](https://github.com/pyca/bcrypt#adjustable-work-factor)'s maximum of 31,
  which is not slow but unusable — a cost field wired to what the library accepts hangs the app
  with no error and no way back.
- **That verifying is not cheaper than hashing.** `checkpw` *is* `hashpw` plus a constant-time
  compare, so its column comes out beside `hashpw`'s: a login screen pays the full cost factor
  once per attempt, right password or wrong. Read the two as one number measured twice.
- **Correctness cross-checked three independent ways, so a wrong answer cannot look right.**
  `checkpw` against the manual `hashpw(password, stored) == stored`, which also demonstrates that
  the salt lives inside the hash; against the thing people reach for,
  `hashpw(password, gensalt()) == stored`, which is `False`; and against a fixed vector from
  upstream's test suite, which proves this device's bcrypt agrees with the reference
  implementation rather than merely with itself. All at cost 4, so nearly free. The line below
  reads the 29-byte salt and the cost back out of the stored hash.
- **Where hashing belongs, settled on the device.** One button runs four cost-10 hashes one after
  another, then the same four across four threads, and prints both wall times with the speedup.
  bcrypt's extension releases the GIL for the whole hash, so a figure comfortably above 1.0 is
  device-side proof that a Flet app should push hashing to
  [`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and that
  simultaneous logins do not serialise. The core count on the header line is the ceiling.
- **The 72-byte limit, corrected rather than repeated, and counted in bytes.** Pre-5.0 tutorials
  say bcrypt silently ignores everything past 72 bytes; 5.0.0 raises `ValueError` instead, and
  the text field is seeded with a 100-byte passphrase so the app opens showing the exact message.
  *Hash as typed* fails; *Truncate to 72 bytes* succeeds and verifies. The fixed table walks the
  boundary both ways — 72 ASCII characters hash, 73 raise, `"é"` × 36 is 72 bytes and hashes,
  `"é"` × 37 is 74 bytes at 37 characters and raises — and its last row passes the `str` in
  unencoded and gets `TypeError`, the mistake every call site risks once a
  [`TextField`](https://flet.dev/docs/controls/textfield/) is involved.
- **Compute off the UI thread.** Each measurement runs in `page.run_thread` with a spinner up,
  started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run rather than one per pixel of the drag, and ending with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Workers catch broad `Exception`, because `run_thread` drops what a worker raises and an
  unhandled exception in a handler is a crash screen. The re-entrancy guard is tested and set in
  the *handler*, not in the worker.
- **How the extension got loaded, on this device.** The header line carries `bcrypt.__version__`,
  the library's own default cost — read out of a salt rather than typed in — the Python version,
  the platform, `os.cpu_count()`, and the basename of `bcrypt._bcrypt.__file__`. That last field
  cannot be predicted from the wheel: Flet relocates native extensions on both platforms, so it
  reports whatever the import system resolved, under a name that appears in no wheel.

`src/hashing.py` owns every call into bcrypt and returns plain values; `src/main.py` is the Flet
app around it. The example writes no files and opens no sockets — bcrypt needs neither.

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

`pyproject.toml` pins both `flet` and `bcrypt`, which is the combination that was verified.
`requires-python` stays at `>=3.10`: bcrypt's own floor is `>=3.8`, so every split uv resolves
for is satisfiable.
