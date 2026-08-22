"""Every call into bcrypt the app makes: cost, correctness and the 72-byte limit.

Nothing here is read off a table — each figure is produced by calling bcrypt on
the device that is running it. The cost factor is the single decision bcrypt asks
a developer to make, its work doubles for every step up, and the answer is a
property of the hardware, so it has to be measured rather than copied.
"""

import concurrent.futures
import os
import platform
import time

import bcrypt

PASSWORD = b"correct horse battery staple"

# gensalt accepts 4..31, and nothing above the mid teens is usable on a phone: the
# work doubles per step, so cost 31 is 2**19 times a cost-12 hash. The slider stops
# well short of what the library allows, deliberately. The floor is 8 because below
# it one hash is under 10 ms and timing overhead swamps the doubling this checks for.
MIN_COST, MAX_COST, GENSALT_MAX = 8, 15, 31

# What a login is allowed to spend. The verdict column is read against this.
BUDGET_MS = 500

# The concurrency panel keeps its own cost so it does not scale with the slider.
THREAD_COST, THREAD_COUNT = 10, 4

# Cost 4 is the cheapest bcrypt allows, so the correctness and boundary panels cost
# nothing measurable and are safe to run on the UI thread at startup.
CHEAP_COST = 4

MAX_BYTES = 72

# From upstream's own test suite. Verifying it proves this device's bcrypt agrees
# with the reference implementation rather than merely with itself.
VECTOR_PASSWORD = b"Kk4DQuMMfZL9o"
VECTOR_HASH = b"$2b$04$cVWp4XaNU8a4v1uMRum2SO026BWLIoQMD/TXg5uZV.0P.uO8m3YEm"

# Exactly 100 bytes, so the field starts over the limit before anyone types.
LONG_PASSPHRASE = (
    "a passphrase long enough that a password manager would generate it "
    "and bcrypt will not hash it today"
)

# The limit counts bytes, so the accented pair is over it at half the characters.
BOUNDARY = ("a" * 72, "a" * 73, "é" * 36, "é" * 37)

COST_HEADER = ("cost", "hashpw ms", "checkpw ms", "x cost-1", "verdict")
CHECK_HEADER = ("check", "got", "")
BOUND_HEADER = ("password", "chars", "bytes", "hashpw")

THREAD_LABEL = f"Time {THREAD_COUNT} hashes serially against {THREAD_COUNT} threads"


def build_line(platform_name):
    """Name the version, the library's own default cost, and how the extension loaded.

    The default cost is read out of the library — `gensalt()` records it in bytes 4
    and 5 of the salt — rather than typed in, so the number every tutorial copies is
    on screen as a fact. `_bcrypt.__file__` is last because it is the one field that
    cannot be predicted from the wheel: Flet relocates native extensions on both
    platforms, so this reports whatever the import system resolved, under a name that
    appears in no wheel. Both lookups are guarded for that same reason — a header line
    is not worth crashing the app over.
    """
    origin = getattr(getattr(bcrypt, "_bcrypt", None), "__file__", None)
    return (
        f"bcrypt {bcrypt.__version__} · library default cost "
        f"{int(bcrypt.gensalt()[4:6])} · Python {platform.python_version()} · "
        f"{platform_name} · {os.cpu_count()} cores · _bcrypt "
        f"{os.path.basename(origin) if origin else 'none'}"
    )


def fastest(work, reps=2):
    """Best of `reps` calls of `work`, in milliseconds, plus its last result.

    Two runs rather than one because a single hash can be preempted, and the ratio
    column would then read 1.5x or 2.5x for a library that is in fact exactly 2.0x on
    average. Two only takes the edge off — a loaded machine still scatters the ratio —
    and it is the compromise the cost forces: a measurement already costs four hashes
    at the chosen cost, and at the top of the slider that is tens of seconds on a phone.
    """
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def measure(cost):
    """Time one hash and one verification at `cost`, and check the hash verifies.

    Rounded here rather than on the way to the screen, so the ratio between two rows
    is exactly the two numbers beside it divided rather than nearly them.
    """
    salt = bcrypt.gensalt(cost)
    hash_ms, stored = fastest(lambda: bcrypt.hashpw(PASSWORD, salt))
    check_ms, matched = fastest(lambda: bcrypt.checkpw(PASSWORD, stored))
    return round(hash_ms, 1), round(check_ms, 1), matched


