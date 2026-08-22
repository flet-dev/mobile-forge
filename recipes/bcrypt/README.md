# bcrypt

[`bcrypt`](https://github.com/pyca/bcrypt) is the password hashing function whose whole design
goal is to be *slow*: a tunable cost factor makes each hash deliberately expensive, so guessing
passwords stays expensive too. The API is four functions —
[`gensalt`](https://github.com/pyca/bcrypt#adjustable-work-factor),
[`hashpw`](https://github.com/pyca/bcrypt#password-hashing),
[`checkpw`](https://github.com/pyca/bcrypt#password-hashing) and
[`kdf`](https://github.com/pyca/bcrypt#kdf) — and nothing else. On a phone you want it for a
local unlock code, for credentials an app verifies offline, or to produce and check hashes a
server shares with you; the 60-byte output is portable in both directions.

**The cost factor is the one number bcrypt asks you to choose, the work doubles for every step
you add, and the right value depends on the slowest device you ship to** — so measure it rather
than copying a tutorial written on a workstation. The
[`cost-factor-explorer`](examples/cost-factor-explorer) example exists to measure it. Two other
things shape the code around it: the extension **releases the GIL for the whole hash**, so a
background thread buys real parallelism rather than an early return, and **5.0.0 stopped silently
truncating passwords at 72 bytes and raises instead**, which invalidates most of what is written
about bcrypt online and can crash a Flet session outright.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "bcrypt",
]
```

A bare `bcrypt` always resolves from this index: upstream publishes no Android or iOS wheel for
this version, so every mobile target lands on the wheel this recipe builds.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`cost-factor-explorer`](examples/cost-factor-explorer) — measures milliseconds per cost
  factor on the device it runs on.

## Usage in a Flet app

Three calls do the whole job, and the result is 60 ASCII bytes you store:

```python
salt = bcrypt.gensalt(12)                                    # 12 is the library default
stored = bcrypt.hashpw(field.value.encode("utf-8"), salt)    # b'$2b$12$...', 60 bytes
ok = bcrypt.checkpw(attempt.encode("utf-8"), stored)
```

Both boundaries in that snippet bite. A [`TextField`](https://flet.dev/docs/controls/textfield/)
hands you a `str` and bcrypt takes only `bytes`; anything over 72 bytes raises, and so does a
corrupt stored hash. Encode at the UI edge and catch `ValueError` around both calls — an
unhandled exception in a Flet handler makes Flet send `SESSION_CRASHED`, a crash screen rather
than a failed login:

```python
def on_unlock(e):
    try:
        ok = bcrypt.checkpw(field.value.encode("utf-8"), stored)
    except ValueError:
        status.value = "At most 72 bytes, and check the saved credential."
    else:
        status.value = "unlocked" if ok else "wrong code"
```

### Storage

The hash is built to be stored: always 60 ASCII bytes, of which the first 29 are the salt string
`$2b$<cost>$<22 base64 chars>`. `checkpw` re-derives the cost from the hash it is given, so
hashes written at an old cost keep verifying after you raise your default, with no migration.
Being ASCII, a hash round-trips through `.decode("ascii")` into any text column, key-value store
or file; encode it back before `checkpw`. A single value such as a local unlock hash fits
[`page.shared_preferences`](https://flet.dev/docs/controls/page/#flet.Page.shared_preferences),
whose methods are coroutines:

```python
encoded = stored.decode("ascii")

await page.shared_preferences.set("unlock", encoded)            # in an async handler
page.run_task(page.shared_preferences.set, "unlock", encoded)   # from a worker thread
```

Call it bare from a handler that is not `async` and you get a coroutine nobody runs: nothing
stored, nothing raised, nothing to see.
[`page.run_task`](https://flet.dev/docs/controls/page/#flet.Page.run_task) is the way in from a
worker thread. A hash belonging to a file or database the app owns goes in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
not
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
which the platform may clear. bcrypt opens no file of its own and no sockets at all, so where the
hash lives is entirely your decision. Never store the password.

### Threading

**The extension drops the GIL around the whole hash, so hashing in a background thread is real
parallelism and the UI thread is not starved.** On desktop, four cost-11 hashes took 373 ms one
after another against 106 ms across four threads (3.52x) and eight took 775 ms against 128 ms
(6.05x), while a busy loop standing in for the UI thread counted 33,645 turns/ms idle against
33,109 during a cost-12 hash. So the shape is the ordinary Flet one, and it pays off rather than
merely tidying up:

```python
def on_unlock(e):
    attempt = field.value.encode("utf-8")   # a TextField hands you str
    button.disabled = True                  # guard here: run_thread only schedules
    spinner.visible = True
    page.run_thread(verify, attempt)

def verify(attempt):
    try:
        status.value = "unlocked" if bcrypt.checkpw(attempt, stored) else "wrong code"
    except ValueError:
        status.value = "That credential is unusable."
    button.disabled = False
    spinner.visible = False
    page.update()  # auto-update does not reach background threads
```

[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never retrieves the
worker's future, so an exception raised in there surfaces nowhere and a failed login just looks
like a screen that stopped updating; end the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) too, because auto-update
does not reach background threads. The re-entrancy guard belongs in the *handler*: `run_thread`
only schedules, so a `disabled` set inside the worker has not happened yet when Flet pushes the
control states.

There is no pool to size and no shared state to serialise: nothing in the wheel starts a thread of
its own, and every function is bytes in, bytes out with no handle to keep, so N simultaneous
verifications are N independent hashes and the ceiling is the device's core count. Those are
desktop numbers — the ratio transfers, the milliseconds do not.

### Choosing the cost factor

`gensalt` accepts 4 through 31 — 3 and 32 raise `ValueError: Invalid rounds` — and the library
default is 12. Measured on a desktop, best of three per cost:

| cost | 4 | 8 | 10 | 12 | 14 | 16 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| one hash | 0.76 ms | 11.97 ms | 46.86 ms | 187.68 ms | 741.75 ms | 2,994.51 ms |

The doubling is exact where it can be measured cleanly: the step ratio held 2.00 ± 0.01 across
costs 11 → 14 over three passes on an idle machine. **It is only the average that is stable, and
only on an idle machine** — the same sweep of costs 8 → 12 under load (load average 19 on ten
cores) kept a median of 1.97 over 32 readings but spread them from 1.52 to 2.56, more than half
outside 1.90–2.10. Contention moves a single reading far more than a small cost factor does, so
read one ratio as a noise gauge and the trend across rows as the measurement.

Extrapolated, cost 31 is 2^19 times cost 12 — around 27 hours on that machine, with no error, no
progress and no way to interrupt it. **A phone core is slower than any of these figures**, and no
device measurement backs this page: cap what a slider or config field can reach at a value you
measured on the slowest device you support, which is what the
[`cost-factor-explorer`](examples/cost-factor-explorer) example is for. Because the curve doubles
exactly, one measurement fixes the whole table — and because the cost travels inside the hash,
raising your default later costs stored data nothing.

### App size

The wheels span 229,658–273,979 B compressed, unpacking to 473,924–570,157 B — around a quarter
of a megabyte per slice, 95% of it the extension; everything else comes to the same
23,528–23,561 B on every slice. Flet's default
[cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) already removes
`bcrypt/__init__.pyi` and `bcrypt/py.typed`, leaving one compiled `__init__`, the `dist-info` and
the extension. An app bundle, split APKs and a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are still
the Android size levers, but at this payload they will be earning their keep on some other
dependency.

### Other considerations

**Every timing on this page is a desktop measurement.** A desktop core is several times a phone
core, and a phone throttles and migrates between big and little cores, so the cost curve, the
thread speedup and the budget you set from them all have to be re-taken on the slowest hardware
you ship to. The API, the hashes and the 72-byte behaviour are identical; only the milliseconds
move. A desktop `flet run` also uses PyPI's own wheel rather than this one — same source at the
same version, so results match, but not the binary that ships.

Flet relocates native extensions on both platforms: on Android each `*.cpython-*.so` moves into
`jniLibs` with a `.soref` marker left at the import path, and on iOS it becomes a framework with a
`<name>.fwork` pointer file that CPython's `AppleFrameworkLoader` reports as `__file__`. bcrypt
never reads its own `__file__`, so this costs it nothing — but code of yours that locates a data
file relative to a native module's `__file__` breaks on device. The example prints the value its
own import resolved.

## Things to know

- **bcrypt 5.0.0 no longer truncates at 72 bytes — it raises `ValueError`, from `checkpw` as well
  as `hashpw`.** Every pre-5.0 tutorial says the opposite, and the only place upstream records the
  change is its [changelog](https://github.com/pyca/bcrypt#changelog), under 5.0.0: *"Passing
  `hashpw` a password longer than 72 bytes now raises a `ValueError`. Previously the password was
  silently truncated"*. Its *Maximum Password Length* section was **not** updated, so checking
  against that section is wrong twice over: the truncation is gone, and the limit was never in
  characters. The check is the first statement in `hashpw`, before the salt is parsed, and
  `checkpw` is `hashpw` plus a compare — so a long passphrase pasted into a login field takes the
  session down rather than failing to log in. Measured: 71 and 72 bytes hash, 73 and 100 raise,
  and `checkpw(b"a" * 73, …)` raises before looking at the hash at all, giving the same error for
  an empty hash, a garbage one and a valid one. Catch `ValueError` around both calls and pick a
  policy explicitly. Three, all tested:

  | policy | what it costs |
  | --- | --- |
  | reject the input with a message | nothing, but you must say "bytes" — see the next bullet |
  | `password[:72]` | keeps 4.x behaviour, and is the *only* way pre-5.0 hashes stay verifiable |
  | `base64.b64encode(hashlib.sha256(password).digest())` | upstream's suggestion; 44 bytes, always in range, and unlike truncation two long passwords stay distinct — but it changes every hash you store, so it is a migration |

  That middle row is not optional with existing data: measured end to end, a hash written by
  bcrypt 4.2.0 for a 100-byte password raises `ValueError` on 5.0.0 against the full candidate and
  returns `True` when the candidate is cut to 72 bytes first.

- **The limit counts bytes, not characters, so a 37-character passphrase can be over it.**
  Measured: `"é".encode() * 36` is 72 bytes at 36 characters and hashes; `"é".encode() * 37` is 74
  bytes at 37 characters and raises. Validate `len(password.encode("utf-8")) <= 72`, never
  `len(password)` — and say "bytes" in the message, or a user counting characters will not
  understand a limit of 72 that rejects their 37.

- **Everything takes `bytes`, and only exactly `bytes`.** A `str` raises `TypeError: argument
  'password': 'str' object cannot be converted to 'PyBytes'`, and so do `bytearray` and
  `memoryview` — measured for `hashpw`'s password and salt, `checkpw`'s password and hash,
  `gensalt`'s prefix and `kdf`'s password; `gensalt(4.0)` raises on the rounds instead. Missing
  the encode at one call site is a crash, not a silent mismatch.

- **`checkpw` raises `ValueError("Invalid salt")` on a malformed stored hash instead of returning
  `False`.** An empty column, a truncated write, a cost byte out of range or a NUL inside the hash
  all raise; only a *well-formed* hash that does not match returns `False`. Measured: `b""`,
  `b"notahash"`, `b"$2b$"`, `b"$2b$12$short"`, a one-digit cost and a cost of 99 all raise, while
  dropping the hash's last byte, changing it or appending data all return `False`. Treat that
  branch as "this stored credential is corrupt", distinct from "wrong password".

- **Re-hashing and comparing does not work, and `==` on hashes leaks timing.** The salt lives
  inside the hash, so `hashpw(password, gensalt()) == stored` is `False` for the right password as
  much as the wrong one. Measured, the two that do work: `hashpw(password, stored) == stored` is
  `True` and `hashpw(b"wrong", stored) == stored` is `False`, because `hashpw` decodes only the
  first 22 base64 characters of the salt field and so accepts a whole 60-byte hash where a 29-byte
  salt goes. That is exactly how `checkpw` is implemented, plus the thing you lose by hand-rolling
  it: a constant-time compare.

- **Verifying costs the same as hashing; producing a salt costs nothing.** `checkpw` *is* `hashpw`
  plus that compare, so a login screen pays the full cost factor once per attempt whether the
  password is right or wrong — measured at cost 12: 185.7 ms to hash, 186.6 ms to verify
  correctly, 187.1 ms to reject. Moving a cost slider is free: the cost is recorded in the salt
  rather than spent producing it, and 1,000 `gensalt(12)` calls took 0.84 ms in total.

- **Hashes are portable to and from a server, in both directions.** Three of upstream's own test
  vectors verify against these wheels' code, two of them `$2a$` hashes. `hashpw` accepts `$2a$`,
  `$2b$`, `$2y$` and `$2x$` in the salt's version field — `$2c$` and `$2$` raise `ValueError:
  Invalid salt` — and the digest bytes are identical across `$2a$`, `$2b$` and `$2y$` for the same
  password and salt, only the version field differing. So a `$2y$` hash verifies, though that was
  checked against a `$2y$` hash produced here rather than one from another implementation.
  `gensalt` only ever *produces* `$2a$` or `$2b$` (`gensalt(4, b"2y")` raises `ValueError:
  Supported prefixes are b'2a' or b'2b'`).

- **NUL bytes are hashed rather than treated as a terminator, and that is not new in 5.0.0.**
  `hashpw(b"ab\x00cd", salt)` succeeds, `checkpw(b"ab", …)` is `False` and
  `checkpw(b"ab\x00cd", …)` is `True` — identical results from bcrypt 4.2.0 in a second
  environment, so do not file this with the 5.0.0 changes. A NUL *inside a stored hash* is one of
  the `Invalid salt` cases above, so it belongs in the corrupt-credential branch.

- **`kdf`'s `rounds` is linear, not logarithmic like `hashpw`'s cost, and the library warns you if
  you get that wrong.** Measured: 50 rounds 146.1 ms, 100 rounds 292.5 ms, 200 rounds 590.2 ms.
  Below 50 it emits `UserWarning: Warning: bcrypt.kdf() called with only N round(s). This few is
  not secure: the parameter is linear, like PBKDF2.`, silenced with `ignore_few_rounds=True`.
  Unlike `hashpw` it takes passwords longer than 72 bytes, it is deterministic for the same
  inputs, `desired_key_bytes` must be 1–512, and neither password nor salt may be empty.

- **bcrypt's own description tells you to prefer argon2id, and both alternatives reach a Flet
  app.** The first line of prose in upstream's README is *"Acceptable password hashing for your
  software and your servers (but you should really use argon2id or scrypt)"*.
  [`argon2-cffi`](https://argon2-cffi.readthedocs.io/) resolves for mobile on top of the
  [`argon2-cffi-bindings`](../argon2-cffi-bindings) recipe here, and
  [`hashlib.scrypt`](https://docs.python.org/3/library/hashlib.html#hashlib.scrypt) needs no
  dependency at all — the OpenSSL-backed function it wraps is compiled into Flet's mobile Python
  on both platforms, though nothing here has called it on a device. Reach for bcrypt when
  something else already chose it: an existing hash column, a server, or a format you have to
  interoperate with.

## Build notes (maintainers)

### Recipe shape

The build side is two files — a `meta.yaml` naming the version and one test — with no `patches/`
and no `build.sh`. bcrypt is a Rust/PyO3 extension built through setuptools-rust, and it
cross-compiles to every slice of all three Python minors on forge's stock support with one
environment variable and nothing else. The day it needs a patch, suspect the toolchain or an
upstream restructuring before reaching for one.

Nothing here relocates, preloads or repackages the extension, because nothing has to: it links
only CPython and the platform's own libraries on both sides, and arrives as the Mach-O file type
iOS packaging needs. The filename is not uniform across minors and does not need to be — cp312's
Android wheels ship `bcrypt/_bcrypt.cpython-312.so` with no platform triple while cp313 and cp314
carry one, and both match the `\.(cpython-[^/]+|abi3)\.so$` tag regex serious_python's Android
packaging uses, so both mangle to the same relocated name and `.soref` marker.

### Upgrade hazards

The **72-byte behaviour** is the load-bearing claim of this page, the example and half the
consumer advice on it; it has already changed once, and its error string is quoted verbatim in
both. A change there is a documentation pass, not a version bump.

`bcrypt.__version__` is re-exported from the extension's `__version_ex__` — deliberately not named
`__version__` in Rust, because passlib treats that attribute's presence as proof of a different
module. A rename there breaks the example's header line silently.

If upstream starts publishing Android or iOS wheels, **Install**'s resolution claim stops being
true and a consumer can silently land on a wheel this recipe did not build — along with the
question of whether the recipe is still needed. One `pip download --only-binary :all: --platform …
--extra-index-url https://pypi.flet.dev bcrypt` per target re-establishes it.

### Re-verification checklist

- **The 72-byte boundary:** 71 and 72 hash, 73 raises, `checkpw` raises too, and the error string
  still reads as quoted. Upstream parametrises `(71, False)`, `(72, False)`, `(73, True)`, so the
  behaviour is at least guarded there.
- **The API surface:** the non-underscore names in `dir(bcrypt)` still exactly `checkpw`,
  `gensalt`, `hashpw` and `kdf`, with the signatures `__init__.pyi` declares.
- **The GIL release**, which is the **Threading** section entirely — and it is the timing that
  checks it, not the symbols. Grep the sdist's `lib.rs` for `py.detach`, then measure: N threads
  measurably faster than N serial hashes (3.52x at four, 6.05x at eight, on desktop), each worker
  hashing a *different* password so a shared or dropped result cannot pass as a speedup.
  `PyEval_SaveThread`/`PyEval_RestoreThread` stay in the binary either way, so an extension that
  stopped detaching would rewrite that section without failing any grep.
- **The exact doubling**, on which every extrapolation here and in the example rests. Re-measure
  costs 8 through 16; below 8 the ratios are noisy because a single hash is under 10 ms and
  overhead dominates, which is why the example's slider starts at 8.
- **The extension's presence, per leg.** One `.so` per wheel, and no pure-Python fallback —
  `__init__.py` is bare imports with no `try`/`except` — so a wheel that lost it fails at
  `import bcrypt` rather than degrading quietly. Confirm the import on **every** leg, cp312 Android
  included, since the filename is the one axis on which the legs genuinely differ.
- **The linkage.** Android `DT_NEEDED` is `libpython3.<minor>`/`libdl`/`libc` with no `SONAME`,
  `RPATH` or `RUNPATH`, one exported symbol (`PyInit__bcrypt`) and 16 KB `PT_LOAD` alignment; iOS
  is `MH_DYLIB`/`NOUNDEFS` resolving only to `Python.framework` and `libSystem`, plus an unused
  `/usr/lib/libiconv.2.dylib` that rustc leaves behind and upstream's macOS wheel carries too.
  Anything new is a runtime dependency **Install** does not mention, and an `MH_BUNDLE` would fail
  at link time.
- **The randomness source**, per-platform and both times an OS CSPRNG: the `getrandom` syscall with
  a `/dev/urandom` fallback on Android, `_CCRandomGenerateBytes` on iOS. Salts are identical in
  format and cost either way.
- **The byte-identical Python payload and the crate versions**, which are what license quoting a
  desktop measurement as a claim about the mobile wheels at all. `__init__.py`, `__init__.pyi` and
  `py.typed` must still hash identical across the mobile wheels and upstream's desktop one
  (`__init__.py` at `72ff8dba…7ac0a4`), `METADATA` differ only in `Metadata-Version` and one
  `Dynamic:` line, and `strings -a` on both extensions name the crates the sdist's `Cargo.lock`
  pins for that same version (`bcrypt`, `bcrypt-pbkdf`, `blowfish`, `base64`, `pbkdf2`, `pyo3`).
- **The measurements.** The cost curve, the thread speedups, the `gensalt` and `kdf` timings and
  the per-slice sizes are all desktop figures. Re-measure; do not scale.

### Coverage gaps

**No on-device run backs any timing on this page.** Everything above was read off the wheels or
measured on a desktop install of the same version, and the number a consumer most wants —
milliseconds per cost factor on a phone — is missing by construction. An Android and an iOS run of
the [`cost-factor-explorer`](examples/cost-factor-explorer) example is the missing evidence, and
its header line is built to be read off the screen.

The device test covers verification only, and not the thing most likely to break:
`tests/test_bcrypt.py` is one function doing two cost-12 `checkpw` calls against a hardcoded hash,
and — against the repo's test convention — without a docstring. It never calls `gensalt`, `hashpw`
or `kdf`, never asserts the 72-byte `ValueError` that is the whole behavioural story of 5.0.0, and
spends about 400 ms doing it on a fast desktop. Worth adding, in rough order of value: the
71/72/73-byte boundary asserting `ValueError` at 73; a `gensalt` → `hashpw` → `checkpw` round trip
at cost 4 so the suite stops paying for 12; a `ValueError` assertion for a malformed stored hash;
and the GIL relationship, N threads against N serial hashes, which is the one claim here a device
could confirm cheaply.
