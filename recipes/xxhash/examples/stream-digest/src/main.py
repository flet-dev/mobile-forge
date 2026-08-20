"""Hash the same bytes with xxhash and the stdlib here, then show what xxhash is not.

Four panels: throughput against `crc32`, `md5` and `sha256` at three sizes; the
streaming API checked against the one-shot digest and priced against it; xxHash's
own sanity vectors recomputed here; and two attacks a cryptographic hash survives.
"""

import hashlib
import platform
import random
import time
import zlib

import flet as ft

try:
    import xxhash
except Exception as error:  # the wheel may be missing or fail to load
    xxhash = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

# The two constants xxHash's own sanity check is built from (cli/xsum_sanity_check.c).
PRIME32 = 2654435761
PRIME64 = 11400714785074694797

MASK32 = 0xFFFFFFFF
MASK64 = 0xFFFFFFFFFFFFFFFF

# XXH32's mixing constants, and the modular inverses that undo the multiplications.
P2, P3, P4, P5 = 2246822519, 3266489917, 668265263, 374761393
INV2, INV3, INV4 = (pow(prime, -1, 1 << 32) for prime in (P2, P3, P4))

SMALL_SIZES = ((1024, "1 KiB"), (65536, "64 KiB"))

BIG_SIZES = {"1 MiB": 1 << 20, "4 MiB": 4 << 20, "16 MiB": 16 << 20}

ROW_WEIGHTS = (4, 3, 3, 3)

SEED = 20260820

CHUNK = 65536

REPEAT_BUDGET_MS = 60.0

REPEAT_ROUNDS = 4

MIN_BATCH_MS = 1.0

MAX_BATCH = 1 << 20

COLLISION_SEEDS = (0, 1, 2)

COLLISION_LIMIT = 400_000

COLLISION_LENGTH = 32

INVERSION_TRIALS = 2000

# A subset of xxHash's own sanity vectors, values verbatim from v0.8.2's
# tests/sanity_test_vectors.h (which holds thousands per algorithm), picked to
# straddle every length branch. Each row is (length, seed, expected).
VECTORS32 = (
    (0, 0, 0x02CC5D05),
    (0, PRIME32, 0x36B78AE7),
    (1, 0, 0xCF65B03E),
    (1, PRIME32, 0xB4545AA4),
    (14, 0, 0x1208E7E2),
    (14, PRIME32, 0x6AF1D1FE),
    (222, 0, 0x5BD11DBD),
    (222, PRIME32, 0x58803C5F),
)

VECTORS64 = (
    (0, 0, 0xEF46DB3751D8E999),
    (0, PRIME32, 0xAC75FDA2929B17EF),
    (1, 0, 0xE934A84ADB052768),
    (1, PRIME32, 0x5014607643A9B4C3),
    (4, 0, 0x9136A0DCA57457EE),
    (14, 0, 0x8282DCC4994E35C8),
    (14, PRIME32, 0xC3BD6BF63DEB6DF0),
    (222, 0, 0xB641AE8CB691C174),
    (222, PRIME32, 0x20CB8AB7AE10C14A),
)

# XXH3 branches by length, so its vectors deliberately straddle every boundary.
VECTORS3_64 = (
    (0, 0, 0x2D06800538D394C2),
    (0, PRIME64, 0xA8A6B918B2F0364A),
    (1, 0, 0xC44BDFF4074EECDB),
    (6, 0, 0x27B56A84CD2D7325),
    (12, 0, 0xA713DAF0DFBB77E7),
    (24, 0, 0xA3FE70BF9D3510EB),
    (48, 0, 0x397DA259ECBA1F11),
    (80, 0, 0xBCDEFBBB2C47C90A),
    (195, 0, 0xCD94217EE362EC3A),
    (403, 0, 0xCDEB804D65C6DEA4),
    (512, 0, 0x617E49599013CB6B),
    (2048, 0, 0xDD59E2C3A5F038E0),
    (2099, 0, 0xC6B9D9B3FC9AC765),
    (2240, 0, 0x6E73A90539CF2948),
    (2367, 0, 0xCB37AEB9E5D361ED),
)

