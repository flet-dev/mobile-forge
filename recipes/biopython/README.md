# biopython

[Biopython](https://biopython.org/) is the standard Python toolkit for computational
molecular biology: sequence objects, translation and the genetic code, dozens of file formats
through [`Bio.SeqIO`](https://biopython.org/wiki/SeqIO) and `Bio.AlignIO`, pairwise
alignment, substitution matrices, restriction enzymes, phylogenetic trees, PDB structures,
motifs and clustering.

Almost all of that is arithmetic on strings and small arrays, which makes a phone a
perfectly reasonable place to run it — a field app can parse a FASTA, translate it, align
it against a reference and score it with BLOSUM62 without a network round trip. The other
half of Biopython shells out to external programs or talks to NCBI, and that half does not
travel.

## Install

Add Biopython to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "biopython",
]

[tool.flet.android]
extract_packages = ["Bio"]
```

The [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
**not optional on Android** if your app loads a substitution matrix or parses saved NCBI or
BLAST XML — [Android](#android) has the exact failures. It is an *import* name, so it is
`Bio` with a capital B, not the `biopython` distribution name. `BioSQL`, the wheel's other
top-level package, is [not usable on mobile](#things-to-know).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`offline-seqlab`](examples/offline-seqlab) — parses, translates and aligns sequences on
  device, every answer checked against one computed by hand.

## Usage in a Flet app

Biopython returns strings, numbers and small objects that print as one, so a parse, a
translation or an alignment goes into an [`ft.Text`](https://flet.dev/docs/controls/text/)
as it is — in a monospace font, because sequence output only lines up in one:

```python
from Bio import Align, SeqIO

records = list(SeqIO.parse(path, "fasta"))
aligner = Align.PairwiseAligner(mode="local", match_score=2, mismatch_score=-1)
view = ft.Text(
    f"{records[0].seq.translate()}\n{aligner.align(records[0].seq, reference)[0]}",
    font_family="monospace",
    selectable=True,
)
```

Configure
[`PairwiseAligner`](https://biopython.org/docs/latest/api/Bio.Align.html#Bio.Align.PairwiseAligner)
once and reuse it. `align()` is lazy — it returns an object you index into — and
`aligner.score(a, b)` is the cheaper call when the number is all you need.

### Storage

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
thing it and the MAF indexer need, and both mobile Python builds ship it.

An index you can rebuild belongs in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
instead, and a reference FASTA shipped with the app is an
[asset](https://flet.dev/docs/cookbook/assets) whose absolute path comes from
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

Nothing in the wheel writes anywhere on its own, with one exception:
`import Bio.Entrez.Parser` creates a cache directory under `$HOME` while the import is still
running — see [Entrez cache directory](#entrez-cache-directory).

### Threading

**Alignment holds the GIL for the entire call.** Nothing in the wheel releases it. A canary
thread confirms the consequence — its tick rate across a 191 ms
`PairwiseAligner.score` call was 3.5% of idle, tracking a GIL-holding `sorted()` control at
2.5% rather than a GIL-releasing `zlib.compress` control at 99.0%. `sys.setswitchinterval`
cannot help, because there are no bytecode boundaries inside the C call to switch at.

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
retrieves the worker's future and an exception in it surfaces nowhere at all. There is no
shared handle to serialise, so nothing here needs the application-wide lock a document or a
database connection would.

### Android

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
missing. iOS needs no equivalent entry and has none: it keeps site-packages as a real
directory in the app bundle, so the same reads resolve there.

### Entrez cache directory

`import Bio.Entrez.Parser` is the one import in the wheel with a side effect. Its
`DataHandlerMeta.__init__` runs at class creation and, with no cache directory configured,
calls `os.path.expanduser("~")` and two `os.makedirs`. Flet's iOS Python ships no `pwd`
module, so if `HOME` is unset `expanduser` returns the literal string `~` and the import
silently creates a directory named `~` in the process working directory — measured by
simulating that runtime on the host (`sys.modules["pwd"] = None`, `HOME` removed), which
produced `./~/.config/biopython/Bio/Entrez/{DTDs,XSDs}`. It does not raise, which is what
makes it easy to miss. If anything in your app imports it, set a home first:

```python
os.environ.setdefault("HOME", os.getenv("FLET_APP_STORAGE_DATA", "."))
```

`Bio.Entrez.local_cache` is not a usable lever — `Parser` reads it during its own import, so
there is no window in which to set it. Most apps never reach this at all: plain
`import Bio.Entrez` does not pull `Parser` in, and neither `from Bio import SeqIO` nor
`import Bio.PDB` imports `Bio.Entrez`. What `HOME` is on each mobile runtime is not
established here, so the `setdefault` above is the cheap way to stop caring.

### App size

The wheel is about 2.7 MB compressed on every slice and unpacks to about 11 MB on Android,
12 MB on iOS. Roughly 35% of that — 4.0 MB across 291 files — is `Bio/Entrez/DTDs/`, which
only `Entrez.read` and `Blast.read` touch, and another 7% is the `.c`/`.h` sources upstream
ships in its own wheels too, which nothing runs. With numpy, which biopython requires, expect
roughly 9–10 MB of wheels and a little over 30 MB unpacked before your own assets.

The layout is upstream's own and not configurable, and on Android `extract_packages = ["Bio"]`
is what makes the unpacked figure real: the whole package is written out of `sitepackages.zip`
onto the filesystem, DTD tree included, even for an app that only touches sequences. What that
costs in first-launch time on a real device is not established here.

The lever is the architecture list: use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These figures describe the package payload, not the
exact amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, whose Python files are the same ones the mobile
wheel carries — so anything you work out at a desk transfers. What does not transfer is the
loader: on desktop, site-packages is a real directory and `pwd` exists, so none of the
`NotADirectoryError` failures above and none of the `~` behaviour can appear there. Validate
the three loader-sensitive paths — loading a substitution matrix, reading saved Entrez or
BLAST XML, and importing `Bio.Entrez.Parser` — on a device or emulator/simulator rather than
on the desktop run that will always pass.

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
  `mode="fogsaa"` is also accepted. The `algorithm` attribute names whichever one it picked,
  which is worth printing next to any score you show a user.
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
- **Nothing here is a mobile fork.** Every `.py` and every data file in the wheel is
  byte-identical to the PyPI release of the same version, so
  [upstream's documentation](https://biopython.org/docs/latest/Tutorial/index.html) applies
  unchanged — except for the loader, external-binary and size questions this page is about.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version and a build number. The shipped C includes nothing but
`Python.h`, libc headers and biopython's own — no numpy headers, no third-party library — so
the sdist cross-compiles as-is with no `requirements`, no patch and no flag. That is the
recipe's whole shape, and a bump that needs more than a version change is a shape change
worth pausing over.

There is no native dependency chain either: the thirteen extension modules need nothing
beyond `libc`, `libdl`, `libm` and `libpython` on Android, and `Python.framework` plus
`libSystem` on iOS. `flet-libcpp-shared` does scroll past in an Android build — that is
numpy's dependency, not biopython's, and it is why the stack's Python floor is 3.11 rather
than biopython's own 3.10.

**The recipe declares no `extract_packages`, and its tests would not notice**: they exercise
two pure-Python paths that pass happily from `sitepackages.zip`, which is why CI is green
while `substitution_matrices.load()` is not. The `Bio` entry in [Install](#install) is
therefore something every consumer adds by hand today. Closing that gap means confirming the
failure on a device, then adding both an `extract_packages: [Bio]` key here and a test that
loads BLOSUM62 and parses a saved Entrez XML and a saved BLAST report. A recipe's own
`extract_packages` list is read only by the on-device test app and travels nowhere near a
consumer's build, so the README entry stays either way.

### Upgrade hazards

- **The consumer-facing claims are almost all about upstream's tree, not the build.** The
  five `subprocess` users, the six optional-dependency guards, the removed
  `Bio.Alphabet`/`Applications`/`SubsMat` surface, the three `__file__` sites and the five
  `Entrez.__path__[0]` reads — two in `Bio/Entrez/Parser.py`, three in `Bio/Blast/_parser.py`
  — are all re-derivable by grepping the extracted wheel, and a minor release can move any of
  them. Grep `__path__` as well as `__file__`: the `Bio/Blast` three are what make saved
  BLAST XML an `extract_packages` case, and they are easy to miss.
- **If upstream ever releases the GIL around the DP loop**, the advice to chunk work per pair
  becomes wrong rather than merely conservative, and the whole [Threading](#threading)
  section has to be rewritten rather than trimmed.
- **The absence of `Bio.Align._aligners`.** The current release splits the pairwise engine
  across `_pairwisealigner` and `_aligncore`; older code and older documentation name a
  module that does not exist here. If a bump reunifies them, the extension count moves.

### Re-verification checklist

- **The GIL claim**, which the whole Threading section rests on, has two independent checks
  that are cheap to repeat: zero
  `Py_BEGIN_ALLOW_THREADS`/`PyEval_SaveThread`/`Py_UNBLOCK_THREADS` across the seventeen
  shipped `.c`/`.h` files, and no GIL or `pthread` symbol in any compiled module's dynamic
  symbols on either platform.
- **Android `DT_NEEDED` and iOS file types:** re-read the Android wheel's entries after a
  bump — a new library there, `libc++_shared` above all, turns a zero-requirement recipe
  into a chained one. The iOS side should stay MH_DYLIB with only `Python.framework` and
  `libSystem`.
- **Wheel parity:** normalise the ABI tag in the extension filenames and the Android
  arm64-v8a and iOS device wheels list identical entries, including the same thirteen
  extension modules. Nothing in the tree gates on `sys.platform`, and the single
  `platform.system()` check only distinguishes Windows from everything else — recheck that,
  because it is what keeps the iOS `platform.system() == "iOS"` trap out of this page.
- **Sizes and the DTD share are measured**, decimal, from the built wheels, as is the leg
  matrix: three Python versions × three Android ABIs and three iOS slices, plus a 32-bit
  `android_24_x86` wheel on the 3.12 leg only. Re-measure rather than scaling, and re-count
  the legs — that asymmetry follows from Flet's Python builds, not from this recipe.
- **The timing table and the 6.2× `pairwise2` ratio are desktop numbers** on random DNA at
  5% divergence, quoted as shape rather than as a budget. They move with the machine, not
  with the recipe; the example app is what produces a device figure.

### Coverage gaps

The device tests cover `Seq` complement/reverse-complement and a FASTA round trip through a
string buffer. They do not exercise a substitution matrix, saved Entrez or BLAST XML,
`SeqIO.index_db`, or `Bio.Entrez.Parser`'s import side effect — precisely the surface the
consumer sections make claims about.

**None of the Android section has been confirmed on an Android device.** It was established
by reproducing Flet's Android shape on the host with a real `zipimport` — the pure-Python
tree in a `sitepackages.zip`, the extensions in a flat directory resolved by a `.soref`
meta-path finder — and running the [example app](examples/offline-seqlab) against it: four
panels pass and the BLOSUM50 panel prints the `NotADirectoryError`. The Entrez and BLAST
cases were read the same way, each against a control run from an ordinary directory that
parsed the same file fine. The `~` directory in
[Entrez cache directory](#entrez-cache-directory) is a host simulation too
(`sys.modules["pwd"] = None`, `HOME` removed), so what `HOME` holds on either mobile runtime
remains unmeasured.
