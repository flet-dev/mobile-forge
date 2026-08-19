# offline-seqlab

A one-screen sequence lab that never opens a socket and bundles no asset. It writes a FASTA
to app storage and reads it back, translates the records it just parsed, aligns two pairs
whose scores are known in advance, and times an alignment at a length you pick with the
slider.

Every checked number is printed next to one obtained a different way, so the first four
panels state a verdict rather than a value you have to trust; the fifth is a measurement,
and its number is the point:

- **FASTA round trip through app storage.** Four records are built in code, written with
  [`SeqIO.write`](https://biopython.org/docs/latest/api/Bio.SeqIO.html) to
  `sequences.fasta` in
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
  and re-parsed with `SeqIO.parse` from the path — not from a `StringIO`, so the file really
  landed on the device. Ids, descriptions and sequences are compared exactly. FASTA has no
  separate description field, so the check expects the title line back as `id description`,
  which is what teaches the actual format semantics rather than hiding them.
- **GC and translation, checked by hand.** For each record,
  [`SeqUtils.gc_fraction`](https://biopython.org/docs/latest/api/Bio.SeqUtils.html#Bio.SeqUtils.gc_fraction)
  and `Seq.translate()` sit next to `(G+C)/len` and a 64-entry codon dict written out in the
  app, with an equality column. Note `gc_fraction` returns a *fraction*; the old
  `SeqUtils.GC`, which returned a percentage, no longer exists.
- **Alignment score, checked by arithmetic.** `GATTACA` vs `GATCACA` in global mode with
  match=+2, mismatch=−1 and gaps priced at −10, so the optimal alignment cannot contain a
  gap and the score is 6×2 + 1×(−1) = 11 with no alignment theory involved. The printed
  alignment shows the single `.` column the arithmetic assumed.
- **Alignment scores, checked against a textbook.** `HEAGAWGHEE` vs `PAWHEAE` under
  BLOSUM50 with a linear gap cost of 8 — the worked example in Durbin et al.,
  *Biological Sequence Analysis* (1998) §2.3, published as 1 globally and 28 locally.
  Each row prints the `mode`, the `algorithm`
  [`PairwiseAligner`](https://biopython.org/docs/latest/api/Bio.Align.html#Bio.Align.PairwiseAligner)
  actually selected, and the gap costs it used.
- **How long one alignment takes on this device.** The
  [slider](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) picks a query
  length from 200 to 4000 nt; the app regenerates a random pair at 5% divergence and reports
  milliseconds per `score()` call. Recomputation runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and
  ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. biopython holds the GIL for the whole call, so the thread pool buys no
  concurrency here — the measured milliseconds *are* how long the Python side is frozen.

**Each panel catches its own exceptions and renders the class and message.** That is the
point of the fourth panel: it is the only one that loads a substitution matrix, so on
Android without `[tool.flet.android] extract_packages = ["Bio"]` — which this app's
`pyproject.toml` carries — it is the one that shows
`NotADirectoryError: [Errno 20] Not a directory: …/sitepackages.zip/Bio/Align/substitution_matrices/data/BLOSUM50`
while the other four keep working. Without the guard, the same failure would end the Flet
session with a crash screen that names nothing.

`requires-python` is `>=3.11` because that is numpy's floor at the version pypi.flet.dev
publishes, and numpy is biopython's one hard dependency.

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
