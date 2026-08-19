# biopython

[Biopython](https://biopython.org/) is the standard Python toolkit for computational
molecular biology: sequence objects, translation and the genetic code, ~50 file formats
through [`Bio.SeqIO`](https://biopython.org/wiki/SeqIO) and `Bio.AlignIO`, pairwise
alignment, substitution matrices, restriction enzymes, phylogenetic trees, PDB structures,
motifs and clustering.

Almost all of that is arithmetic on strings and small arrays, which makes a phone a
perfectly reasonable place to run it — a field app can parse a FASTA, translate it, align
it against a reference and score it with BLOSUM62 without a network round trip. What a
phone cannot do is the half of Biopython that shells out to external programs or talks to
NCBI; this page is mostly about which half is which, plus one Android packaging entry you
have to add yourself.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "biopython",
]

[tool.flet.android]
extract_packages = ["Bio"]
```

The [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
**not optional on Android** if your app loads a substitution matrix or parses saved NCBI
or BLAST XML — see [Android notes](#android-notes) for the exact failures. It is an *import*
name, so it is `Bio` with a capital B, not the `biopython` distribution name. `BioSQL`, the wheel's
other top-level package, is [not usable on mobile at all](#things-to-know).

It is not free: the entry names one package and `Bio` is the whole wheel, so all 10.8 MiB of it
is written out of `sitepackages.zip` onto the filesystem, 3.8 MiB of that the
`Bio/Entrez/DTDs/` tree an app that only touches sequences will never open. What that costs in
disk and in first-launch time on a real device is not established here.

List nothing else. The wheel's `Requires-Dist` is a single line, `numpy` — add numpy to your
own dependency list only if your code imports it directly. There is no `flet-lib*` chain of
biopython's own: its thirteen extension modules need nothing beyond `libc`, `libdl`, `libm`
and `libpython` on Android, and `Python.framework` plus `libSystem` on iOS. You will still
see `flet-libcpp-shared` scroll past in an Android build — that is numpy's dependency, not
biopython's, and it is why the stack's Python floor is 3.11 rather than biopython's own 3.10.

Nineteen wheels at the current build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator), plus a 32-bit `android_24_x86` wheel that exists on the 3.12 leg only. Nothing
on PyPI competes for a mobile target — upstream's own 1.87 release publishes 31 files, all
macOS, Linux and Windows.

## Storage

Biopython reads and writes ordinary paths — `SeqIO.write(records, path, "fasta")` and
`SeqIO.parse(path, "fasta")` take whatever you hand them — so put anything you want to keep
in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "sequences.fasta")
```

[`SeqIO.index_db`](https://biopython.org/docs/latest/api/Bio.SeqIO.html#Bio.SeqIO.index_db)
belongs there too. It builds a stdlib-`sqlite3` index beside your sequence files and gives
you random access by id without holding the records in memory — 200 FASTA records indexed
into a 20 kB `.db` and read back correctly, measured on the host. `sqlite3` is the only
thing it and the MAF indexer need, and both mobile Python builds ship it (the
[apsw recipe](../apsw/README.md) compares that module against apsw on both platforms).

Nothing in the wheel writes anywhere on its own, with one exception:
`import Bio.Entrez.Parser` creates `~/.config/biopython/Bio/Entrez/{DTDs,XSDs}` while the
import is still running — see [iOS notes](#ios-notes) for why that is worth knowing.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`offline-seqlab`](examples/offline-seqlab) — parses, translates and aligns sequences on
  device, every answer checked against one computed by hand.

## Threading

**Alignment holds the GIL for the entire call.** Nothing in the wheel releases it: the
seventeen shipped `.c`/`.h` files contain no `Py_BEGIN_ALLOW_THREADS`, `PyEval_SaveThread`
or `Py_UNBLOCK_THREADS`, and no compiled module on either platform references a GIL or
`pthread` symbol at all. A canary thread confirms the consequence — its tick rate across a
191 ms
[`PairwiseAligner.score`](https://biopython.org/docs/latest/api/Bio.Align.html#Bio.Align.PairwiseAligner)
call was 3.5% of idle, tracking a GIL-holding `sorted()` control at 2.5% rather than a
GIL-releasing `zlib.compress` control at 99.0%. `sys.setswitchinterval` cannot help, because
there are no bytecode boundaries inside the C call to switch at.

So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does
not keep the UI responsive *during* an alignment — it only keeps the structure right.
**Chunk the work**: align one pair per `run_thread` call and update between pairs, rather
than looping over a batch inside one worker. What that costs is the length of a single
alignment, which is worth knowing in advance. Median per-call times on a development
machine, global mode with match=+2 / mismatch=−1 / open=−2 / extend=−0.5 on random DNA at
5% divergence:

| length | `score()` | `align()[0]` and `str()` |
| ---: | ---: | ---: |
| 100 nt | 0.01 ms | 0.08 ms |
| 300 nt | 0.11 ms | 0.38 ms |
| 1,000 nt | 1.27 ms | 4.42 ms |
| 3,000 nt | 11.2 ms | 37.9 ms |
| 10,000 nt | 126 ms | 510 ms |

A phone is slower than that, and no device measurement is quoted here — the
[example](examples/offline-seqlab) measures it on the device you actually care about. The
shape is the useful part: cost is quadratic in length, and building and formatting the
alignment costs roughly three to four times what scoring it does.

End every `run_thread` handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads — and wrap the body in `try/except`, because `run_thread` never
retrieves the worker's future and an exception in it surfaces nowhere at all.

Biopython imposes no thread rules of its own; there is no shared handle to serialise.

## Android notes

`[tool.flet.android] extract_packages = ["Bio"]` prevents three failures, and all of them
are invisible until an app reaches for them.

Flet ships pure-Python site-packages inside `sitepackages.zip` and imports from it with
`zipimport`. Three code paths in Biopython read bundled data through a real
`__file__`/`__path__` path, which a zip cannot serve:

- **Every substitution matrix.**
  [`substitution_matrices.load()`](https://biopython.org/docs/latest/api/Bio.Align.substitution_matrices.html)
  does `os.path.realpath(__file__)` and then `os.listdir`/`open` under `…/data`. From a zip,
  `load()` raises `NotADirectoryError: [Errno 20] Not a directory:
  …/sitepackages.zip/Bio/Align/substitution_matrices/data`, `load("BLOSUM62")` the same on
  `…/data/BLOSUM62`, and `PairwiseAligner(scoring="blastn")` the same on `…/data/BLASTN`.
  That takes out all protein alignment and the `blastn`/`megablast`/`blastp` presets.
- **Locally saved NCBI XML.** `Bio/Entrez/Parser.py` builds its DTD directory from
  `Entrez.__path__[0]`, so `Entrez.read()` on a file you already downloaded raises
  `NotADirectoryError` on `…/sitepackages.zip/Bio/Entrez/DTDs/esearch.dtd`. Parsing saved
  NCBI XML offline is a legitimate thing to want even though Entrez itself is a web client,
  so this is not covered by "just don't use Entrez".
- **Locally saved BLAST XML.** `Bio/Blast/_parser.py` resolves the DOCTYPE out of that same
  `Entrez.__path__[0]` directory, so `Blast.read()`/`Blast.parse()` on a saved BLAST report
  raise `NotADirectoryError` on `…/sitepackages.zip/Bio/Entrez/DTDs/NCBI_BlastOutput.dtd`,
  and BLAST XML2 fails the same way under `…/XSDs`. The deprecated `Bio.Blast.NCBIXML`
  parser is the only BLAST reader that touches no bundled file, and it does keep working.

Everything else tried keeps working from the zip: `import Bio`, `Seq` and its
`reverse_complement`/`translate`, `SeqIO.parse`, `SeqUtils.gc_fraction`, `Bio.Restriction`,
`Bio.Phylo` including `draw_ascii`, and a default `PairwiseAligner().score` — which is
exactly why an app that only ever uses match/mismatch scoring never notices the entry is
missing.

This was established by reproducing Flet's Android shape on the host with a real
`zipimport` — the pure-Python tree in a `sitepackages.zip`, the extensions in a flat
directory resolved by a `.soref` meta-path finder — and running the
[example app](examples/offline-seqlab) against it: four panels pass and the BLOSUM50 panel
prints the `NotADirectoryError` above. The Entrez and BLAST cases were exercised the same
way, reading saved XML directly, each against a control run from an ordinary directory that
parsed it fine. **None of it has been confirmed on an Android device**; see
[Build notes](#build-notes-maintainers).

## iOS notes

No `extract_packages` equivalent is needed or exists: iOS keeps site-packages as a real
directory in the app bundle, so both `__file__`-relative reads above resolve there.

The one iOS-specific hazard is `import Bio.Entrez.Parser`. Its `DataHandlerMeta.__init__`
runs at class creation and, with no cache directory configured, calls
`os.path.expanduser("~")` and two `os.makedirs`. Flet's iOS Python ships no `pwd` module, so
if `HOME` is unset `expanduser` returns the literal string `~` and the import silently
creates a directory named `~` in the process working directory — measured by simulating that
runtime on the host (`sys.modules["pwd"] = None`, `HOME` removed), which produced
`./~/.config/biopython/Bio/Entrez/{DTDs,XSDs}`. It does not raise, which is what makes it
easy to miss. If anything in your app imports it, set a home first:

```python
os.environ.setdefault("HOME", os.getenv("FLET_APP_STORAGE_DATA", "."))
```

`Bio.Entrez.local_cache` is not a usable lever — `Parser` reads it during its own import, so
there is no window in which to set it. Most apps are unaffected: plain `import Bio.Entrez`
does not pull `Parser` in, and neither `from Bio import SeqIO` nor `import Bio.PDB` imports
`Bio.Entrez` at all. What `HOME` actually is on Flet's mobile runtimes was not established
here, so the `setdefault` above is the cheap way to stop caring.

Otherwise the two platforms agree completely: normalise the ABI tag in the extension
filenames and the Android arm64-v8a and iOS device wheels list the identical 659 entries,
including the same thirteen extension modules. Nothing in the tree gates on `sys.platform`,
and the single `platform.system()` check only distinguishes Windows from everything else —
so the iOS `platform.system() == "iOS"` trap does not apply.

## Things to know

- **Old tutorial code fails at *import*, not at the line that matters.** `Bio.Alphabet`
  raises `ImportError: Bio.Alphabet has been removed from Biopython…`; `Bio.Application`,
  `Bio.Align.Applications`, `Bio.Blast.Applications` and `Bio.SubsMat` all raise
  `ModuleNotFoundError`; and `Bio.SeqUtils.GC` is gone, replaced by
  [`gc_fraction`](https://biopython.org/docs/latest/api/Bio.SeqUtils.html#Bio.SeqUtils.gc_fraction),
  which returns a *fraction* rather than a percentage. Since an unhandled exception in a
  Flet event handler produces a crash screen rather than a message, this shows up as a crash
  with nothing explaining it — wrap each section of your app in `try/except` and render
  `type(e).__name__` and `str(e)`.
- **Use `Bio.Align.PairwiseAligner`, not `Bio.pairwise2`.** The old module still imports and
  still returns the same score, so nothing forces you off it; it just emits a
  `BiopythonDeprecationWarning` and ran 6.2× slower on a 600 nt pair (2.97 ms against
  0.48 ms, medians of nine, and the same ratio at 300 and 1,000 nt). It also builds every
  optimal alignment eagerly, where `PairwiseAligner.align()` returns a lazy object that
  reported `len() = 184,756` in 0.03 ms without materialising anything. `mode`,
  `match_score`/`mismatch_score` or `substitution_matrix`, and
  `open_gap_score`/`extend_gap_score` cover what `globalms`/`localms` did.
- **Check which aligner you actually got.** A fresh `PairwiseAligner` is *global*
  Needleman-Wunsch with match=1.0, mismatch=0.0, open=extend=−1.0 and no substitution matrix
  — which means a mismatch costs nothing and only matches are rewarded, rarely what you
  want. Setting affine gap costs switches it to Gotoh, `mode="local"` to Smith-Waterman, and
  1.87 also accepts `mode="fogsaa"`. The `algorithm` attribute names whichever one it
  picked, which is worth printing next to any score you show a user.
- **Five modules shell out to external binaries and are dead on mobile:** `Bio.PDB.DSSP`,
  `Bio.PDB.NACCESS`, `Bio.PDB.PSEA`, `Bio.PDB.ResidueDepth` and `Bio.Phylo.PAML`. They invoke
  `dssp`, `naccess`, `psea`, `msms` and the PAML suite; none ships in the wheel and none
  exists on a phone.
- **Six subpackages need a third-party library that is not in the wheel**, and they say so
  cleanly rather than crashing: `Bio.Graphics` wants ReportLab, `Bio.PDB.binary_cif` msgpack,
  `Bio.PDB.mmtf` mmtf-python, `Bio.Phylo.CDAOIO` RDFlib, `Bio.phenotype.pm_fitting` scipy and
  `Bio.motifs.jaspar.db` MySQLdb; `Phylo.draw` wants matplotlib. Of those, only msgpack,
  scipy and matplotlib exist on pypi.flet.dev — reportlab, mmtf-python and rdflib return 404,
  so `Bio.Graphics` (GenomeDiagram, BasicChromosome, the KGML renderer) and CDAO have no
  route at all.
  [`Phylo.draw_ascii`](https://biopython.org/wiki/Phylo) is the offline substitute for
  `Phylo.draw`: pure Python, and it renders a text tree into an `ft.Text` given a monospace
  font.
- **`Bio.Entrez` and `Bio.Blast.NCBIWWW` are web clients**, so they do nothing useful
  offline; the DTDs `Entrez` ships are for parsing XML you already have. Both import fine,
  which is the trap. Reading that saved XML back is a different matter, and the modern
  `Bio.Blast.read`/`Bio.Blast.parse` are *not* exempt from it: they resolve the report's
  DOCTYPE out of `Entrez.__path__[0]/DTDs`, so they need the same Android
  `extract_packages` entry the matrices do. Only the deprecated `Bio.Blast.NCBIXML` parser
  drives `expat` without opening a bundled file.
- **`BioSQL` is effectively unusable.** Its default driver is `MySQLdb`, which is not on
  pypi.flet.dev; `open_database(driver="sqlite3", db=…)` does create the file, but the first
  `new_database()` raises `sqlite3.OperationalError: no such table: biodatabase` because the
  BioSQL schema DDL is not in the wheel (zero `.sql` files). Use `SeqIO.index_db` instead, or
  ship the schema in `src/assets/` and run it yourself.
- **Exactly two imports warn.** `Bio.pairwise2` gives a `BiopythonDeprecationWarning` and
  `Bio.codonalign` a `BiopythonExperimentalWarning`; `import Bio` and the modern API are
  silent. Separately, `Seq.translate()` on a sequence whose length is not a multiple of three
  warns `BiopythonWarning: Partial codon…` at call time and translates the whole codons.
- **Size.** The Android arm64-v8a wheel is 2.55 MiB and unpacks to 10.8 MiB across 659
  entries (armeabi-v7a 2.53 / 10.7; iOS device 2.55 / 11.5). Of the unpacked total,
  **35.3% — 3.8 MiB across 291 files — is `Bio/Entrez/DTDs/`**, which only `Entrez.read`
  touches, and another 6.8% is the `.c`/`.h` sources upstream ships in its own wheels too,
  which nothing runs. Adding numpy, a hard dependency, takes the pair to about 9.1 MiB of
  wheels and 32 MiB unpacked before your own assets. None of this is configurable — it is
  upstream's own wheel layout — but Flet compiles `.py` to `.pyc` and zips site-packages, so
  what lands on the device is smaller than the unpacked figure.
- **Nothing here is a mobile fork.** All 298 `.py` files and all 343 data files in the wheel
  are byte-identical to the PyPI release of the same version, so
  [upstream's documentation](https://biopython.org/docs/latest/Tutorial/index.html) applies
  unchanged and anything you work out on a laptop transfers — except for the loader,
  external-binary and size questions this page is about.

## Build notes (maintainers)

`meta.yaml` is a name, a version and a build number. The shipped C includes nothing but
`Python.h`, libc headers and biopython's own — no numpy headers, no third-party library — so
the sdist cross-compiles as-is with no `requirements`, no patch and no flag. That is the
recipe's whole shape, and a bump that needs more than a version change is a shape change
worth pausing over.

What has no home in `meta.yaml`, in rough order of how quietly it can go wrong:

- **The recipe declares no `extract_packages`, and its tests would not notice.**
  `tests/test_biopython.py` exercises `Seq.reverse_complement`/`complement` and a FASTA round
  trip through a `StringIO` — two pure-Python paths that pass happily from
  `sitepackages.zip`, which is why CI is green while `substitution_matrices.load()` is not.
  The `Bio` entry in [Install](#install) is therefore something every consumer has to add by
  hand today. Closing the gap means confirming the failure on a device, then adding both an
  `extract_packages: [Bio]` key here and a test that loads BLOSUM62 and parses both a saved
  Entrez XML and a saved BLAST report. Note that a recipe's own `extract_packages` list is
  read only by the on-device test app and travels nowhere near a consumer's build, so the
  README entry stays either way.
- **The consumer-facing claims are almost all about upstream's tree, not the build.** The
  five `subprocess` users, the six optional-dependency guards, the removed
  `Bio.Alphabet`/`Applications`/`SubsMat` surface, the three `__file__` sites and the five
  `Entrez.__path__[0]` reads — two in `Bio/Entrez/Parser.py`, three in
  `Bio/Blast/_parser.py` — are all re-derivable by grepping the extracted wheel, and a minor
  release can move any of them. Grep `__path__` as well as `__file__`: the `Bio/Blast` three
  are what make saved BLAST XML an `extract_packages` case, and they are easy to miss.
- **The "no GIL release" claim underpins the whole [Threading](#threading) section.** It
  rests on two independent checks that are cheap to repeat: zero
  `Py_BEGIN_ALLOW_THREADS`/`PyEval_SaveThread`/`Py_UNBLOCK_THREADS` across the seventeen
  shipped `.c`/`.h` files, and no GIL or `pthread` symbol in any compiled module's dynamic
  symbols on either platform. If upstream ever releases the GIL around the DP loop, the
  advice to chunk work per pair becomes wrong rather than merely conservative.
- **The thirteen-extension / four-`NEEDED`-library claim is what says this recipe has no
  native dependency chain.** Re-read the Android wheel's `DT_NEEDED` entries after a bump: a
  new library appearing there (`libc++_shared` above all) means the recipe shape has to
  change. The iOS side should stay MH_DYLIB with only `Python.framework` and `libSystem`.
- **The absence of `Bio.Align._aligners`.** 1.87 splits the pairwise engine across
  `_pairwisealigner` and `_aligncore`; older code and older documentation name a module that
  does not exist here. If a bump reunifies them, the extension count in this page moves.
- **The sizes, the 35.3% DTD share and the wheel/leg matrix are measured**, including that
  the 32-bit `android_24_x86` wheel exists on the 3.12 leg only. Re-measure rather than
  scaling the old numbers, and re-count the legs — that asymmetry follows from Flet's Python
  builds, not from this recipe.
- **The timing table and the 6.2× `pairwise2` ratio are desktop numbers** on random DNA at
  5% divergence, quoted as shape rather than as a budget. They move with the machine, not
  with the recipe; the example app is what produces a device figure.
