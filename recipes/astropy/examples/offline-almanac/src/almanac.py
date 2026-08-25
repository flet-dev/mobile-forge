"""The astronomy, with no Flet in it: every function returns plain values.

Each number here comes from data that shipped inside the wheels, and each answer arrives
with its own verdict attached rather than as a bare figure.
"""

import math
import os
import tempfile

import numpy as np

# astropy resolves its config directory while `import astropy` is still running, and falls
# back to Path.home() — which raises on the Flet iOS runtime, since that has no `pwd` module
# to fall back to when HOME is unset. astropy 8 also ignores these two variables unless the
# directories already exist, so the makedirs is the load-bearing half: setting the variables
# without it warns once and then crashes anyway.
_TEMP = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
_DATA = os.getenv("FLET_APP_STORAGE_DATA") or _TEMP
_CONFIG_DIR = os.path.join(_DATA, "astropy", "config")
_CACHE_DIR = os.path.join(_TEMP, "astropy", "cache")
os.makedirs(_CONFIG_DIR, exist_ok=True)
os.makedirs(_CACHE_DIR, exist_ok=True)
os.environ.setdefault("ASTROPY_CONFIG_DIR", _CONFIG_DIR)
os.environ.setdefault("ASTROPY_CACHE_DIR", _CACHE_DIR)

import astropy  # noqa: E402
import astropy.units as u  # noqa: E402
import astropy.utils.data  # noqa: E402
import astropy_iers_data  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.time import Time  # noqa: E402
from astropy.utils import iers  # noqa: E402

# Two switches, because they cover different things. Without auto_download=False every
# Earth-orientation lookup re-tries two download URLs at a 10 s timeout each; without
# allow_internet=False the same lookups still emit three warnings apiece. The
# astropy.utils.data import above is what makes the second line legal: plain
# `import astropy` leaves astropy.utils.data unbound.
iers.conf.auto_download = False
astropy.utils.data.conf.allow_internet = False

FITS_PATH = os.path.join(_DATA, "roundtrip.fits")

# Berlin, hard-coded: EarthLocation.of_site downloads a site catalogue that is not in the
# wheel, so it raises offline rather than degrading.
SITE = EarthLocation(lat=52.520008 * u.deg, lon=13.404954 * u.deg, height=34 * u.m)

# ICRS positions with the galactic coordinates SIMBAD publishes for them. Those are quoted
# to four decimal degrees, so agreement closer than 0.36" is all the reference can prove.
OBJECTS = [
    ("M31", 10.684708, 41.268750, 121.1743, -21.5733),
    ("Betelgeuse", 88.792939, 7.407064, 199.7872, -8.9586),
    ("Sgr A*", 266.416837, -29.007810, 359.9442, -0.0462),
    ("M1 (Crab)", 83.633083, 22.014500, 184.5575, -5.7844),
]
QUOTING_PRECISION = 0.36

# 1 pc = 648000/pi au and 1 ly = 9460730472580800 m, both exact by IAU definition, so the
# ratio is a reference the app can derive rather than remember.
PC_IN_LYR = (648000 / math.pi * 149597870700) / 9460730472580800

TARGET = SkyCoord(ra=OBJECTS[0][1] * u.deg, dec=OBJECTS[0][2] * u.deg, frame="icrs")

HEADER = (
    f"astropy {astropy.__version__} · astropy-iers-data {astropy_iers_data.__version__}\n"
    f"auto_download={iers.conf.auto_download} · "
    f"allow_internet={astropy.utils.data.conf.allow_internet}"
)

NOT_ATTEMPTED = (
    "Not attempted, because each is a download with nothing bundled behind it: "
    "EarthLocation.of_site and get_site_names (site catalogue), SkyCoord.from_name "
    "(Sesame), EarthLocation.of_address (geocoding), and solar_system_ephemeris.set('jpl') "
    "(needs jplephem, which is not installed). Sun and Moon above come from ERFA's built-in "
    "ephemeris instead."
)

FROZEN = (
    "Earth orientation: PAST THE TABLE. UT1-UTC is frozen at its last value with no warning. "
    "Leap seconds cap frozen and true at 0.9 s each, so they differ by up to 1.8 s, and 1 s "
    'of UT1 error is 15.04" x cos(dec) of sky error — ~11" for M31 here, ~27" on the '
    "celestial equator."
)


def table_span():
    """Read the coverage of the bundled IERS-A table off the table itself.

    Returns the first and last MJD it holds and the last row that is a measurement rather
    than a prediction — the three dates that bound how far this build can be trusted.
    """
    tbl = iers.IERS_Auto.open()
    mjd = np.asarray(tbl["MJD"].value, dtype=float)
    measured = mjd[np.asarray(tbl["UT1Flag"]) != "P"]
    return mjd.min(), mjd.max(), measured.max()


