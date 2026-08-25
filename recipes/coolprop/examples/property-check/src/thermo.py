"""The CoolProp half of the example: plain values out, and no Flet anywhere in here.

Importing *this* module has to stay cheap. `import CoolProp` parses the whole fluid
database compiled into the extension — the app's single largest cost — so it happens in
load(), which main.py calls from the thread pool once there is a frame on screen. Nothing
below touches CoolProp at module scope; every reference reaches for `_cp`, which a lambda
and a function body both resolve at call time rather than at import time.
"""

import sys
import time

# A row agrees when its relative error is at or under this. Every row below sits at
# 3e-5 or better on desktop CoolProp 7.2.0, so this leaves better than 3x headroom.
TOLERANCE = 1e-4
SWEEP_POINTS = 200
FLUIDS = ["Water", "R134a", "Ammonia"]

_cp = None  # CoolProp.CoolProp, bound by load()
_package = None  # the CoolProp package itself, for the version and the record counts

# (label, unit, published value, source, call).
REFERENCES = [
    (
        "Water triple-point temperature",
        "K",
        273.16,
        "ITS-90",
        lambda: _cp.PropsSI("Ttriple", "Water"),
    ),
    (
        "Water critical temperature",
        "K",
        647.096,
        "IAPWS-95",
        lambda: _cp.PropsSI("Tcrit", "Water"),
    ),
    (
        "Water critical pressure",
        "Pa",
        22.064e6,
        "IAPWS-95",
        lambda: _cp.PropsSI("pcrit", "Water"),
    ),
    (
        "Water boiling point at 101325 Pa",
        "K",
        373.1243,
        "IAPWS-95",
        lambda: _cp.PropsSI("T", "P", 101325, "Q", 0, "Water"),
    ),
    (
        "Water density at 25 °C and 101325 Pa",
        "kg/m³",
        997.047,
        "IAPWS-95",
        lambda: _cp.PropsSI("D", "T", 298.15, "P", 101325, "Water"),
    ),
    (
        "Nitrogen normal boiling point",
        "K",
        77.355,
        "NIST",
        lambda: _cp.PropsSI("T", "P", 101325, "Q", 0, "Nitrogen"),
    ),
    (
        "R134a saturation pressure at 25 °C",
        "Pa",
        665400.0,
        "NIST",
        lambda: _cp.PropsSI("P", "T", 298.15, "Q", 0, "R134a"),
    ),
    (
        "CO₂ triple-point pressure",
        "Pa",
        517950.0,
        "NIST",
        lambda: _cp.PropsSI("ptriple", "CO2"),
    ),
    (
        "Saturation humidity ratio, moist air at 25 °C and 101325 Pa",
        "kg/kg",
        0.020173,
        "ASHRAE Fundamentals",
        lambda: _cp.HAPropsSI("W", "T", 298.15, "P", 101325, "R", 1.0),
    ),
]

# Three requests CoolProp should refuse. Two of them it does; the third is the point.
PROBES = [
    (
        "HAPropsSI at 100 K, below the humid-air model's floor",
        lambda: _cp.HAPropsSI("W", "T", 100, "P", 101325, "R", 0.5),
    ),
    (
        "Saturation pressure of water at 700 K, above its critical point",
        lambda: _cp.PropsSI("P", "T", 700, "Q", 0, "Water"),
    ),
    (
        "Density of water at 100000 K, fifty times its own declared T_max",
        lambda: _cp.PropsSI("D", "T", 100000, "P", 101325, "Water"),
    ),
]


def _rss_mib():
    """Peak resident set size in MiB, or None where the `resource` module is unavailable.

    `ru_maxrss` is a high-water mark, not the current footprint, so the pair either side
    of the import bounds what the import cost rather than measuring it exactly. It is
    also bytes on Darwin and iOS but kibibytes on Linux and Android, so the raw number
    means nothing until the platform is known.
    """
    try:
        import resource
    except ImportError:
        return None
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / 2**20 if sys.platform in ("darwin", "ios") else raw / 2**10


def load():
    """Import CoolProp, bind it for every other function here, and price the import.

    CoolProp's package `__init__` asks the extension for the full fluid list, which forces
    the embedded database to be decompressed and parsed — hundreds of milliseconds and a
    large allocation that would otherwise delay the first frame. Returns the one line only
    a device can supply: what that cost here.
    """
    global _cp, _package
    before = _rss_mib()
    started = time.perf_counter()

    import CoolProp
    import CoolProp.CoolProp

    elapsed = (time.perf_counter() - started) * 1000
    after = _rss_mib()
    _package, _cp = CoolProp, CoolProp.CoolProp

    cost = f"import CoolProp: {elapsed:.0f} ms"
    if before is not None and after is not None:
        cost += f", peak RSS {before:.0f} → {after:.0f} MiB"
    return cost


