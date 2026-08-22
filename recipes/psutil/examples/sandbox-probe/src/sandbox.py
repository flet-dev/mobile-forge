"""Every question this example asks psutil, and the second sources it checks against."""

import os
import platform
import time
import warnings

try:
    import psutil

    IMPORT_ERROR = None
except Exception as error:
    # Not only ModuleNotFoundError: a psutil built without this recipe's patch
    # raises NotImplementedError("platform android is not supported") instead.
    psutil = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

# Three outcomes, not two. A call that returned None, or that degraded to a warning
# and an invented number, answered nothing — scoring it alongside the calls that
# worked would let a soft failure satisfy the headline count.
OK, SOFT, FAILED = "ok", "soft", "failed"

SIZES = (8, 16, 32, 64, 128)  # MB, decimal: 10**6 bytes

# Wide enough for the longest bounded value on Linux: `virtual_memory()` spells
# out eleven fields there, about 218 characters on a 24 GB device, and truncating
# it would hide the very field names this screen exists to show.
CELL = 260
LINES = 24

PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def trim(text):
    """`text` bounded to a few lines of a cell each, each cut from the middle.

    The middle rather than the end because the end is where the answer is: a
    cross-check line finishes with its verdict, so chopping the tail would
    silently turn `they DIFFER` into `they …` — hiding the one word the row
    exists to say.
    """
    kept = text.split("\n")[:LINES]
    half = CELL // 2
    return "\n".join(
        line if len(line) <= CELL else f"{line[:half]}…{line[-half:]}" for line in kept
    )


def amount(value):
    """One namedtuple field, formatted short enough to sit beside its siblings."""
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return repr(value)


def fields(value):
    """A namedtuple as `name=value` pairs.

    Spelled out rather than repr'd because the field names are half the
    answer: the Linux tuples psutil returns here have different — and more —
    fields than the macOS ones the same call gives on a development machine.
    """
    return " ".join(f"{name}={amount(item)}" for name, item in value._asdict().items())


def stamp(seconds):
    """An epoch timestamp as local time plus the raw value."""
    moment = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))
    return f"{moment} ({seconds:.0f})"


def current():
    """A `Process` for this app's own PID.

    Rebuilt per row rather than shared, so that a construction that fails —
    it reads /proc/<pid>/stat — is reported on every row it would affect
    instead of taking the whole screen down.
    """
    return psutil.Process()


def rss():
    """This process's resident set size, in bytes."""
    return current().memory_info().rss


def family(address):
    """The address family of one `snicaddr`, by name where it has one."""
    return getattr(address.family, "name", None) or str(address.family)


def interfaces():
    """Every network interface with, per family, the address psutil reports.

    One interface per line rather than one long line: whether Android hands out
    a real hardware MAC, an anonymised one, or none at all is the thing worth
    seeing, and a phone lists enough interfaces that running them together
    pushes the interesting ones past what a cell will hold. The count leads, so
    a device with more interfaces than the cell has lines still says so.
    """
    found = psutil.net_if_addrs()
    listed = "\n".join(
        f"{name}: " + ",".join(f"{family(one)}={one.address}" for one in addresses)
        for name, addresses in found.items()
    )
    return f"{len(found)} interfaces\n{listed}"


def physical_cores():
    """psutil's physical-core count, a wholly different code path from the logical one.

    Returned with a soft flag when it is `None`, which is the likely answer on ARM:
    the function is documented to answer `None` rather than raise, and a green dot
    for "the call returned, having found nothing" is the lie this screen exists to
    avoid.
    """
    count = psutil.cpu_count(logical=False)
    return repr(count), count is None


def cpu_share():
    """System-wide CPU usage, sampled over the 0.3 s it asks for.

    The blocking form on purpose: the non-blocking one measures since this
    thread's last call, and a screen that runs once has no previous call.
    """
    return repr(psutil.cpu_percent(interval=0.3))


def connections():
    """How many sockets psutil can enumerate system-wide."""
    return f"{len(psutil.net_connections())} connections"


def open_files():
    """How many regular files this process has open."""
    return f"{len(current().open_files())} files"


def mounts(everything):
    """How many mountpoints `disk_partitions` reports, and the first few."""
    found = psutil.disk_partitions(all=everything)
    listed = ", ".join(part.mountpoint for part in found[:6])
    return f"{len(found)} mounts: {listed}"


