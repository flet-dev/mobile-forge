# uuid-utils

[`uuid-utils`](https://github.com/aminalaee/uuid-utils) is a Rust reimplementation of
Python's `uuid` module, built on the [`uuid`](https://docs.rs/uuid/) crate. It generates seven
versions — `uuid1`, `uuid3`, `uuid4` and `uuid5` from RFC 4122, plus the three
[RFC 9562](https://www.rfc-editor.org/rfc/rfc9562) additions `uuid6`, `uuid7` and `uuid8` —
and generates every one of them considerably faster than the standard library does.

**The one people actually want is `uuid7`.** A v7 id is a 48-bit Unix-millisecond timestamp
followed by 80 bits of version, variant and randomness, so a list of them is already sorted
by creation time before you sort it, and the instant an id was made can be read straight out
of it. That is what makes it a usable primary key: consecutive inserts write consecutive
keys, "everything between these two instants" is a comparison on the key column rather than a
second column plus a second index, and the id is still globally unique with no coordination.
`uuid4` gives up all three for 122 random bits.

Speed, on an Apple M4 desktop under CPython 3.14.6, best of twenty timing loops of 200,000
calls each — nanoseconds per id, and the ratio against the standard library on the same
interpreter:

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
package's own class, and the answer whenever something downstream type-checks its ids. It
still beats the standard library everywhere, by 6.2× on v4 and 5.6× on v7 down to 1.4× on v3
— the wrapper builds a `uuid.UUID` by hand and pays for it. See
[Things to know](#things-to-know), because the two classes are less interchangeable than they
look. v3 and v5 are the narrow wins in either column: those are MD5 and SHA-1, and `hashlib`
is already C.

**On CPython 3.14 the ratio column is the whole argument, and on 3.12 and 3.13 it is not.**
3.14 added `uuid6`, `uuid7` and `uuid8` to the standard library, so on Flet's default Python
this package is a speed choice rather than a capability one. On 3.12 and 3.13 — both of which
Flet still ships — the stdlib has `uuid1`, `uuid3`, `uuid4` and `uuid5` and nothing else,
verified by introspecting all three interpreters; there, this package is the only way to get
a v7 at all.

**It opens no file and makes no network call.** The Android arm64-v8a and iOS device
extensions leave no `open`, `fopen`, `stat`, `socket`, `connect` or `getenv` undefined, so
every identifier it hands you is computed from the clock, the OS random source and its own
state — nothing here needs storage permission, a data file beside the binary, or connectivity.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6 — and the example prints the platform split in its own header:
iOS says `stdlib _uuid present, uuid1() runs in C`, Android says `stdlib no _uuid, uuid1() runs
in Python`. The cost of that gap is not theoretical. Asking the **stdlib** for a node identifier
took **1,021.1 ms on Android against 22.2 ms on iOS**, because without `_uuid` it falls back to
a pure-Python path; `uuid_utils` answered in 6.1 ms and 0.0 ms respectively, since it is Rust and
needs no C extension from CPython.

Generation is faster everywhere and more so where the stdlib is slower: v4 costs 43 ns against
the stdlib's 1,941 on iOS (45×) and 248 ns against 5,416 on Android (22×). 20,000 ids came back
20,000 distinct on both.

**The interop result is the one that will bite you.** A `uuid_utils.UUID` and a `uuid.UUID`
holding the same text are **not equal but hash the same**, so a dict given both ends up with
**2 keys** — measured identically on both platforms. If you mix the two types, convert at the
boundary; `uuid_utils.compat.uuid7()` returns a real `uuid.UUID` and is the clean way across.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "uuid-utils",
]
```

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.android]` /
`[tool.flet.ios]` table: `flet build` resolves for the build host first, and PyPI has a
desktop wheel for every host you would build from. The 0.17.0 release is 94 files — an sdist
plus 93 binaries covering CPython 3.10 through 3.14 (free-threaded 3.14t included) and PyPy
3.11 on macOS (one wheel carrying `macosx_10_12_x86_64`, `macosx_11_0_arm64` and
`macosx_10_12_universal2` at once, plus a second tagged `x86_64` only), Linux (`manylinux`
across x86_64, aarch64, armv7l, ppc64le and i686, `musllinux_1_2` across the same set minus
ppc64le), Windows (`win32`, `win_amd64`, `win_arm64`) and two Emscripten wasm32 wheels —
with **no Android tag and no iOS tag among them**, which is why this recipe exists.

Nothing follows it in. `METADATA` in all eighteen mobile wheels contains **zero**
`Requires-Dist` lines, so no `flet-lib*` wheel and no transitive dependency arrives with it.
`Requires-Python` is `>=3.10`, below anything Flet ships.

A bare `uuid-utils` resolves from this index on every target. Checked with `pip download
--only-binary :all:` under pip 26.2.1, using `--index-url https://pypi.org/simple
--extra-index-url https://pypi.flet.dev/` — which is how serious_python invokes pip — for all
eighteen platform × Python combinations: arm64-v8a, armeabi-v7a and x86_64 on Android plus
device, arm64-simulator and x86_64-simulator on iOS, across 3.12, 3.13 and 3.14. All
eighteen came back with this index's wheel.

**Pin it anyway, because the failure mode when nothing matches is silent.** PyPI carries a
`uuid_utils-0.0.0-py3-none-any.whl` from the same author — five files, an `__about__.py`
saying `__version__ = '0.0.0'` and an `__init__.py` of **zero bytes**. Being `py3-none-any`
it matches every target, so whenever no real wheel fits, pip installs *that* instead of
failing: asking for a bare `uuid-utils` on `android_24_x86`/cp314, or on cp315, or on cp311
each fetched the 0.0.0 wheel in the check above. `import uuid_utils` then succeeds and every
call raises `AttributeError`. Naming a version turns it back into an error you see at build
time — `uuid-utils==0.17.0` on the same three targets fails with *Could not find a version
that satisfies the requirement uuid-utils==0.17.0 (from versions: 0.0.0)*. None of those
three targets is one `flet build` asks for today, so this is insurance rather than a live
bug; it costs one string.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every wheel is eleven entries — one extension, `uuid_utils/__init__.py`,
`uuid_utils/compat/__init__.py`, two `.pyi` stubs, an empty `py.typed`, and five `dist-info`
files — with no data file that any code reads. Neither shipped `.py` mentions `__file__`,
`open`, `importlib.resources`, `pkgutil` or `pkg_resources` (grepped across both, on every
slice; the two files are byte-identical on all eighteen). The extension carries a CPython ABI
tag on every slice, which is what serious_python's relocation of native modules into
`jniLibs` keys on.

Eighteen wheels at build number 1: Android arm64-v8a, armeabi-v7a and x86_64 plus iOS device,
arm64-simulator and x86_64-simulator, on each of Python 3.12, 3.13 and 3.14. No architecture
is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. The wheels are 268,168–284,477 bytes to download and 589,522–743,005
unpacked, of which the extension is 525,112–685,104 — 89–92% of every slice; see
[Things to know](#things-to-know) for what the rest of that is.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`id-generator`](examples/id-generator) — four UUID versions measured as database keys on
  the device: cost against the standard library, whether a batch comes out sorted, the
  instant each id carries, and a range scan done on key text alone.

## Threading

**Every call holds the GIL, and none of them holds it for long.** `src/lib.rs` in the 0.17.0
sdist contains no `allow_threads` and no `Python::detach` at any point, so no generator call
drops the interpreter. **Do not settle this from the symbol table, which answers the other way
here**: `PyEval_SaveThread`, `PyEval_RestoreThread`, `PyGILState_Ensure` and
`PyGILState_Release` are all undefined symbols on the published slices — checked on the cp314
Android arm64-v8a and iOS device wheels — because PyO3's runtime imports them whether or not a
binding uses them. The grep that decides this for a Cython or cffi extension proves nothing
about a Rust one; the measurement does. On desktop, with a pure-Python counter thread running
beside the work and its tick count given as a
percentage of an idle-baseline window: `zlib.decompress` of a 48 MB blob — a C extension that
*does* release the GIL — scored 105%, `math.factorial(6000)`, which holds it, scored 50%, and
loops of `uuid_utils.uuid7` and `uuid_utils.uuid4` scored 52% and 50%. Squarely in the holds
camp, and the zlib control is what shows the harness could have said otherwise.

That costs nothing in practice. At the desktop rates above — 39–190 ns a call — there is no
id generation worth moving into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — a
thread is worth it for the database write or the HTTP request around the id, and the id rides
along. If you do generate in a worker anyway, the usual two Flet rules apply and the
[example](examples/id-generator) shows both: end the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and wrap its body in `try`/`except`, because `run_thread`
never retrieves the worker's future and discards whatever it raised.

**Generating from several threads at once is safe, and each thread's own sequence stays
ordered.** Measured on desktop: eight threads × 20,000 `uuid7` calls gave 160,000 distinct
ids with every thread's own sequence strictly increasing, and four threads × 50,000 gave
200,000 distinct ids, same result. There is no shared Python-level object to protect — the
generators are module-level functions, and the shared state in the Rust is guarded three
ways: the cached node id is an atomic, the v1/v6 clock sequence is an atomic
(`ContextV1 { count: Atomic<u16> }`), and the v7 counter sits behind a process-global
`std::sync::Mutex<ContextV7>` — all three visible as symbols in the unstripped iOS slices.

## Android notes

- **The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all nine Android slices — not even
  `libm` — with no `SONAME`, no `RPATH`, no `RUNPATH` and no `libc++_shared`, so none of the
  usual Android C++ staging applies. Every `PT_LOAD` segment carries 16 KB alignment
  (`0x4000`), which Android 15 requires. arm64-v8a and x86_64 are `ELF64`; armeabi-v7a is a
  genuine `ELF32`/`ARM` build rather than a stub. Each slice exports exactly one symbol,
  `PyInit__uuid_utils`, and imports 134–151, of which 45–51 are outside CPython's API.
- **`uuid.uuid1()` and `uuid.getnode()` take their slow paths here, and uuid-utils does not
  care.** Flet's Android runtime ships **no `_uuid` extension at all**: verified against the
  `python-android-dart` tarballs of python-build release 20260730 for all three Pythons —
  `libpython3.12/3.13/3.14.so` define zero `PyInit__uuid`, and none of the 53–55 modules in
  `libpythonbundle.so` is `_uuid` (the pure-Python `stdlib/uuid.pyc` is there). The stdlib
  import is guarded by `try: import _uuid / except ImportError`, so `import uuid` still works
  — it just leaves `_generate_time_safe` as `None`, and `uuid.uuid1()` then computes the
  timestamp in Python. Measured on desktop by forcing that same state: 943 ns per call
  against 481 ns with the C helper. uuid-utils is Rust and imports the stdlib `uuid` module
  only for `SafeUUID`, so it is unaffected — confirmed on desktop by blocking `_uuid` at the
  import hook, after which `uuid_utils.uuid1()`, `uuid_utils.uuid7()` and
  `uuid_utils.compat` all still work. Its timestamps come from `clock_gettime`, which is an
  undefined symbol on every slice.
- **`uuid_utils.getnode()` reads network interfaces in-process.** `getifaddrs` and
  `freeifaddrs` are undefined symbols on all nine Android slices (versioned `@LIBC_N`, the
  API 24 bionic addition), because the recipe keeps the `mac_address` crate on Android; the
  wheel's own SBOM lists `mac_address 1.1.8` on all nine and on none of the iOS nine. The
  standard library has no such path here — `_unix_getnode` needs `_uuid`, so `uuid.getnode()`
  falls through to shelling out to `ip`, then `ifconfig` (that order: `platform.system()` is
  `Android`, which `uuid.py` folds into its Linux getter list), and reaches a random node only
  if neither answers.
  **Whether Android hands back a real MAC is not something this page can answer** — modern
  Android restricts hardware addresses to apps — so the [example](examples/id-generator)
  prints both node ids and labels each `MAC` or `random` from its multicast bit.
- **`getrandom` is a weak undefined symbol**, not a hard one, which is what lets an
  API 24 wheel run on a device whose bionic gained the wrapper only at API 28; `syscall` and
  `dlsym` are imported alongside it for the fallback. Randomness comes from there, seeding
  the `rand 0.10.1` / `chacha20` generator the `uuid` crate's `fast-rng` feature selects.

## iOS notes

- **The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
  filetype `DYLIB` (not `BUNDLE`) on all nine iOS slices, so the *Unsupported mach-o filetype
  (only MH_OBJECT and MH_DYLIB can be linked)* failure at app link time does not arise here.
  Besides each extension's own install name, `otool -L` lists exactly three dependencies on
  every slice: `@rpath/Python.framework/Python`, `/usr/lib/libiconv.2.dylib` and
  `/usr/lib/libSystem.B.dylib`. The three arm64-simulator slices are ad-hoc linker-signed;
  the other six are unsigned.
- **There is no MAC lookup on this platform, by construction.** The recipe drops the
  `mac_address` crate for iOS, and the wheels show it: `getifaddrs` appears **zero** times in
  the symbol table of all nine iOS slices against twice on every Android slice, and the SBOM
  shipped inside each wheel lists 30–31 crates on iOS against 36–37 on Android with
  `mac_address` absent from every iOS one. So `uuid_utils.getnode()` returns a random
  multicast node here, generated once per process and cached — meaning **a v1 or v6 id made
  on iOS carries a node that changes every app launch**. Only those two versions consult it;
  v4, v5 and v7 never do. Reading a hardware MAC is blocked by the iOS sandbox regardless, so
  nothing is lost that was ever available.
- **Randomness comes from `CCRandomGenerateBytes`**, an undefined symbol on all nine slices,
  where Android uses `getrandom`. Both are the platform CSPRNG; the `uuid` crate seeds the
  same generator from either.
- **`_uuid` *is* present on this platform**, as `_uuid.framework` plus a
  `lib-dynload/_uuid.fwork` marker in the `python-ios-dart` tarballs of all three Pythons —
  the opposite of Android. Its one imported libuuid symbol is `uuid_generate_time`, not
  `uuid_generate_time_safe`, so `uuid.uuid1()` runs in C and returns
  `is_safe = SafeUUID.unknown`. On 3.13 and 3.14 it does **not** make `uuid.getnode()` fast,
  and the same symbol says why: CPython's `configure.ac` only sets
  `HAVE_UUID_GENERATE_TIME_SAFE_STABLE_MAC` when `HAVE_UUID_GENERATE_TIME_SAFE` is defined, so
  `_uuid.has_stable_extractable_node` is 0 and `_unix_getnode` returns nothing — the same
  value a desktop macOS 3.14.6 reports. **3.12 behaves the other way**: that attribute did not
  exist before 3.13 (the string is absent from the shipped 3.12 `_uuid` binary and present in
  the other two) and 3.12's `_unix_getnode` is gated on `_generate_time_safe` alone, so there
  `uuid.getnode()` does take its node from the C helper. None of this reaches uuid-utils,
  which needs no C helper on either platform.
- **Know what is in the binary before you answer the export-compliance question.** uuid-utils
  does carry cryptographic code — just nothing you could encrypt anything with. MD5 and SHA-1
  for v3/v5 are there as named symbols in the unstripped iOS slices (`uuid::md5::hash`,
  `sha1_smol::Sha1::digest`), and the ChaCha12 generator behind v4/v7 randomness is inlined
  into `rand::rngs::thread::ReseedingCore`, which is also a named symbol. There is no
  transport encryption and no key exchange. `ITSAppUsesNonExemptEncryption` in `Info.plist` is
  where App Store Connect records your answer, and everything else in your app counts toward
  it too.

## Things to know

- **`uuid_utils.UUID` and `uuid.UUID` compare unequal while hashing equal.** This is the trap
  most likely to cost you an afternoon. Measured on desktop: build both classes from the same
  string and `a == b` is `False` in both directions, `hash(a) == hash(b)` is `True`,
  `{a: …, b: …}` is a dict of length **two** whose keys print identically, `{a, b}` is a set
  of two, and `sorted([a, b])` raises `TypeError: '<' not supported between instances of
  'UUID' and 'uuid_utils.UUID'`. The cause is visible in the source: `__richcmp__` is
  declared to take a `UUID` — the Rust one — so a stdlib instance fails extraction and PyO3
  returns `NotImplemented`, while the stdlib's own `__eq__` returns `NotImplemented` for
  anything that is not a `uuid.UUID`. The hashes match because both compute the integer
  modulo the same constant (`2**61 - 1` on 64-bit, `2**31 - 1` on 32-bit, matching CPython's
  own int hash — so this holds on `armeabi-v7a` too). Pick one representation per codebase.
  Either store `str(id)` and compare text, or use
  [`uuid_utils.compat`](https://github.com/aminalaee/uuid-utils#compatibility-with-python-uuid),
  whose functions return real `uuid.UUID` objects and still beat the stdlib by 1.4–6.2×.
- **`sqlite3` and `json` reject the class outright**, which is the good version of the same
  problem. Binding one as a parameter raises `sqlite3.ProgrammingError: Error binding
  parameter 1: type 'uuid_utils.UUID' is not supported` and `json.dumps` raises `TypeError` —
  both loud, both fixed by `str(id)`. `pickle` and `copy.deepcopy` round-trip it correctly.
- **v7 is monotonic under load; v6 and v1 are not.** Measured on desktop, one thread, ids
  compared as text: 1,000,000 consecutive `uuid_utils.uuid7` calls produced **zero**
  out-of-order adjacent pairs and 1,000,000 distinct ids, at up to 7,151 in a single
  millisecond. Over 100,000 calls, `uuid_utils.uuid6` produced 4–7 inversions per run and
  `uuid_utils.uuid1` 3–7. Every inversion inspected was the same event: two ids sharing one
  100-nanosecond tick, where the ordering falls to the 14-bit clock sequence, which had just
  wrapped from 16383 to 0. CPython 3.14's own `uuid.uuid6` showed none, because it bumps its
  timestamp forward rather than letting the sequence wrap — at 12× the cost. **If you want a
  sortable key from this package, take v7.**
- **v1 is not a sort key at all, however sorted a burst of it looks.** A v1 id writes the
  *low* 32 bits of its 60-bit timestamp first, so its text order restarts every `2**32` ticks
  — 429.5 seconds. Two ids 20 ms apart that straddle that boundary come out
  `fffe795f-…` and `0001869f-…`, and the later one sorts first; the
  [example](examples/id-generator) computes exactly that pair on the device. A short
  benchmark loop never crosses a boundary, which is precisely why the problem gets shipped.
  v6 is the same timestamp with the three words written most significant first, and it is the
  entire content of that specification.
- **`uuid8` is a different function here than in the standard library.** `uuid_utils.uuid8`
  takes exactly 16 bytes and raises `ValueError: expected a sequence of length 16` for
  anything else; CPython 3.14's `uuid.uuid8(a=None, b=None, c=None)` takes three integers.
  Code moved from one to the other does not merely slow down, it fails to call.
- **`.time` means two different things and both classes agree about it.** On a v7 id it is
  Unix milliseconds, straight out of the top 48 bits. On v1 and v6 it is 100-nanosecond ticks
  since 1582-10-15, which is `(one.time - 0x01b21dd213814000) // 10_000` milliseconds. Reading
  `.time` off a v4 id returns a number that means nothing, silently — CPython's own
  implementation carries a comment saying it deliberately neither warns nor raises.
- **The RNG is reseeded after `fork`, if the platform has one.** `__init__.py` calls
  `os.register_at_fork(after_in_child=reseed_rng)` when `hasattr(os, "fork")`, so a forked
  child cannot repeat the parent's v4 ids. Flet's Android `libpython` does import `fork` from
  bionic, so the hook is registered there; nothing in a Flet app forks, so this is
  bookkeeping rather than something to act on.
- **A v4 id is not a secret and a v7 id is less of one.** v4 gives you 122 random bits from
  the platform CSPRNG, which is fine as an unguessable handle. v7 spends 48 of its 128 bits
  on a timestamp you are publishing whether you meant to or not, plus 6 on version and
  variant — an id in a URL tells its reader when the row was created to the millisecond. That
  is usually a feature and occasionally a leak.
- **Size: 262–278 KB to download per slice, and 89–92% of every one is the extension.** The
  Python half is a 1,121-byte `__init__.py` and a 2,481-byte `compat/__init__.py`,
  byte-identical across all eighteen wheels. The two `.pyi` stubs and `py.typed` never reach
  the device — serious_python's junk list deletes `**.pyi` and `**.typed`, and `flet build`
  passes `--cleanup-packages` by default. What *does* reach it is the `dist-info` directory,
  including a 35,662–43,265-byte CycloneDX SBOM listing every Rust crate: no glob in that
  junk list matches `dist-info` (read from serious_python 4.5.1's `package_command.dart`, not
  from a built app). The nine Android slices are stripped; the nine iOS ones are not —
  `strip -x` takes the cp314 device slice from 685,104 bytes to 520,920, so roughly 164 KB of
  each iOS slice is symbol table. Code size itself is comparable: on the cp314 slices, 372,576
  bytes of `.text` on Android arm64-v8a against 343,820 of `__text` on the iOS device slice.
- **Python 3.14 narrows the case for this package but does not close it.** It brings
  `uuid6`, `uuid7` and `uuid8` into the standard library, so on Flet's default Python the
  argument is speed alone — 19× on v7 and 27× on v4 by the table at the top. On 3.12 and
  3.13 there is no stdlib v7 to fall back to.

## Build notes (maintainers)

The recipe is a `meta.yaml` naming the package, a build number, the `_PYTHON_SYSCONFIGDATA_NAME`
line every Rust/PyO3 recipe here carries, and one patch. There is no `build.sh`, no
`requirements`, no `excluded_arches` — armeabi-v7a builds and ships like the other two ABIs,
which for a Rust crate is the part that usually does not come free, and the patch is what buys
it.

**The patch's two effects are visible in the published wheels, so a bump can be checked
without reading a build log.** Each wheel embeds a CycloneDX SBOM at
`dist-info/sboms/uuid-utils.cyclonedx.json` listing every crate that went in:
`portable-atomic 1.13.1` is present on all eighteen, and `mac_address 1.1.8` on the nine
Android slices and none of the nine iOS ones. The symbol tables agree — `getifaddrs`/
`freeifaddrs` twice on every Android slice and zero times on every iOS slice — and
the three `armeabi-v7a` slices are the only ones of the eighteen importing `sched_yield`,
which is consistent with (though not proof of) a spin-based 64-bit atomic fallback. If a bump
silently loses either half, those three checks catch it before a device does.

One observation with no other home: **the 3.12 Android slices name the extension
`_uuid_utils.cpython-312.so`, without the platform triplet, while 3.13 and 3.14 use the full
`_uuid_utils.cpython-31X-<triplet>.so`.** Both carry the `.cpython-*` tag serious_python's
`jniLibs` relocation keys on, so both work, but the untripleted form means forge's
foreign-arch drop cannot tell the three 3.12 Android slices apart by file name. Currently
harmless — the `e_machine` of every slice was checked and each is the right architecture —
but it is the first thing to look at if a 3.12 Android wheel ever imports on one ABI and not
another.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **Whether the GIL is still held across a generation call.** The binding imports
  `PyEval_SaveThread`/`PyGILState_Ensure` because PyO3 does, so the symbol table cannot
  answer it and only a counter-thread measurement can. A PyO3 bump can change the answer
  without changing a line of this package's own source.

- **That the patch still applies to the shape upstream ships.** It touches four places:
  `Cargo.toml`'s `[dependencies]` and its single
  `[target.'cfg(not(target_arch = "wasm32"))'.dependencies]` header, and in `src/lib.rs` the
  `AtomicU64` import plus two `#[cfg]` attributes. Upstream adding a second target-specific
  dependency table, or moving `_getnode`, breaks it. Both halves are still needed as of 0.17.0
  — check whether `mac_address` has grown an iOS backend and whether the crate still uses
  `AtomicU64` before carrying the patch forward.
- **The speed table and the ratios in this page's opening**, which are the reason a reader
  takes the dependency. Re-measure against the *same* interpreter, since the stdlib side
  moves too: 3.14 made `uuid6`/`uuid7`/`uuid8` exist at all, and a future release
  reimplementing them in C would change the answer more than a uuid-utils bump would.
- **The v7 monotonicity claim in [Things to know](#things-to-know)**, which rests on the
  `uuid` crate's shared v7 context rather than on anything in this recipe. A crate bump that
  changed the counter width would leave the build green, the tests green, and the page wrong.
  The 1,000,000-id zero-inversion loop is the check — but run it more than once before
  concluding anything: a single stray inversion turned up once while documenting this and did
  not recur in a further twenty million ids.
- **That `METADATA` still has zero `Requires-Dist` lines**, and that neither shipped `.py`
  has acquired a `__file__` read. Either would falsify [Install](#install) without failing
  anything.
- **The extension file names**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Match the `_uuid_utils.cpython-` prefix, not an exact
  suffix.
- **The linkage**, per slice: `DT_NEEDED` still three entries with no `libc++_shared`, 16 KB
  `PT_LOAD` alignment on all three Android ABIs, `MH_DYLIB` on all three iOS ones.
- **Whether PyPI has started carrying mobile tags.** 0.17.0 is 94 files with no Android or
  iOS wheel among them, which is what makes a bare `uuid-utils` resolve from this index; the
  day that changes, this recipe may stop being needed — and until it does, the 0.0.0
  `py3-none-any` wheel described in [Install](#install) remains the thing a mismatched target
  silently falls back to.

`tests/test_uuid_utils.py` is three functions — a `uuid4` distinctness and version check, a
`uuid5` determinism check, and a `str`/parse round trip — all with docstrings and no version
assertion, in line with the repo's conventions. They exercise only the two versions the
standard library already has. Additions worth making at the next touch, in rough order of
value: **a v7 ordering assertion** (a few thousand ids, sorted as text, compared against the
generation order), since time-ordering is the reason to ship this package and nothing on
device currently checks it; a `uuid7().time` sanity check against `time.time()`, which would
catch a clock or epoch regression in the Rust; a `getnode()` call asserting the value fits in
48 bits, which is the only test that would exercise the patched `_getnode` on both platforms
at once; and an assertion that `uuid_utils.compat.uuid4()` is an instance of `uuid.UUID`,
which pins the one interop guarantee this page tells people to rely on.