def verdict(ms):
    """Name what a per-attempt cost of `ms` feels like against the login budget."""
    if ms < 50:
        return "instant"
    if ms <= BUDGET_MS:
        return "fine"
    if ms <= BUDGET_MS * 2:
        return "noticeable"
    return "unusable"


def cost_caption(cost):
    """Name the cost the next run will measure, and where the library's ceiling is."""
    return (
        f"cost {cost} — release to measure · gensalt accepts up to {GENSALT_MAX}, "
        "which this slider will not reach"
    )


def cost_rows(measured):
    """Header plus one row per measured cost, each with its ratio to the cost below.

    bcrypt doubles its work per step, so that ratio centres on 2.00x — read it as a
    gauge of how much to trust the row rather than as a pass/fail check. A single
    reading scatters well past 2.00 under load; only the trend across rows is stable.
    """
    rows = [COST_HEADER]
    for cost in sorted(measured):
        hash_ms, check_ms, matched = measured[cost]
        below = measured.get(cost - 1)
        rows.append(
            (
                str(cost),
                f"{hash_ms:.1f}",
                f"{check_ms:.1f}",
                f"{hash_ms / below[0]:.2f}x" if below else "—",
                verdict(hash_ms) if matched else "VERIFY FAILED",
            )
        )
    return rows


def cost_summary(measured):
    """Extrapolate the highest measured row to the next cost and to gensalt's maximum.

    The doubling is exact on average, so one believable row fixes the whole table,
    including the far end: cost 31 is 2**19 times a cost-12 hash, and it runs with no
    error, no progress and no way to interrupt it. A cost slider or config field wired
    to what the library accepts hangs the app.
    """
    top = max(measured)
    hash_ms = measured[top][0]
    hours = hash_ms * 2 ** (GENSALT_MAX - top) / 3.6e6
    return (
        f"cost {top} measured {hash_ms} ms here, so cost {top + 1} should land near "
        f"{hash_ms * 2:.0f} ms and cost {GENSALT_MAX} near {hours:.0f} hours · budget "
        f"{BUDGET_MS} ms per login attempt"
    )


def correctness_rows():
    """Cross-check verification three ways; return the table rows and a summary line.

    `checkpw` is the API; `hashpw(password, stored) == stored` is the manual equivalent
    and has to agree, which is also the demonstration that the salt is embedded in the
    hash. The fourth row is the mistake people actually make: a fresh salt cannot
    reproduce a stored hash. The fifth is upstream's own vector, which no amount of
    self-consistency would satisfy. Everything runs at cost 4, so it is nearly free.
    """
    stored = bcrypt.hashpw(PASSWORD, bcrypt.gensalt(CHEAP_COST))
    checks = (
        ("bcrypt.checkpw(password, stored)", bcrypt.checkpw(PASSWORD, stored), True),
        (
            "bcrypt.checkpw(one letter changed, stored)",
            bcrypt.checkpw(PASSWORD[:-1] + b"E", stored),
            False,
        ),
        (
            "hashpw(password, stored) == stored",
            bcrypt.hashpw(PASSWORD, stored) == stored,
            True,
        ),
        (
            "hashpw(password, gensalt()) == stored",
            bcrypt.hashpw(PASSWORD, bcrypt.gensalt(CHEAP_COST)) == stored,
            False,
        ),
        (
            "checkpw(upstream test vector)",
            bcrypt.checkpw(VECTOR_PASSWORD, VECTOR_HASH),
            True,
        ),
    )
    rows = [
        CHECK_HEADER,
        *(
            (what, str(got), "ok" if got is want else "WRONG")
            for what, got, want in checks
        ),
    ]
    summary = (
        f"stored hash is {len(stored)} ASCII bytes, of which the first 29 are the "
        f"salt: {stored[:29].decode('ascii')} · cost {int(stored[4:6])} read back "
        f"out of it"
    )
    return rows, summary


