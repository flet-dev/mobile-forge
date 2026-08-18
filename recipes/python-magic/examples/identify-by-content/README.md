# python-magic: what is this file?

One screen that writes ten files into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
and then asks [libmagic](https://www.darwinsys.com/file/) what each one actually is, ignoring the
name it was given. All ten are generated on the spot out of the standard library alone — a PNG
from `zlib` and `struct`, a GIF, a ZIP from `zipfile`, a gzip stream, a hand-written PDF with a
real cross-reference table, a SQLite database, a WAVE from `wave`, a POSIX tar and two text
files — so there is nothing bundled, nothing downloaded and no image or audio library anywhere in
the app. Together they come to 24,766 bytes.

Two of the ten are the point: **`holiday.png` is really a ZIP** and **`receipt` has no extension
at all and is really a PDF**. Both come back MATCH against their content and visibly disagree
with what `mimetypes.guess_type()` makes of their names, which is the package's entire reason to
exist.

What it demonstrates:

- **Content beats the filename, on every row.** Each card prints what the name suggests, then
  what [`magic.from_file()`](https://github.com/ahupp/python-magic#usage) says — MIME and full
  description — and a MATCH/MISMATCH chip against the format the generator actually wrote. The
  descriptions carry structure the MIME cannot: `PNG image data, 16 x 16, 8-bit/color RGB,
  non-interlaced`, or a SQLite line naming the engine version and page count.
- **The other half of the library, and where it stops.** A
  [`Slider`](https://flet.dev/docs/controls/slider/) chooses how many leading bytes are handed to
  `magic.from_buffer()`, from 1 to 4096, and every card carries a second answer with its own
  verdict. Dragging it reproduces the thresholds on the device: at the slider's stops, GIF and
  gzip flip to correct at **4** bytes, PDF at **8** (5 is really enough), WAVE at **12**, PNG at
  **16**, SQLite at **18**, and POSIX tar not until **512**, because tar's identity lives in a
  512-byte header block.
- **The one row that never flips.** `holiday.png`, the ZIP, is `application/octet-stream` at every
  stop but the 2-byte one — where `PK` alone reads as `text/plain` — *including the full file*:
  `from_buffer` cannot name a plain ZIP at any length, while `from_file` on those same bytes says
  `Zip archive data, made by v2.0 UNIX, …`. Two code paths through one library, agreeing on nine
  rows and disagreeing on one, with the disagreement visible rather than described.
- **Which delivery path this build got, computed on device.** The header line reads libmagic's
  version, the basename of the file the loader actually opened, the rule count parsed out of the
  database's own 16-byte header, whether that database is a real file or a buffer held in memory,
  [`page.platform`](https://flet.dev/docs/controls/page/#flet.Page.platform) and the Python
  version. On Android it is expected to name `libmagic.so` and an in-memory database; on iOS,
  `libmagic.fwork` and a file on disk. The recipe [`README.md`](../../README.md#android-notes)
  explains why the two differ and what the difference costs.
- **Honest behaviour where libmagic is absent.** The import is guarded, so a desktop `flet run`
  without a system libmagic shows `ImportError: failed to find libmagic.  Check your installation`
  in place of the header instead of failing to launch.

Every detection goes through one `ask()` helper that catches broad `Exception`, because the
failure modes here are not all `MagicException`: `from_file` raises `FileNotFoundError` or
`IsADirectoryError` before libmagic is consulted, and `from_buffer` raises `ctypes.ArgumentError`
for anything that is not immutable `bytes`. An unhandled exception in a Flet handler ends the
session with a crash screen.

The app only ever calls the **module-level** `magic.from_file` / `magic.from_buffer`, which cache
at most two `Magic` instances for the whole process. That is deliberate: on **both** platforms each
live instance holds its own ~10 MB copy of the rule database, so twenty rows built with twenty
instances would be a 200 MB screen. Everything runs synchronously — a full redraw is writing ten
files plus thirty detections, around 5 ms on a development machine — so it needs no
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and two gestures
cannot overlap. Recomputation is driven by the slider's `on_change_end`, which fires once on
release; `on_change` only updates the caption.

The files are rewritten on every refresh and every generator is deterministic — the gzip is
stamped `mtime=0` and the ZIP entries carry a fixed date, both because libmagic reads those
timestamps back into the description and a drifting description would look like the slider
affecting `from_file`. The one row that legitimately differs between devices is `library.db`,
whose description names the interpreter's own SQLite (`last written using SQLite version …`). It
writes no other files, makes no network requests and bundles no assets.

`python-magic` is a plain `[project] dependencies` entry: the recipe publishes wheels for every
Android ABI and every iOS slice Flet targets, and `flet-libmagic` follows it in on its own.
`pyproject.toml` pins both `flet` and `python-magic`, which is the combination that was verified.
`requires-python` stays at `>=3.10` — python-magic's own wheel is `py2.py3-none-any` and declares
a floor far below that, so every split uv resolves for is satisfiable — checked the way a consumer
meets it, by copying that `pyproject.toml` alone into an empty directory and running `uv lock`
there (56 packages, no error).

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device, emulator or
simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

`flet run` on the desktop is worth doing once, for what it shows rather than for what it proves:
it resolves python-magic from PyPI rather than from this index, so it uses the unpatched loader
and needs a system libmagic (`brew install libmagic`, `sudo apt install libmagic1`) with that
system's own — usually older — rule database. Expect the wording of some descriptions to differ
from a device, and treat nothing you see there as evidence about a phone.