def running():
    """How many processes this app can see, and what they call themselves.

    The count is the sandbox story, so it is printed rather than the list
    being tidied: `pids()` is `os.listdir('/proc')`, so a confined app gets a
    short honest answer here instead of an exception.
    """
    names = [proc.info["name"] for proc in psutil.process_iter(["name"])]
    listed = ", ".join(sorted(name for name in names if name))
    return f"{len(names)} processes: {listed}"


def verdict(mine, theirs, tolerance):
    """Whether two independently obtained numbers agree, and by how much they miss."""
    gap = abs(mine - theirs)
    return "agrees" if gap <= tolerance else f"DIFFERS by {gap:,.0f}"


def compare(label, mine, ask, tolerance=0):
    """One cross-check line: a value obtained without psutil, then psutil's.

    psutil's half is called here and guarded separately, so a row whose psutil
    call is blocked still shows what a plain `open()` returned — which is the
    only reason to have a second source in the first place.
    """
    try:
        theirs = ask()
    except Exception as error:
        return f"{label}={mine:,.0f} · psutil raised {type(error).__name__}"
    if not isinstance(theirs, (int, float)):
        # `cpu_count()` is documented to answer None rather than raise, and
        # "psutil raised TypeError" from the format below would blame the
        # wrong side of the comparison.
        return f"{label}={mine:,.0f} · psutil returned {theirs!r}"
    return f"{label}={mine:,.0f} · psutil={theirs:,.0f} · {verdict(mine, theirs, tolerance)}"


def cross_cpu_count():
    """`os.cpu_count()` — the same `sysconf` psutil calls — against psutil's.

    The affinity mask is printed alongside but deliberately not required to
    match. Android confines an app to a cpuset, so a perfectly healthy device
    lets you run on fewer CPUs than it has online; demanding all three agree
    would report that as a disagreement and blame psutil for it.
    """
    line = compare("os.cpu_count()", os.cpu_count(), psutil.cpu_count)
    if hasattr(os, "sched_getaffinity"):
        line += f" · affinity mask allows {len(os.sched_getaffinity(0))}"
    return line


def cross_mem_total():
    """Total RAM parsed by hand out of /proc/meminfo, against psutil's."""
    with open("/proc/meminfo", "rb") as handle:
        for line in handle:
            if line.startswith(b"MemTotal:"):
                mine = int(line.split()[1]) * 1024
                break
        else:
            return "/proc/meminfo carries no MemTotal line"
    return compare("MemTotal", mine, lambda: psutil.virtual_memory().total)


def cross_rss():
    """RSS from /proc/self/statm, the same file psutil's `memory_info` reads.

    A few pages of difference is this process allocating between the two
    reads rather than a disagreement, so the tolerance is four pages wide.
    """
    with open("/proc/self/statm", "rb") as handle:
        mine = int(handle.read().split()[1]) * PAGE_SIZE
    return compare("statm rss", mine, rss, tolerance=4 * PAGE_SIZE)


def cross_boot_time():
    """Boot time derived from CLOCK_BOOTTIME instead of /proc/stat's btime."""
    mine = time.time() - time.clock_gettime(time.CLOCK_BOOTTIME)
    return compare("time.time() - CLOCK_BOOTTIME", mine, psutil.boot_time, tolerance=2)


def cross_cwd():
    """The working directory as the stdlib, Flet and psutil each report it.

    From Flet 0.86 the app-storage data directory is also the process working
    directory on device, so on Android these three are one check rather than
    three unrelated strings. Off device they routinely disagree — a desktop
    run has its own working directory, and macOS resolves /var through a
    symlink — which is exactly why the verdict is printed instead of assumed.
    """
    here = os.getcwd()
    stored = os.getenv("FLET_APP_STORAGE_DATA")
    try:
        theirs = psutil.Process().cwd()
    except Exception as error:
        theirs = f"<{type(error).__name__}>"
    same = "all three agree" if theirs == here == stored else "they DIFFER"
    return f"os.getcwd()={here!r} · FLET_APP_STORAGE_DATA={stored!r} · {same}"