# Upstream stores the 128-bit results as (low64, high64); the canonical digest is
# high first, so these are written the way the bytes come out.
VECTORS3_128 = (
    (0, 0, 0x99AA06D3014798D8, 0x6001C324468D497F),
    (1, 0, 0xA6CD5E9392000F6A, 0xC44BDFF4074EECDB),
    (6, 0, 0x082AFE0B8162D12A, 0x3E7039BDDA43CFC6),
    (12, 0, 0x6E3EFD8FC7802B18, 0x061A192713F69AD9),
)

VECTOR_BYTES = max(length for length, *_ in VECTORS3_64)


def sanity_buffer(length):
    """xxHash's own test buffer, byte for byte.

    `XSUM_fillTestBuffer` seeds a 64-bit generator with PRIME32 and takes the top
    byte of each step. The stream is prefix-stable, so one buffer of the longest
    length serves every vector by slicing - which is also why the published values
    for length 0, 1 and 14 all come from the same bytes.
    """
    out = bytearray(length)
    state = PRIME32
    for i in range(length):
        out[i] = (state >> 56) & 0xFF
        state = (state * PRIME64) & MASK64
    return bytes(out)


def check_vectors():
    """Recompute every published vector on this device; return (passed, total).

    These are the numbers upstream uses to decide a port is correct, so agreement
    here is the claim that this build produces the same digests as every other
    xxHash on any CPU - which no timing measurement can show.
    """
    if xxhash is None:
        return 0, 0
    buffer = sanity_buffer(VECTOR_BYTES)
    passed = total = 0
    checks = (
        (VECTORS32, xxhash.xxh32_intdigest),
        (VECTORS64, xxhash.xxh64_intdigest),
        (VECTORS3_64, xxhash.xxh3_64_intdigest),
    )
    for table, digest in checks:
        for length, seed, expected in table:
            total += 1
            passed += digest(buffer[:length], seed) == expected
    for length, seed, high, low in VECTORS3_128:
        total += 1
        expected = (high << 64) | low
        passed += xxhash.xxh3_128_intdigest(buffer[:length], seed) == expected
    return passed, total


def algorithms():
    """(label, one-shot callable) per table row; the callable is None when absent.

    `crc32` is in the list because it is the honest competitor - a checksum that is
    also fast and also not tamper-evident - and `md5`/`sha256` because they are what
    people reach for when they want either of those properties.
    """
    absent = xxhash is None
    return (
        ("xxh3_64", None if absent else xxhash.xxh3_64_intdigest),
        ("xxh64", None if absent else xxhash.xxh64_intdigest),
        ("xxh32", None if absent else xxhash.xxh32_intdigest),
        ("crc32", zlib.crc32),
        ("md5", lambda data: hashlib.md5(data).digest()),
        ("sha256", lambda data: hashlib.sha256(data).digest()),
    )


def timed(work):
    """Milliseconds for one call of `work`, best of several batches.

    Hashing 1 KiB costs tens of nanoseconds, far below what `perf_counter` can
    resolve, so a single call would report the clock rather than the algorithm - two
    different algorithms then land on the identical figure. The call is batched until
    a batch lasts a millisecond, and the batch is what gets timed.

    Best-of rather than mean, because a phone schedules across cores of different
    speeds and throttles under load: the fastest batch is the one that says what the
    hash costs, and the slow ones say what else the device was doing. Repeating stops
    once a batch passes the budget, since 16 MiB through `md5` costs a tenth of a
    second on a phone and five of those per row would turn one tap into a stall.
    """
    batch, elapsed = 1, 0.0
    while True:
        started = time.perf_counter()
        for _ in range(batch):
            work()
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed >= MIN_BATCH_MS or batch >= MAX_BATCH:
            break
        batch *= 8
    best = elapsed / batch
    for _ in range(REPEAT_ROUNDS):
        if elapsed > REPEAT_BUDGET_MS:
            break
        started = time.perf_counter()
        for _ in range(batch):
            work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = min(best, elapsed / batch)
    return best


def throughput(payloads):
    """Megabytes per second for every algorithm over every payload.

    Returns the display rows plus a `{label: {size_label: MB/s}}` map for the
    summary line. The same bytes go to every algorithm, which is the only way a
    comparison like this means anything.
    """
    rows, table = [], {}
    for label, digest in algorithms():
        speeds, cells = {}, []
        for size_label, data in payloads:
            if digest is None:
                cells.append("-")
                continue
            rate = len(data) / timed(lambda work=digest, d=data: work(d)) / 1000.0
            speeds[size_label] = rate
            cells.append(f"{rate:,.0f}")
        table[label] = speeds
        rows.append((label, *cells))
    return rows, table