def library_line():
    """What the loaded library says about itself: version, Python, and the record counts."""
    return (
        f"CoolProp {_package.__version__}, Python {sys.version.split()[0]} — "
        f"{len(_package.__fluids__)} fluids, "
        f"{len(_package.__incompressibles_pure__)} pure incompressibles, "
        f"{len(_package.__incompressibles_solution__)} solutions"
    )


def checks():
    """Every reference row as (label, passed, detail).

    Each row catches its own failure, so one fluid missing on one platform costs one row
    rather than replacing the whole table with a single message.
    """
    rows = []
    for label, unit, reference, source, call in REFERENCES:
        try:
            got = call()
            error = abs(got - reference) / abs(reference)
            detail = f"{got:.7g} vs {reference:.7g} {unit} ({source}) — rel {error:.1e}"
            rows.append((label, error <= TOLERANCE, detail))
        except Exception as exc:
            rows.append((label, False, f"{type(exc).__name__}: {exc}"))
    return rows


def limits_line():
    """The bounds CoolProp itself reports for water — the ones the probes below ignore."""
    return (
        f"CoolProp reports T_max = {_cp.PropsSI('Tmax', 'Water'):.0f} K and "
        f"p_max = {_cp.PropsSI('pmax', 'Water'):.3g} Pa for water."
    )


def probes():
    """Every out-of-range request as (label, refused, answer).

    `refused` is the wanted outcome: a ValueError naming the offending value. A row that
    comes back with a number instead is the trap this example exists to show. Anything
    other than a ValueError is itself worth seeing, and costs only its own row.
    """
    rows = []
    for label, call in PROBES:
        try:
            rows.append((label, False, f"returned {call():.6g} — no exception"))
        except ValueError as exc:
            rows.append((label, True, f"ValueError: {exc}"))
        except Exception as exc:
            rows.append((label, False, f"{type(exc).__name__}: {exc}"))
    return rows


def sweep(fluid, percent):
    """Saturation properties `percent` of the way up the dome, timed both ways CoolProp offers.

    Returns three lines: the state, its properties, and what the sweep cost per call.

    PropsSI rebuilds its backend on every call, so the identical sweep through one reused
    AbstractState is far cheaper. How much cheaper is the number a CoolProp app should
    budget against, and only the device it ships to can supply it.
    """
    t_min = _cp.PropsSI("Ttriple", fluid)
    t_max = _cp.PropsSI("Tcrit", fluid)
    temperature = t_min + (t_max - t_min) * percent / 100

    pressure = _cp.PropsSI("P", "T", temperature, "Q", 0, fluid)
    liquid = _cp.PropsSI("D", "T", temperature, "Q", 0, fluid)
    vapour = _cp.PropsSI("D", "T", temperature, "Q", 1, fluid)
    latent = _cp.PropsSI("H", "T", temperature, "Q", 1, fluid) - _cp.PropsSI(
        "H", "T", temperature, "Q", 0, fluid
    )

    points = [
        t_min + (t_max - t_min) * (i + 0.5) / SWEEP_POINTS for i in range(SWEEP_POINTS)
    ]

    started = time.perf_counter()
    for point in points:
        _cp.PropsSI("P", "T", point, "Q", 0, fluid)
    per_call = (time.perf_counter() - started) / SWEEP_POINTS * 1e6

    # Built here rather than cached: an AbstractState holds one mutable state point, so
    # the thread doing the sweep should own it outright.
    state = _cp.AbstractState("HEOS", fluid)
    started = time.perf_counter()
    for point in points:
        state.update(_cp.QT_INPUTS, 0, point)
        state.p()
    per_update = (time.perf_counter() - started) / SWEEP_POINTS * 1e6

    return (
        f"{fluid} saturated at {temperature:.2f} K ({temperature - 273.15:.2f} °C)",
        f"p = {pressure / 1000:.4g} kPa · ρ_liq = {liquid:.5g} kg/m³ · "
        f"ρ_vap = {vapour:.5g} kg/m³ · h_fg = {latent / 1000:.5g} kJ/kg",
        f"{SWEEP_POINTS} points up the dome: PropsSI {per_call:.1f} µs/call, "
        f"one reused AbstractState {per_update:.2f} µs/call "
        f"({per_call / per_update:.0f}x)",
    )