def outcome(password, salt):
    """Hash `password` with `salt` and name the result rather than raising.

    Every failure mode of the boundary table arrives here: `ValueError` for a password
    over the limit, `TypeError` for a `str` that was never encoded. An unhandled
    exception in a Flet handler makes the framework send SESSION_CRASHED, so the catch
    is what keeps a long paste from being a crash screen instead of a message.
    """
    try:
        bcrypt.hashpw(password, salt)
    except Exception as error:
        return type(error).__name__
    return "ok"


def boundary_rows():
    """Walk the 72-byte limit in characters and in bytes; return the table rows.

    The last row passes the `str` straight in without encoding it, which is the
    mistake every call site risks once a TextField is involved.
    """
    salt = bcrypt.gensalt(CHEAP_COST)
    rows = [BOUND_HEADER]
    for text in BOUNDARY:
        rows.append(
            (
                f"{text[0]!r} x {len(text)}",
                str(len(text)),
                str(len(text.encode())),
                outcome(text.encode(), salt),
            )
        )
    rows.append(
        (
            "the same str, not encoded",
            str(len(BOUNDARY[0])),
            "—",
            outcome(BOUNDARY[0], salt),
        )
    )
    return rows


def thread_report():
    """Run four hashes one after another, then four at once, and compare the wall times.

    The pool is built here rather than reusing `page.run_thread` because `run_thread`
    returns nothing to wait on — it schedules onto the page's own executor and drops
    the future. This is the same kind of pool, joined so the two wall times mean
    something. A speedup well above 1.0 is the device-side proof that the extension
    drops the GIL for the whole hash, and therefore that simultaneous logins do not
    serialise behind each other. The core count is the ceiling.
    """
    salts = [bcrypt.gensalt(THREAD_COST) for _ in range(THREAD_COUNT)]
    started = time.perf_counter()
    for salt in salts:
        bcrypt.hashpw(PASSWORD, salt)
    serial = (time.perf_counter() - started) * 1000.0
    with concurrent.futures.ThreadPoolExecutor(THREAD_COUNT) as pool:
        started = time.perf_counter()
        list(pool.map(lambda salt: bcrypt.hashpw(PASSWORD, salt), salts))
        parallel = (time.perf_counter() - started) * 1000.0
    return (
        f"{THREAD_COUNT} hashes at cost {THREAD_COST}: {serial:.1f} ms one after "
        f"another, {parallel:.1f} ms across {THREAD_COUNT} threads — "
        f"{serial / parallel:.2f}x on {os.cpu_count()} cores"
    )


def truncation_report(text, truncate):
    """Hash `text`, optionally cut to 72 bytes first, and describe what happened.

    Truncating is what bcrypt 4.x did silently: two long passwords differing only after
    byte 72 shared a hash and verified against each other. 5.0.0 refuses instead, so the
    choice is now the app's to make explicitly — and it is the only way a hash stored
    under 4.x for a long password stays verifiable.
    """
    raw = text.encode("utf-8")
    password = raw[:MAX_BYTES] if truncate else raw
    try:
        stored = bcrypt.hashpw(password, bcrypt.gensalt(CHEAP_COST))
    except Exception as error:
        return f"{len(raw)} bytes → {type(error).__name__}: {error}"
    return (
        f"{len(raw)} bytes in, {len(password)} hashed → "
        f"{stored[:32].decode('ascii')}… · checkpw {bcrypt.checkpw(password, stored)}"
    )