def streaming(data):
    """Hash `data` twice - one call, then `CHUNK`-sized updates - and compare.

    The chunked path is what a file or a download needs, and it is not free: XXH3's
    one-shot entry point has a fast path the streaming state machine cannot use, so
    this returns both rates as well as the agreement.
    """
    if xxhash is None:
        return None
    one_shot_ms = timed(lambda: xxhash.xxh3_64_intdigest(data))
    view = memoryview(data)

    def feed():
        digest = xxhash.xxh3_64()
        for start in range(0, len(view), CHUNK):
            digest.update(view[start : start + CHUNK])
        return digest.intdigest()

    streamed_ms = timed(feed)
    scale = len(data) / 1000.0  # bytes per millisecond -> megabytes per second
    return (
        feed() == xxhash.xxh3_64_intdigest(data),
        scale / one_shot_ms,
        scale / streamed_ms,
    )


def collide(seed):
    """Find two 32-byte inputs with the same xxh32 digest, by birthday search.

    A 32-bit digest space needs roughly 2**16 tries, which is nothing. Every drawn
    message is kept rather than only its digest, so the pair can be shown on screen -
    a digest that repeats is only evidence if the two inputs that produced it differ.
    The generator is seeded, so the same seed gives the same pair and the same try
    count on every device, which is what makes the number checkable.
    """
    rng = random.Random(seed)
    seen = {}
    started = time.perf_counter()
    for tries in range(1, COLLISION_LIMIT + 1):
        message = rng.randbytes(COLLISION_LENGTH)
        digest = xxhash.xxh32_intdigest(message)
        earlier = seen.get(digest)
        if earlier is not None and earlier != message:
            return (
                tries,
                (time.perf_counter() - started) * 1000.0,
                digest,
                earlier,
                message,
            )
        seen[digest] = message
    return None, (time.perf_counter() - started) * 1000.0, None, b"", b""


