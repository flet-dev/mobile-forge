# uuid-utils

[`uuid-utils`](https://github.com/aminalaee/uuid-utils) is a Rust reimplementation of Python's
[`uuid`](https://docs.python.org/3/library/uuid.html) module, built on the
[`uuid`](https://docs.rs/uuid/) crate. It generates seven versions — `uuid1`, `uuid3`, `uuid4`
and `uuid5` from RFC 4122, plus the three
[RFC 9562](https://www.rfc-editor.org/rfc/rfc9562) additions `uuid6`, `uuid7` and `uuid8`.

**The one people actually want is `uuid7`.** A v7 id is a 48-bit Unix-millisecond timestamp
followed by 80 bits of version, variant and randomness, so a list of them is already sorted by
creation time before you sort it, and the instant an id was made can be read straight out of
it. That is what makes it a usable primary key on a device: consecutive inserts write
consecutive keys, "everything between these two instants" is a comparison on the key column
rather than a second column plus a second index, and the id is still globally unique with no
coordination. `uuid4` gives up all three for 122 random bits.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "uuid-utils",
]
```

The entry belongs in top-level `[project] dependencies` rather than in a `[tool.flet.android]`
or `[tool.flet.ios]` table. `flet build` resolves for the build host first, and PyPI carries a
desktop wheel for every host you would build from.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`id-generator`](examples/id-generator) — four UUID versions measured as database keys on the
  device: cost against the standard library, whether a batch comes out sorted, the instant each
  id carries, and a range scan done on key text alone.

## Usage in a Flet app

Generate an id, then keep its text — that is what goes into an
[`ft.Text`](https://flet.dev/docs/controls/text/), a key column or a file name:

```python
import uuid_utils

row_id = uuid_utils.uuid7()
label = ft.Text(str(row_id))
```

Anything downstream that type-checks its ids — `sqlite3`, `json`, a library annotated with
`uuid.UUID` — wants the standard library's class instead, and
[`uuid_utils.compat`](https://github.com/aminalaee/uuid-utils#compatibility-with-python-uuid)
returns exactly that:

```python
from uuid_utils import compat

row_id = compat.uuid7()  # a real uuid.UUID
cursor.execute("insert into rows (id) values (?)", (str(row_id),))
```

Pick one of those two representations and use it everywhere. Mixing them is the trap under
[Things to know](#things-to-know).

### Choosing a version

- **v7** for anything you store: sortable as generated, carries its own creation instant, and
  unique without coordinating with anything.
- **v4** when you specifically do *not* want a timestamp in the id — an opaque handle in a URL.
- **v3** and **v5** for an id derived from a namespace and a name, where the same input must
  produce the same id forever.
- **v1** and **v6** only when something else requires them. Both consult a node id, and neither
  is a dependable sort key.

On Flet's default Python this is a speed choice: CPython 3.14 brought `uuid6`, `uuid7` and
`uuid8` into the standard library. On 3.12 and 3.13 — both of which Flet still ships — it is a
capability one. Those interpreters have `uuid1`, `uuid3`, `uuid4` and `uuid5` and nothing else,
verified by introspecting all three, so this package is the only way to get a v7 at all.

### Cost per id

Nanoseconds per id on an Apple M4 desktop under CPython 3.14.6, best of twenty timing loops of
200,000 calls, with the ratio against the standard library on the same interpreter:

| | uuid-utils | `uuid_utils.compat` | stdlib `uuid` | ratio |
| --- | --- | --- | --- | --- |
| `uuid1` | 52 ns | 232 ns | 485 ns | 9× |
| `uuid3` | 190 ns | 524 ns | 715 ns | 4× |
| `uuid4` | 39 ns | 170 ns | 1,052 ns | **27×** |
| `uuid5` | 130 ns | 454 ns | 737 ns | 6× |
| `uuid6` | 55 ns | 269 ns | 659 ns | 12× |
| `uuid7` | 65 ns | 218 ns | 1,230 ns | **19×** |
| `uuid8` | 55 ns | 236 ns | 353 ns | 6× |

The `compat` column is the same work returning real `uuid.UUID` objects instead of the
package's own class. It still beats the standard library everywhere — by 6.2× on v4 and 5.6× on
v7, down to 1.4× on v3 — because the wrapper builds a `uuid.UUID` by hand and pays for it. v3
and v5 are the narrow wins in either column: those are MD5 and SHA-1, and `hashlib` is already
C.

The ratios are wider on mobile, where the interpreter around the call is slower. Measured on an
arm64-v8a Android 14 emulator and an iPhone 16 simulator, both CPython 3.14.6: a v4 costs 43 ns
against the stdlib's 1,941 ns on iOS (45×), and 248 ns against 5,416 ns on Android (22×).

The widest gap is not generation at all. Asking the **standard library** for a node id took
**1,021 ms on Android against 22 ms on iOS**, because Flet's Android runtime ships no `_uuid`
extension and the pure-Python fallback shells out to find one. `uuid_utils.getnode()` answered
in 6 ms and under 1 ms respectively. Only v1 and v6 consult it, so most apps never pay either
figure.

### Threading

**Every call holds the GIL, and none of them holds it for long.** Measured with a counter
thread running beside the work and its tick count taken as a percentage of an idle baseline:
loops of `uuid_utils.uuid7` and `uuid_utils.uuid4` scored 52% and 50%, next to 105% for
`zlib.decompress`, which does release the GIL, and 50% for `math.factorial`, which does not.

**Do not settle this from the symbol table, which answers the other way.** `PyEval_SaveThread`,
`PyGILState_Ensure` and their partners are undefined symbols on every published slice, because
PyO3's runtime imports them whether or not a binding uses them. The grep that decides this for
a Cython or cffi extension proves nothing about a Rust one.

It costs nothing in practice. At 39–190 ns a call there is no id generation worth moving into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — a thread
is worth it for the database write or the HTTP request around the id, and the id rides along.
If you do generate inside a worker anyway, the usual two Flet rules apply and the
[example](examples/id-generator) shows both: end the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and wrap its body in `try`/`except`, because `run_thread`
never retrieves the worker's future and discards whatever it raised.

**Generating from several threads at once is safe, and each thread's own sequence stays
ordered.** Eight threads × 20,000 `uuid7` calls produced 160,000 distinct ids with every
thread's own sequence strictly increasing, and four threads × 50,000 gave the same result.
There is no shared Python-level object to protect, and the shared state inside the Rust is
guarded: the cached node id and the v1/v6 clock sequence are atomics, and the v7 counter sits
behind a process-global mutex.

### App size

Approximately 270–285 KB compressed and 590–745 KB unpacked per architecture, of which about
90% is the single extension. There is no data directory or test suite worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

Every architecture is built, so on Android use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI — though at this size the saving is unlikely to be what
decides it. These figures describe the package payload, not the exact amount added to the final
APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, and two things around the package behave
differently once the app is on a device.

**The standard library's optional `_uuid` extension is present on desktop and on iOS and absent
on Android.** Without it, `uuid.uuid1()` computes its timestamp in Python and `uuid.getnode()`
falls through to shelling out to `ip` and then `ifconfig` — that is the 1,021 ms above.
`import uuid` still works either way, and uuid-utils is unaffected by the difference: it is
Rust, needs no C helper, and imports the stdlib module only for `SafeUUID`.

**`getnode()` finds a different kind of node on each platform.** On a desktop it reads a real
MAC address. On iOS it cannot — the recipe drops the MAC lookup there, and the sandbox blocks
reading a hardware address regardless — so it returns a random multicast node generated once
per process, which means **a v1 or v6 id made on iOS carries a node that changes every app
launch**. On Android the lookup is compiled in, but modern Android restricts hardware addresses
to apps, so it may return either; the [example](examples/id-generator) prints the node it got
and labels it `MAC` or `random` from the multicast bit. If anything in your data keys off the
node half of a v1 or v6 id, verify it on a device rather than under `flet run`.

Otherwise an id is computed from the clock, the OS random source and the generator's own state:
no file is read and no connection is opened. `getnode()` is the one exception, and even that
enumerates local network interfaces in-process rather than making a network call.

## Things to know

- **`uuid_utils.UUID` and `uuid.UUID` compare unequal while hashing equal.** This is the trap
  most likely to cost you an afternoon, and it measures identically on both platforms. Build
  both classes from the same string and `a == b` is `False` in both directions,
  `hash(a) == hash(b)` is `True`, `{a: …, b: …}` is a dict of length **two** whose keys print
  identically, `{a, b}` is a set of two, and `sorted([a, b])` raises `TypeError: '<' not
  supported between instances of 'UUID' and 'uuid_utils.UUID'`. Neither side will ever concede:
  each class returns `NotImplemented` for anything that is not one of its own, while both hash
  the integer modulo the same constant — including on `armeabi-v7a`, where that constant is
  `2**31 - 1` rather than `2**61 - 1` and the two still agree. Pick one representation per
  codebase: store `str(id)` and compare text, or use `uuid_utils.compat`.
- **`sqlite3` and `json` reject the class outright**, which is the good version of the same
  problem. Binding one as a parameter raises `sqlite3.ProgrammingError: Error binding parameter
  1: type 'uuid_utils.UUID' is not supported` and `json.dumps` raises `TypeError` — both loud,
  both fixed by `str(id)`. `pickle` and `copy.deepcopy` round-trip it correctly.
- **v7 is ordered under load; v6 and v1 are not.** One thread, ids compared as text: 1,000,000
  consecutive `uuid_utils.uuid7` calls produced **zero** out-of-order adjacent pairs and
  1,000,000 distinct ids, at up to 7,151 in a single millisecond. One stray inversion did turn
  up once in a further twenty million ids and never recurred, so treat ordering as a property
  worth relying on rather than an invariant to assert on. Over 100,000 calls,
  `uuid_utils.uuid6` produced 4–7 inversions per run and `uuid_utils.uuid1` 3–7. Every inversion
  inspected was the same event: two ids sharing one 100-nanosecond tick, where the ordering
  falls to the 14-bit clock sequence, which had just wrapped from 16383 to 0. CPython 3.14's own
  `uuid.uuid6` shows none, because it bumps its timestamp forward rather than letting the
  sequence wrap — at 12× the cost. **If you want a sortable key from this package, take v7.**
- **v1 is not a sort key at all, however sorted a burst of it looks.** A v1 id writes the *low*
  32 bits of its 60-bit timestamp first, so its text order restarts every `2**32` ticks — 429.5
  seconds. Two ids 20 ms apart that straddle that boundary come out `fffe795f-…` and
  `0001869f-…`, and the later one sorts first; the [example](examples/id-generator) computes
  exactly that pair on the device. A short benchmark loop never crosses a boundary, which is
  precisely why the problem gets shipped. v6 is the same timestamp with its three words written
  most significant first, and that is the entire content of the v6 specification.
- **`uuid8` is a different function here than in the standard library.** `uuid_utils.uuid8`
  takes exactly 16 bytes and raises `ValueError: expected a sequence of length 16` for anything
  else; CPython 3.14's `uuid.uuid8(a=None, b=None, c=None)` takes three integers. Code moved
  from one to the other does not merely slow down, it fails to call.
- **`.time` means two different things, and both classes agree about it.** On a v7 id it is
  Unix milliseconds, straight out of the top 48 bits. On v1 and v6 it is 100-nanosecond ticks
  since 1582-10-15, which is `(one.time - 0x01b21dd213814000) // 10_000` milliseconds. Reading
  `.time` off a v4 id returns a number that means nothing, silently — CPython's own
  implementation carries a comment saying it deliberately neither warns nor raises.
- **A v4 id is not a secret and a v7 id is less of one.** v4 gives you 122 random bits from the
  platform CSPRNG, which is fine as an unguessable handle. v7 spends 48 of its 128 bits on a
  timestamp you are publishing whether you meant to or not, plus 6 on version and variant — an
  id in a URL tells its reader when the row was created, to the millisecond. That is usually a
  feature and occasionally a leak.
- **If every call raises `AttributeError`, you have the placeholder wheel.** PyPI carries a
  `uuid_utils-0.0.0-py3-none-any.whl` from the same author whose `__init__.py` is **zero
  bytes**. Being `py3-none-any` it matches every target, so whenever no real wheel fits — an
  interpreter or ABI this index does not build for — pip installs *that* one instead of
  failing, and `import uuid_utils` then succeeds with nothing behind it. Naming a version in the
  dependency turns it back into an error you see at build time: *Could not find a version that
  satisfies the requirement uuid-utils==… (from versions: 0.0.0)*. No target `flet build` asks
  for today lands there, so this is a symptom to recognise rather than something to pre-empt.
- **Answer the export-compliance question knowing what is in the binary.** uuid-utils does carry
  cryptographic code — MD5 and SHA-1 for v3/v5, and the ChaCha generator behind v4 and v7
  randomness — but nothing you could encrypt anything with: there is no transport encryption and
  no key exchange. `ITSAppUsesNonExemptEncryption` in `Info.plist` is where App Store Connect
  records your answer, and everything else in your app counts toward it too.

## Build notes (maintainers)

### Recipe shape

The recipe is a `meta.yaml` naming the package, a build number, the
`_PYTHON_SYSCONFIGDATA_NAME` line every Rust/PyO3 recipe here carries, and one patch. There is
no `build.sh`, no `requirements` and no `excluded_arches` — armeabi-v7a builds and ships like
the other two ABIs, which for a Rust crate is the part that usually does not come free, and the
patch is what buys it. The patch preamble owns the explanation of both of its halves; what
follows is only where a bump will break them.

### Upgrade hazards

- **The patch is tied to upstream's file shape.** It touches four places: `Cargo.toml`'s
  `[dependencies]` and its single `[target.'cfg(not(target_arch = "wasm32"))'.dependencies]`
  header, and in `src/lib.rs` the `AtomicU64` import plus two `#[cfg]` attributes. Upstream
  adding a second target-specific dependency table, or moving `_getnode`, breaks it. Before
  carrying it forward, check whether `mac_address` has grown an iOS backend and whether the
  crate still uses `AtomicU64`; both halves were still required at the version in `meta.yaml`.
- **The 3.12 Android slices name the extension `_uuid_utils.cpython-312.so`, without the
  platform triplet**, while 3.13 and 3.14 use the full `_uuid_utils.cpython-31X-<triplet>.so`.
  Both carry the `.cpython-*` tag serious_python's `jniLibs` relocation keys on, so both work,
  but the untripleted form means forge's foreign-arch drop cannot tell the three 3.12 Android
  slices apart by file name. Harmless so far — every slice's `e_machine` was checked and each is
  the right architecture — but it is the first thing to look at if a 3.12 Android wheel ever
  imports on one ABI and not another.
- **CPython moves under this page.** 3.14 made `uuid6`, `uuid7` and `uuid8` exist in the
  standard library at all; a release reimplementing them in C would change the ratio column more
  than a uuid-utils bump would.

### Re-verification checklist

- **That the GIL is still held across a generation call.** The binding imports
  `PyEval_SaveThread`/`PyGILState_Ensure` because PyO3 does, so the symbol table cannot answer
  it and only a counter-thread measurement can. A PyO3 bump can change the answer without
  changing a line of this package's own source.
- **The speed table and the ratios**, which are the reason a reader takes the dependency.
  Re-measure against the *same* interpreter, since the stdlib side moves too.
- **The v7 ordering claim**, which rests on the `uuid` crate's shared v7 context rather than on
  anything in this recipe. A crate bump that changed the counter width would leave the build
  green, the tests green and the page wrong. The 1,000,000-id loop is the check — run it several
  times before concluding anything, because a single inversion has been seen once.
- **The patch's two effects, read out of the published wheels rather than a build log.** Each
  wheel embeds a CycloneDX SBOM at `dist-info/sboms/uuid-utils.cyclonedx.json` listing every
  crate that went in: `portable-atomic` must be present on all eighteen slices, and
  `mac_address` on the nine Android ones and none of the nine iOS ones. The symbol tables must
  agree — `getifaddrs`/`freeifaddrs` twice on every Android slice and zero times on every iOS
  slice. The three armeabi-v7a slices are also the only ones importing `sched_yield`, which is
  consistent with (though not proof of) a spin-based 64-bit atomic fallback.
- **That `METADATA` still has zero `Requires-Dist` lines**, and that neither shipped `.py` file
  has acquired a `__file__` read, an `open`, or an `importlib.resources` call. Both are what let
  the Install section stay one snippet, with no companion wheel and no
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry.
- **The extension file names**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Match the `_uuid_utils.cpython-` prefix, not an exact suffix.
- **The linkage**, per slice: `DT_NEEDED` still three entries with no `libc++_shared`, 16 KB
  `PT_LOAD` alignment on all three Android ABIs, `MH_DYLIB` on all three iOS ones.
- **That a bare `uuid-utils` still resolves from this index on every target.** Check with `pip
  download --only-binary :all: --index-url https://pypi.org/simple --extra-index-url
  https://pypi.flet.dev/`, which is how serious_python invokes pip, across all eighteen platform
  × Python combinations — arm64-v8a, armeabi-v7a and x86_64 on Android, plus device,
  arm64-simulator and x86_64-simulator on iOS, each on 3.12, 3.13 and 3.14. All eighteen
  resolved to this index's wheel last time. Anything that fails to match silently gets PyPI's
  `0.0.0` `py3-none-any` wheel instead of an error.
- **Whether PyPI has started carrying mobile tags.** The release checked was 94 files — an sdist
  plus macOS, manylinux, musllinux, Windows and Emscripten binaries — with no Android and no iOS
  tag among them, which is why this recipe exists. The day that changes, it may stop being
  needed.
- **The sizes**, re-measured in decimal bytes from the resulting wheels rather than scaled from
  the figures above.

### Coverage gaps

`tests/test_uuid_utils.py` is three functions: a `uuid4` distinctness and version check, a
`uuid5` determinism check, and a `str`/parse round trip. They exercise only the two versions the
standard library already has, so nothing on device currently checks the reason to ship this
package. Additions worth making at the next touch, in rough order of value: **a v7 ordering
assertion** (a few thousand ids, sorted as text, compared against the generation order); a
`uuid7().time` sanity check against `time.time()`, which would catch a clock or epoch regression
in the Rust; a `getnode()` call asserting the value fits in 48 bits, the only test that would
exercise the patched `_getnode` on both platforms at once; and an assertion that
`uuid_utils.compat.uuid4()` is an instance of `uuid.UUID`, which pins the one interop guarantee
this page tells people to rely on. Until then the ordering, node and interop claims above rest
on the [example](examples/id-generator) and on desktop measurement.
