# bcrypt cost factor explorer

A slider picks a bcrypt cost factor — 8 to 15. Let it go and the app hashes one password at
that cost and verifies it, both best of two, and adds a row: the measured `hashpw` time, the
measured `checkpw` time, the ratio to the cost one step below, and a verdict against a 500 ms
login budget. Drag to each neighbouring cost in turn and the ratio column fills in.

The point is the one number the recipe README cannot give you: **milliseconds per cost factor
on the phone you actually ship to.** Nothing else on this page is worth much without it —
the cost factor is the single decision bcrypt asks a developer to make, and it is the one a
tutorial written on a workstation cannot make for you.

What it demonstrates:

- **The cost curve, measured, with a noise gauge beside it.** bcrypt doubles its work for every
  step up, exactly, so the `x cost-1` column should *centre* on `2.00x` — and each ratio is
  exactly the two numbers beside it divided, because they are rounded on the way in rather than
  on the way out. **A ratio well off 2.00 does not mean bcrypt changed, it means that row was
  contended** — take it again. Read the column that way round: it gauges how much to trust a
  row, and it is not a pass/fail check, because an individual reading is much rougher than the
  trend. Both figures in a row are best of two, and that is not a cure. A controlled
  best-of-three measurement in isolation held 2.00 ± 0.01 over costs 11 to 14; sweeping costs 8
  to 12 back to back on the same desktop under load (load average 19 on ten cores) held a median
  of 1.97 over 32 readings but spread them from 1.52x to 2.56x, more than half of them outside
  1.90–2.10. **A phone throttles and migrates between big and little cores, so expect at least
  that much scatter on device** — the median is the part that transfers, not any single row.
  Because the doubling is exact on average, two believable adjacent rows extrapolate the whole
  table — which is what the line under it does, predicting the next cost up and cost 31,
  [`gensalt`](https://github.com/pyca/bcrypt#adjustable-work-factor)'s accepted maximum.
- **That verifying is not cheaper than hashing.** The `checkpw ms` column sits beside
  `hashpw ms` and comes out the same, because `checkpw` *is* `hashpw` plus a constant-time
  compare. A login screen pays the full cost factor once per attempt, right password or wrong.
  "The same" is subject to the same noise floor as the ratio: across the sweeps above the two
  columns differed by a median of 6% and by as much as 30%, so read them as one number measured
  twice rather than as two numbers that ought to match digit for digit.
- **Correctness cross-checked three independent ways, so a wrong answer cannot look right.**
  `checkpw` returns `True` for the password and `False` for one changed letter. Separately,
  `hashpw(password, stored) == stored` is computed and has to agree with `checkpw` — that is
  the manual equivalent, and the demonstration that the salt lives inside the hash. A fourth
  row does what people actually reach for, `hashpw(password, gensalt()) == stored`, and it
  comes back `False`. The fifth is a fixed vector out of upstream's own test suite, which no
  amount of internal self-consistency would satisfy: it proves this device's bcrypt agrees
  with the reference implementation. All five run at cost 4, so they are nearly free.
- **The hash reading itself back.** The line under that table shows the stored hash is 60
  ASCII bytes, that its first 29 are the salt string, and the cost re-read out of bytes 4 and
  5 — which is why old hashes at an old cost keep verifying after you raise your default.
- **Where hashing belongs, settled on the device.** One button runs four cost-10 hashes one
  after another, then the same four across four threads, and prints both wall times with the
  speedup — 3.4–3.8x across six headless runs on an idle 10-core desktop, and 2.8x on the same
  machine under load, so read it the way the ratio column is read: comfortably above 1.0 is the
  finding, the exact multiple is not. bcrypt's extension releases
  the GIL for the whole hash, so that speedup is real rather than an artefact, and it is the
  device-side proof that a Flet app should push hashing to
  [`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and that
  simultaneous logins do not serialise behind each other. The core count sits on the header
  line, because it is the ceiling.
- **The 72-byte limit, corrected rather than repeated.** Every pre-5.0 tutorial says bcrypt
  silently ignores everything past 72 bytes. **5.0.0 raises `ValueError` instead**, and the
  text field is seeded with a 100-byte passphrase so the app opens showing the exact message.
  *Hash as typed* fails; *Truncate to 72 bytes* succeeds and verifies. The demonstration
  everyone quotes — two long passwords sharing one hash — is impossible here, because neither
  password can be hashed at all.
- **That the limit counts bytes, not characters.** The small fixed table walks the boundary
  both ways: 72 ASCII characters hash, 73 raise, `"é"` × 36 is 72 bytes and hashes, `"é"` × 37
  is 74 bytes at 37 characters and raises. Anything you validate as a character count lets
  unhashable passwords through. The last row passes the `str` in unencoded and gets `TypeError`
  — the mistake every call site risks once a
  [`TextField`](https://flet.dev/docs/controls/textfield/) is involved.
- **Compute off the UI thread, and one run at a time.** The measurement happens in
  `page.run_thread` with a spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run rather than one per pixel of the drag, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Every handler catches broad `Exception`, because an unhandled one in a Flet handler
  is a crash screen rather than a silent no-op. The re-entrancy guard is tested and set in the
  *handler*, not in the worker: `run_thread` only schedules, so a `disabled` set inside the
  worker would not have happened yet when Flet pushes the control states.
- **How the extension got loaded, on this device.** The header line carries
  `bcrypt.__version__`, the library's own default cost — `int(bcrypt.gensalt()[4:6])`, read
  out of a salt rather than typed in, so the number every tutorial copies is on screen as a
  fact — the Python version, `page.platform.value`, `os.cpu_count()`, and the basename of
  `bcrypt._bcrypt.__file__`. That last field is the one that cannot be predicted from the
  wheel: Flet relocates native extensions on both platforms, so it reports whatever the import
  system resolved, under a name that appears in no wheel. See the platform notes in the
  [recipe README](../../README.md).

The slider stops at 15 on purpose, and even that is slow: a measurement is four hashes at the
chosen cost, so the top of the slider is tens of seconds of work on a phone. `gensalt` accepts
up to 31, and 31 is not slow, it is unusable — the prediction line spells out how many hours
that is on this device, extrapolated from the row you just measured. A cost slider or config
field wired to what the library accepts hangs the app with no error and no way back.

The example writes no files and opens no sockets — bcrypt needs neither.

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