def probes():
    """The fixed, ordered list of calls this screen makes.

    Each entry is a label, a callable returning what to print, and an optional
    cross-check computed without psutil. System-wide queries come first and
    this process's own second, because that is the order the Android sandbox
    stops cooperating in: the system-wide ones read files under /proc that
    belong to no one, the rest read the app's own /proc/<pid>/ tree.
    """
    data = os.getenv("FLET_APP_STORAGE_DATA", ".")
    return (
        ("cpu_count()", lambda: repr(psutil.cpu_count()), cross_cpu_count),
        ("cpu_count(logical=False)", physical_cores, None),
        ("cpu_percent(interval=0.3)", cpu_share, None),
        ("cpu_times()", lambda: fields(psutil.cpu_times()), None),
        ("virtual_memory()", lambda: fields(psutil.virtual_memory()), cross_mem_total),
        ("swap_memory()", lambda: fields(psutil.swap_memory()), None),
        ("disk_usage(app storage)", lambda: fields(psutil.disk_usage(data)), None),
        ("disk_partitions()", lambda: mounts(False), None),
        ("disk_partitions(all=True)", lambda: mounts(True), None),
        ("net_if_addrs()", interfaces, None),
        ("net_connections()", connections, None),
        ("boot_time()", lambda: stamp(psutil.boot_time()), cross_boot_time),
        ("Process().memory_info()", lambda: fields(current().memory_info()), cross_rss),
        ("Process().cpu_times()", lambda: fields(current().cpu_times()), None),
        ("Process().num_threads()", lambda: repr(current().num_threads()), None),
        ("Process().open_files()", open_files, None),
        ("Process().cmdline()", lambda: repr(current().cmdline()), None),
        ("Process().exe()", lambda: repr(current().exe()), None),
        ("Process().cwd()", lambda: repr(current().cwd()), cross_cwd),
        ("Process().name()", lambda: repr(current().name()), None),
        ("process_iter()", running, None),
    )


def attempt(work):
    """Call `work` and report the outcome as one of the three states plus its text.

    The refusals are the payload of this screen, so the catch is deliberately
    broad — the system-wide psutil functions are not exception-translated and
    raise a plain `PermissionError` rather than `psutil.AccessDenied`, and an
    unhandled exception in a Flet handler crashes the session instead of
    printing anything. A warning demotes the row to SOFT rather than leaving it
    green: `swap_memory()` degrades to a `RuntimeWarning` and invented `sin`
    and `sout` values where its neighbours raise.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            answer = work()
        except Exception as error:
            return FAILED, f"{type(error).__name__}: {error}"
    text, soft = answer if isinstance(answer, tuple) else (answer, False)
    for warning in caught:
        text += f" [{warning.category.__name__}: {warning.message}]"
        soft = True
    return (SOFT if soft else OK), trim(text)


def survey():
    """Run every probe once and return a (label, state, answer, cross-check) row each.

    A cross-check is attempted separately from the call it checks, so a row whose
    psutil call was refused still shows what a plain `open()` returned.
    """
    return [
        (label, *attempt(call), attempt(cross)[1] if cross else None)
        for label, call, cross in probes()
    ]


def summary(rows):
    """The headline tally, keeping soft answers out of the answered count."""
    answered = sum(state == OK for _, state, _, _ in rows)
    soft = sum(state == SOFT for _, state, _, _ in rows)
    refused = len(rows) - answered - soft
    return f"{answered} answered · {soft} degraded · {refused} refused"


def environment():
    """One line naming what is running: psutil if it imported, Python, the machine."""
    version = f"psutil {psutil.__version__}" if psutil else "psutil absent"
    return f"{version} · Python {platform.python_version()} · {platform.machine()}"


def measure(megabytes):
    """Allocate `megabytes`, touch every page of it, and report where RSS went.

    Touching is what makes this a measurement: a fresh `bytearray` is pages
    the kernel has promised and not yet handed over, so RSS only follows the
    request once every one of them has been written to. MB is decimal here,
    matching the byte counts the screen prints beside it.
    """
    wanted = megabytes * 1_000_000
    before = rss()
    block = bytearray(wanted)
    for offset in range(0, wanted, PAGE_SIZE):
        block[offset] = 1
    held = rss()
    del block
    freed = rss()
    return wanted, before, held, freed