def coverage():
    """One sentence naming the dates the bundled Earth-orientation table covers."""
    first, last, measured = table_span()
    return (
        f"Bundled Earth orientation covers {Time(first, format='mjd').iso[:10]} to "
        f"{Time(last, format='mjd').iso[:10]}, measured to "
        f"{Time(measured, format='mjd').iso[:10]}."
    )


def almanac(months_from_now):
    """Compute the whole almanac for a date `months_from_now` months away.

    Returns `(status, banner, report)`: a status of "measured", "predicted" or "frozen" for
    the caller to colour, the sentence explaining it, and the block of sky positions.

    The first call is by far the slowest — opening the Earth-orientation table parses
    ~20,000 rows out of the two bundled files, measured at 330 ms on a development machine
    and cached from then on — so callers should keep this off the UI thread.
    """
    _, last, measured = table_span()
    when = Time.now() + float(months_from_now) * 30.4375 * u.day
    sun, moon = get_body("sun", when), get_body("moon", when)
    alt = TARGET.transform_to(AltAz(obstime=when, location=SITE))
    dut1 = float(np.ravel(np.asarray(when.delta_ut1_utc))[0])
    tai_utc = (when.tai.jd - when.utc.jd) * 86400
    # Read after that first conversion on purpose: until astropy has loaded Leap_Second.dat
    # into ERFA, this still reports pyerfa's compiled-in 2017 expiry, which reads as a table
    # nine years stale.
    leap_expires = iers.LeapSeconds.from_erfa().expires.iso[:10]

    report = (
        f"{when.utc.isot[:19]} UTC   TAI-UTC {tai_utc:.0f} s\n"
        f"Leap-second table expires {leap_expires}\n"
        f"Sun    RA {sun.ra.deg:8.3f}  Dec {sun.dec.deg:+7.3f}\n"
        f"Moon   RA {moon.ra.deg:8.3f}  Dec {moon.dec.deg:+7.3f}\n"
        f"M31 from Berlin   alt {alt.alt.deg:+7.3f}  az {alt.az.deg:8.3f}\n"
        f"UT1-UTC {dut1:+.6f} s"
    )
    if when.mjd <= measured:
        return "measured", "Earth orientation: measured", report
    if when.mjd <= last:
        left = last - when.mjd
        return "predicted", f"Earth orientation: predicted, {left:.0f} days left", report
    return "frozen", FROZEN, report


def self_checks():
    """Run the checks whose answers are known in advance, and report pass or fail.

    Each exercises a different part of the wheel — the unit machinery, the leap-second
    table, the ERFA-backed frame transforms, the vendored cfitsio writer — against a value
    that comes from a definition or a catalogue rather than from astropy itself.
    """
    lines = []

    ratio = (1 * u.pc).to(u.lyr).value
    ok = math.isclose(ratio, PC_IN_LYR, rel_tol=1e-12)
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  1 pc = {ratio:.10f} lyr (IAU: {PC_IN_LYR:.10f})"
    )

    leap = Time("2016-12-31T23:59:60", scale="utc")
    ok = leap.tai.isot == "2017-01-01T00:00:36.000"
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  leap second 23:59:60 UTC -> {leap.tai.isot} TAI"
    )

    worst, worst_name = 0.0, ""
    for name, ra, dec, gl, gb in OBJECTS:
        got = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs").galactic
        sep = got.separation(
            SkyCoord(l=gl * u.deg, b=gb * u.deg, frame="galactic")
        ).arcsec
        if sep > worst:
            worst, worst_name = sep, name
    ok = worst <= QUOTING_PRECISION
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  ICRS->galactic, worst of {len(OBJECTS)} "
        f'({worst_name}) {worst:.2f}" vs {QUOTING_PRECISION}" quoting precision'
    )

    data = np.linspace(0, 1, 64, dtype="float32").reshape(8, 8)
    hdu = fits.PrimaryHDU(data)
    hdu.header["OBJECT"] = "M31"
    hdu.writeto(FITS_PATH, overwrite=True)
    with fits.open(FITS_PATH) as opened:
        back, header = opened[0].data, opened[0].header
    ok = np.array_equal(back, data) and header["OBJECT"] == "M31"
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  FITS round trip, {os.path.getsize(FITS_PATH)} bytes, "
        f"max|diff| {np.abs(back - data).max():.1f}"
    )

    try:
        1 * u.m + 1 * u.s
        lines.append("FAIL  1 m + 1 s was accepted")
    except Exception as exc:
        lines.append(f"PASS  1 m + 1 s raised {type(exc).__name__}, caught here: {exc}")

    return lines
