"""Measure what a bcrypt cost factor costs on this device, and where hashing belongs."""

import concurrent.futures
import os
import platform
import time

import bcrypt
import flet as ft

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

COSTS, CHECKS, BOUNDS = (2, 3, 3, 2, 3), (7, 2, 2), (5, 2, 2, 3)


def table_row(values, weights):
    """One row of a results table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def fastest(work, reps=2):
    """Best of `reps` calls of `work`, in milliseconds, plus its last result.

    Two runs rather than one because a single hash can be preempted, and the ratio
    column would then read 1.5x or 2.5x for a library that is in fact exactly 2.0x
    on average. Two only takes the edge off — a loaded machine still scatters the
    ratio — and it is the compromise the cost forces: a measurement already costs
    four hashes at the chosen cost, and at the top of the slider that is tens of
    seconds on a phone.
    """
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def verdict(ms):
    """Name what a per-attempt cost of `ms` feels like against the login budget."""
    if ms < 50:
        return "instant"
    if ms <= BUDGET_MS:
        return "fine"
    if ms <= BUDGET_MS * 2:
        return "noticeable"
    return "unusable"


def outcome(password, salt):
    """Hash `password` with `salt` and name the result rather than raising.

    Every failure mode of the 72-byte panel arrives here: `ValueError` for a
    password over the limit, `TypeError` for a `str` that was never encoded. An
    unhandled exception in a Flet handler makes the framework send
    SESSION_CRASHED, so the catch is what keeps a long paste from being a crash
    screen instead of a message.
    """
    try:
        bcrypt.hashpw(password, salt)
    except Exception as error:
        return type(error).__name__
    return "ok"


def build_line(page):
    """Name the version, the library's own default cost, and how it got loaded.

    The default cost is read out of the library — `gensalt()` records it in bytes
    4 and 5 of the salt — rather than typed in, so the number every tutorial
    copies is on screen as a fact. `_bcrypt.__file__` is last because it is the
    one field that cannot be predicted from the wheel: Flet relocates native
    extensions on both platforms, so this reports whatever the import system
    resolved, under a name that appears in no wheel. Both lookups are guarded for
    that same reason — a header line is not worth crashing the app over.
    """
    origin = getattr(getattr(bcrypt, "_bcrypt", None), "__file__", None)
    return (
        f"bcrypt {bcrypt.__version__} · library default cost "
        f"{int(bcrypt.gensalt()[4:6])} · Python {platform.python_version()} · "
        f"{page.platform.value} · {os.cpu_count()} cores · _bcrypt "
        f"{os.path.basename(origin) if origin else 'none'}"
    )


def main(page: ft.Page):
    """Answer "what cost factor can this phone afford" by measuring it.

    Each slider release times one hash and one verification at that cost and adds
    a row. The ratio to the cost below gauges how much to trust the row: bcrypt
    doubles its work per step, so the column centres on 2.00x and a contended or
    mis-timed run shows up as a bad ratio instead of passing as a plausible number.
    It is a noise gauge and not a pass/fail check — any single reading scatters
    well past 2.00 under load, and only the trend across rows is stable. Three
    panels below settle the things a timing alone cannot: that the answers are
    right, that hashing belongs on a background thread, and what happens to a
    password over 72 bytes.
    """
    measured = {}

    def set_busy(busy):
        """Lock or release everything that can start a hash, and show the spinner."""
        cost.disabled = busy
        threads_button.disabled = busy
        as_typed_button.disabled = busy
        truncated_button.disabled = busy
        spinner.visible = busy

    def show_cost():
        """Report which cost the next run will measure, as the slider moves."""
        caption.value = (
            f"cost {int(cost.value)} — release to measure · "
            f"gensalt accepts up to {GENSALT_MAX}, which this slider will not reach"
        )

    def start():
        """Hand one measurement to a background thread and lock the controls.

        Driven by the slider's on_change_end, which fires once on release: a run
        per pixel of the drag would queue minutes of hashing. The guard is tested
        and set here rather than inside `run` because this body is synchronous,
        where `run_thread` only schedules — a `disabled` set inside the worker
        would not have happened yet when this handler returns and Flet pushes the
        control states, so a second release would be accepted.
        """
        if cost.disabled:
            return
        set_busy(True)
        page.update()
        page.run_thread(run)

    def run():
        """Time hashpw and checkpw at the chosen cost, then refill the table.

        The extension releases the GIL around the hash, so this thread genuinely
        leaves the UI thread running at full speed rather than merely returning
        early. The try/except is load-bearing anyway: `page.run_thread` discards
        whatever a worker raises, so a mistake in here would look like a screen
        that quietly stopped updating.
        """
        try:
            chosen = int(cost.value)
            salt = bcrypt.gensalt(chosen)
            hash_ms, stored = fastest(lambda: bcrypt.hashpw(PASSWORD, salt))
            check_ms, matched = fastest(lambda: bcrypt.checkpw(PASSWORD, stored))
            # Rounded on the way in, not on the way out, so the ratio column is
            # exactly the two numbers beside it divided rather than nearly them.
            measured[chosen] = (round(hash_ms, 1), round(check_ms, 1), matched)
            fill_costs()
        except Exception as error:
            prediction.value = f"{type(error).__name__}: {error}"
        set_busy(False)
        page.update()  # auto-update does not reach background threads

    def fill_costs():
        """Rebuild the cost table, with each row's measured ratio to the one below."""
        rows = [
            table_row(
                ("cost", "hashpw ms", "checkpw ms", "x cost-1", "verdict"), COSTS
            ),
            ft.Divider(height=1),
        ]
        for chosen in sorted(measured):
            hash_ms, check_ms, matched = measured[chosen]
            below = measured.get(chosen - 1)
            ratio = f"{hash_ms / below[0]:.2f}x" if below else "—"
            rows.append(
                table_row(
                    (
                        str(chosen),
                        f"{hash_ms:.1f}",
                        f"{check_ms:.1f}",
                        ratio,
                        verdict(hash_ms) if matched else "VERIFY FAILED",
                    ),
                    COSTS,
                )
            )
        costs.controls = rows
        top = max(measured)
        worst = measured[top][0] * 2 ** (GENSALT_MAX - top) / 3.6e6
        prediction.value = (
            f"cost {top} measured {measured[top][0]} ms here, so cost {top + 1} "
            f"should land near {measured[top][0] * 2:.0f} ms and cost "
            f"{GENSALT_MAX} near {worst:.0f} hours · budget {BUDGET_MS} ms per "
            f"login attempt"
        )

    def check_correctness():
        """Cross-check verification three independent ways, at a nearly free cost.

        checkpw is the API; `hashpw(password, stored) == stored` is the manual
        equivalent, and it must agree — that is also the demonstration that the
        salt is embedded in the hash. The fourth row is the mistake people
        actually make: a fresh salt cannot reproduce a stored hash. The fifth is
        upstream's own vector, which no amount of self-consistency would satisfy.
        """
        stored = bcrypt.hashpw(PASSWORD, bcrypt.gensalt(CHEAP_COST))
        checks = (
            (
                "bcrypt.checkpw(password, stored)",
                bcrypt.checkpw(PASSWORD, stored),
                True,
            ),
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
        correctness.controls = [
            table_row(("check", "got", ""), CHECKS),
            ft.Divider(height=1),
            *(
                table_row((what, str(got), "ok" if got is want else "WRONG"), CHECKS)
                for what, got, want in checks
            ),
        ]
        stored_text.value = (
            f"stored hash is {len(stored)} ASCII bytes, of which the first 29 are the "
            f"salt: {stored[:29].decode('ascii')} · cost "
            f"{int(stored[4:6])} read back out of it"
        )

    def measure_threads():
        """Hand the concurrency measurement to a background thread."""
        if threads_button.disabled:
            return
        set_busy(True)
        page.update()
        page.run_thread(threads_worker)

    def threads_worker():
        """Run four hashes one after another, then four at once, and compare.

        The pool is built here rather than reusing `page.run_thread` because
        `run_thread` returns nothing to wait on — it schedules onto the page's own
        `ThreadPoolExecutor` and drops the future. This is the same kind of pool,
        joined so the two wall times mean something. A speedup well above 1.0 is
        the device-side proof that the extension drops the GIL for the whole hash,
        and therefore that simultaneous logins do not serialise.
        """
        try:
            salts = [bcrypt.gensalt(THREAD_COST) for _ in range(THREAD_COUNT)]
            started = time.perf_counter()
            for salt in salts:
                bcrypt.hashpw(PASSWORD, salt)
            serial = round((time.perf_counter() - started) * 1000.0, 1)
            with concurrent.futures.ThreadPoolExecutor(THREAD_COUNT) as pool:
                started = time.perf_counter()
                list(pool.map(lambda salt: bcrypt.hashpw(PASSWORD, salt), salts))
                parallel = round((time.perf_counter() - started) * 1000.0, 1)
            threads_text.value = (
                f"{THREAD_COUNT} hashes at cost {THREAD_COST}: "
                f"{serial} ms one after another, {parallel} ms across "
                f"{THREAD_COUNT} threads — {serial / parallel:.2f}x on "
                f"{os.cpu_count()} cores"
            )
        except Exception as error:
            threads_text.value = f"{type(error).__name__}: {error}"
        set_busy(False)
        page.update()

    def check_boundary():
        """Walk the 72-byte limit in characters and in bytes.

        The last row passes the `str` straight in without encoding it, which is
        the mistake every call site risks once a `TextField` is involved.
        """
        salt = bcrypt.gensalt(CHEAP_COST)
        boundary.controls = [
            table_row(("password", "chars", "bytes", "hashpw"), BOUNDS),
            ft.Divider(height=1),
            *(
                table_row(
                    (
                        f"{text[0]!r} x {len(text)}",
                        str(len(text)),
                        str(len(text.encode())),
                        outcome(text.encode(), salt),
                    ),
                    BOUNDS,
                )
                for text in BOUNDARY
            ),
            table_row(
                (
                    "the same str, not encoded",
                    str(len(BOUNDARY[0])),
                    "—",
                    outcome(BOUNDARY[0], salt),
                ),
                BOUNDS,
            ),
        ]

    def report_long(truncate):
        """Hash the field's contents, optionally cut to 72 bytes first, and report.

        Truncating is what bcrypt 4.x did silently: two long passwords differing
        only after byte 72 shared a hash and verified against each other. 5.0.0
        refuses instead, so the choice is now the app's to make explicitly — and
        it is the only way a hash stored under 4.x for a long password stays
        verifiable.
        """
        raw = editor.value.encode("utf-8")
        password = raw[:72] if truncate else raw
        try:
            stored = bcrypt.hashpw(password, bcrypt.gensalt(CHEAP_COST))
            long_text.value = (
                f"{len(raw)} bytes in, {len(password)} hashed → "
                f"{stored[:32].decode('ascii')}… · checkpw "
                f"{bcrypt.checkpw(password, stored)}"
            )
        except Exception as error:
            long_text.value = f"{len(raw)} bytes → {type(error).__name__}: {error}"

    def hash_as_typed():
        """Hash the field unchanged, so a long passphrase shows its exact failure."""
        report_long(False)

    def hash_truncated():
        """Hash the field's first 72 bytes, which succeeds where the full one cannot."""
        report_long(True)

    page.appbar = ft.AppBar(title=ft.Text("bcrypt cost factor"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(build_line(page), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    cost := ft.Slider(
                        min=MIN_COST,
                        max=MAX_COST,
                        value=MIN_COST + 2,
                        divisions=MAX_COST - MIN_COST,
                        round=0,
                        label="{value}",
                        on_change=show_cost,
                        on_change_end=start,
                    ),
                    costs := ft.Column(spacing=4),
                    prediction := ft.Text(size=11),
                    ft.Divider(),
                    correctness := ft.Column(spacing=4),
                    stored_text := ft.Text(size=11),
                    ft.Divider(),
                    threads_button := ft.Button(
                        f"Time {THREAD_COUNT} hashes serially against "
                        f"{THREAD_COUNT} threads",
                        on_click=measure_threads,
                    ),
                    threads_text := ft.Text(size=11),
                    ft.Divider(),
                    boundary := ft.Column(spacing=4),
                    editor := ft.TextField(
                        value=LONG_PASSPHRASE,
                        multiline=True,
                        min_lines=2,
                        max_lines=4,
                        text_size=12,
                        label="a password over 72 bytes",
                    ),
                    ft.Row(
                        wrap=True,
                        controls=[
                            as_typed_button := ft.Button(
                                "Hash as typed", on_click=hash_as_typed
                            ),
                            truncated_button := ft.Button(
                                "Truncate to 72 bytes", on_click=hash_truncated
                            ),
                        ],
                    ),
                    long_text := ft.Text(size=11),
                ],
            ),
        )
    )

    show_cost()
    check_correctness()
    check_boundary()
    report_long(False)
    start()


if __name__ == "__main__":
    ft.run(main)