def unxorshift(value, shift):
    """Undo `value ^= value >> shift`, which is a permutation of 32-bit words."""
    out = value
    for _ in range(32 // shift + 1):
        out = value ^ (out >> shift)
    return out & MASK32


def invert_xxh32_word(digest, seed=0):
    """Recover the four input bytes that produced this xxh32 digest.

    For an input of exactly four bytes every step XXH32 takes is a bijection on 32
    bits - add a constant, multiply by an odd prime, rotate, xor-shift - so the
    whole function is a permutation and running it backwards is arithmetic, not
    search. Nothing here is a weakness in xxHash; it is what "non-cryptographic"
    means.
    """
    state = unxorshift(digest, 16)
    state = (state * INV3) & MASK32
    state = unxorshift(state, 13)
    state = (state * INV2) & MASK32
    state = unxorshift(state, 15)
    state = (state * INV4) & MASK32
    state = ((state >> 17) | (state << 15)) & MASK32
    state = (state - ((seed + P5 + 4) & MASK32)) & MASK32
    return ((state * INV3) & MASK32).to_bytes(4, "little")


def inversion():
    """Invert a batch of four-byte digests and report how many came back exact."""
    rng = random.Random(SEED)
    started = time.perf_counter()
    recovered = 0
    for _ in range(INVERSION_TRIALS):
        original = rng.randbytes(4)
        recovered += invert_xxh32_word(xxhash.xxh32_intdigest(original)) == original
    return recovered, (time.perf_counter() - started) * 1000.0


def summarise(table, big_label):
    """One line pricing xxh3_64 against the checksum and the cryptographic hash."""
    fast = table.get("xxh3_64", {}).get(big_label)
    if not fast:
        return "xxhash absent - only the stdlib rows above were measured"
    crc = table["crc32"][big_label]
    sha = table["sha256"][big_label]
    return (
        f"at {big_label}: xxh3_64 {fast:,.0f} MB/s is {fast / sha:.1f}x sha256 "
        f"and {fast / crc:.2f}x crc32"
    )


def table_row(values, size=11):
    """One row of the speed table: a `Text` per cell, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, ROW_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Measure xxhash against the stdlib here, then demonstrate its two limits.

    Everything on screen is computed on the device. When the wheel is missing the
    app still runs: the header turns red and names what the import raised, the
    stdlib rows are still measured, and every xxhash cell reads `-`.
    """
    shown = next(iter(BIG_SIZES))  # the big payload the table on screen describes

    def start():
        """Send one measurement to the thread pool and lock the picker while it runs.

        The guard is set here, in the synchronous handler, rather than in the worker:
        `run_thread` only schedules, so a `disabled` set inside the worker would not
        have taken effect before a second tap could start an overlapping run. A tap
        that beat that `disabled` to the client is dropped, and the picker is put back
        to the size being measured - the client moves its own highlight the instant it
        is tapped, so without the reset the button would name one payload while the
        table below described another.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, shown)

    def run(big_label):
        """Measure, then check the vectors, then break xxh32 twice.

        The size is passed in rather than read off the picker, because the worker
        starts after the handler returns and a tap landing in between moves
        `picker.selected` out from under it.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises - without this, a failure would look like a screen that quietly stopped
        updating. The tables are cleared on the error path, since numbers left from the
        previous run would read as though they described the error.
        """
        try:
            rng = random.Random(SEED)
            payloads = [(label, rng.randbytes(size)) for size, label in SMALL_SIZES]
            payloads.append((big_label, rng.randbytes(BIG_SIZES[big_label])))
            rows, table = throughput(payloads)
            speeds.controls = [
                table_row(("MB/s", *(label for label, _ in payloads))),
                ft.Divider(height=1),
                *(table_row(row) for row in rows),
            ]
            summary.value = summarise(table, big_label)

            result = streaming(payloads[-1][1])
            if result is None:
                chunks.value = "streaming API needs the xxhash wheel"
            else:
                agrees, one_shot_rate, streamed_rate = result
                chunks.value = (
                    f"{big_label} in {CHUNK // 1024} KiB updates "
                    f"{'matches' if agrees else 'DIFFERS FROM'} the one-shot digest - "
                    f"{streamed_rate:,.0f} MB/s streamed against "
                    f"{one_shot_rate:,.0f} one-shot"
                )

            passed, total = check_vectors()
            vectors.value = (
                "xxhash absent - published vectors not checked"
                if total == 0
                else f"{passed}/{total} published xxHash v0.8.2 vectors reproduced - "
                f"xxh64('') {xxhash.xxh64_hexdigest(b'')}, "
                f"xxh3_64('') {xxhash.xxh3_64_hexdigest(b'')}"
            )

            if xxhash is None:
                collisions.value = "xxhash absent - no collision search"
                pair.value = ""
                inverted.value = "xxhash absent - no inversion"
            else:
                found = [collide(seed) for seed in COLLISION_SEEDS]
                collisions.value = "xxh32 collisions after " + " / ".join(
                    "gave up" if tries is None else f"{tries:,} tries in {ms:,.0f} ms"
                    for tries, ms, *_ in found
                )
                _, _, digest, first, second = min(found, key=lambda row: row[1])
                pair.value = (
                    f"{first.hex()[:16]}... and {second.hex()[:16]}... "
                    f"both hash to {digest:08x}"
                )
                recovered, invert_ms = inversion()
                inverted.value = (
                    f"{recovered:,}/{INVERSION_TRIALS:,} four-byte inputs recovered "
                    f"from their xxh32 digest alone in {invert_ms:,.0f} ms"
                )
        except Exception as error:  # the worker must never let one escape
            speeds.controls = []
            chunks.value = ""
            vectors.value = ""
            collisions.value = pair.value = inverted.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    library = (
        f"xxhash absent - {IMPORT_ERROR}"
        if xxhash is None
        else f"xxhash {xxhash.VERSION} - bundled libxxhash {xxhash.XXHASH_VERSION}"
    )
    page.appbar = ft.AppBar(title=ft.Text("xxhash stream digest"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library,
                        size=11,
                        color=ft.Colors.ERROR if xxhash is None else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=label, label=ft.Text(label))
                                    for label in BIG_SIZES
                                ],
                                selected=[
                                    next(iter(BIG_SIZES))
                                ],  # a set dies in msgpack
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    speeds := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("streaming, same bytes", size=11),
                    chunks := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("published test vectors", size=11),
                    vectors := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("what it is not", size=11),
                    collisions := ft.Text(size=11, color=ft.Colors.ERROR),
                    pair := ft.Text(size=11, color=ft.Colors.ERROR),
                    inverted := ft.Text(size=11, color=ft.Colors.ERROR),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
